"""Phase 7.5 Shot 方向协调服务。

本服务是 Position 支路 direction_locked 与 State 支路 start_entered 的唯一合流点：
先复用 StoneStateEventBridge 解析 lane/running match，再在 departure 时用 tag 严格相等决定
是否把预投方向注入 Phase 5。这里不读取 PositionCache、不调用 Director、不切视频。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.curling_state_edge import StoneStateEdge
from app.models.shot_coordination import ShotCoordinationResult, ShotDirectionAlignmentStatus
from app.models.stone_state_semantic import StoneStateSemanticEvent
from app.services.direction_service import DirectionService
from app.services.pre_shot_direction_service import PreShotDirectionLock, PreShotDirectionService
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_event_bridge import StoneStateEventBridge


@dataclass(frozen=True)
class _ActiveShotDirection:
    """当前 match + sheet 一投期间的方向协调摘要，只保存在内存中。"""

    alignment_status: ShotDirectionAlignmentStatus
    candidate_tag_id: str | None
    moving_stone_tag_id: str
    resolved_direction: str
    resolved_source_end: str | None
    resolved_target_end: str | None


class ShotDirectionCoordinationService:
    """协调 Pre-shot Lock、StoneState Edge 与 Phase 5 Shot 生命周期。"""

    def __init__(
        self,
        *,
        pre_shot_direction_service: PreShotDirectionService | None = None,
        direction_service: DirectionService | None = None,
        stone_event_service: StoneEventService | None = None,
        bridge: StoneStateEventBridge | None = None,
    ) -> None:
        self._pre_shot_direction_service = pre_shot_direction_service or PreShotDirectionService()
        self._direction_service = direction_service or DirectionService()
        self._stone_event_service = stone_event_service or StoneEventService(direction_service=self._direction_service)
        self._bridge = bridge or StoneStateEventBridge(stone_event_service=self._stone_event_service)
        self._active: dict[tuple[str, str], _ActiveShotDirection] = {}

    def process(self, edge: StoneStateEdge) -> ShotCoordinationResult | None:
        """处理单条 State Edge；无法解析 running match 时返回 None。"""

        semantic = self._bridge.convert(edge)
        if semantic is None:
            return None

        alignment = self._prepare_departure_direction(semantic) if semantic.event_type == "departure" else self._current_alignment(semantic)
        context = self._bridge.dispatch(semantic)
        if semantic.event_type == "stop":
            # stop dispatch 正常返回后才 reset；即使 Phase 5 因无 active Shot 返回 None，也要释放 stale lock。
            self.reset(semantic.match_id, semantic.sheet_id)
        return self._result(semantic, alignment, context)

    def reset(self, match_id: str, sheet_id: str) -> None:
        """释放单个 match + sheet 的预投锁、方向状态和本协调器临时状态。"""

        self._pre_shot_direction_service.reset(match_id, sheet_id)
        # Phase 5 正常 FINISHED stop 已经会 reset；这里补齐 stop without active Shot 等降级路径。
        self._direction_service.reset(sheet_id, match_id=match_id)
        self._active.pop((match_id, sheet_id), None)

    def clear_match(self, match_id: str) -> None:
        """清理某个 match 下的预投锁和协调临时状态。"""

        self._pre_shot_direction_service.clear_match(match_id)
        for key in list(self._active):
            if key[0] == match_id:
                self._active.pop(key, None)

    def clear(self) -> None:
        """清理全部协调状态，主要用于测试、Replay 或重连恢复。"""

        self._pre_shot_direction_service.clear()
        self._active.clear()

    def get_active_alignment(self, match_id: str, sheet_id: str) -> _ActiveShotDirection | None:
        """读取当前一投的协调摘要；仅用于测试和诊断。"""

        return self._active.get((match_id, sheet_id))

    def _prepare_departure_direction(self, semantic: StoneStateSemanticEvent) -> _ActiveShotDirection:
        """departure 时执行唯一一次 tag 对齐，并在 MATCHED 时注入 DirectionService。"""

        # 每次 departure 都先清空 DirectionService 的旧状态，避免跨 Shot 残留方向被 freeze 进新 Shot。
        self._direction_service.reset(semantic.sheet_id, match_id=semantic.match_id)
        lock = self._pre_shot_direction_service.get_lock(semantic.match_id, semantic.sheet_id)
        moving_tag = semantic.moving_stone_tag_id
        if lock is None:
            active = _ActiveShotDirection(
                alignment_status=ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK,
                candidate_tag_id=None,
                moving_stone_tag_id=moving_tag,
                resolved_direction="UNKNOWN",
                resolved_source_end=None,
                resolved_target_end=None,
            )
        elif self._is_matched(lock, moving_tag):
            self._direction_service.set_locked_direction(
                semantic.sheet_id,
                match_id=semantic.match_id,
                direction=lock.direction,
                source_end=lock.source_end,
                target_end=lock.target_end,
                timestamp=semantic.timestamp,
            )
            active = _ActiveShotDirection(
                alignment_status=ShotDirectionAlignmentStatus.MATCHED,
                candidate_tag_id=lock.candidate_tag_id,
                moving_stone_tag_id=moving_tag,
                resolved_direction=lock.direction,
                resolved_source_end=lock.source_end,
                resolved_target_end=lock.target_end,
            )
        else:
            active = _ActiveShotDirection(
                alignment_status=ShotDirectionAlignmentStatus.CANDIDATE_MISMATCH,
                candidate_tag_id=lock.candidate_tag_id,
                moving_stone_tag_id=moving_tag,
                resolved_direction="UNKNOWN",
                resolved_source_end=None,
                resolved_target_end=None,
            )

        # departure 不释放 pre-shot lock；锁在整个 Shot 期间保持关闭，直到 stop 后 reset。
        self._active[(semantic.match_id, semantic.sheet_id)] = active
        return active

    def _current_alignment(self, semantic: StoneStateSemanticEvent) -> _ActiveShotDirection:
        """非 departure 事件沿用当前 Shot 的协调摘要，不重新解析方向。"""

        return self._active.get((semantic.match_id, semantic.sheet_id)) or _ActiveShotDirection(
            alignment_status=ShotDirectionAlignmentStatus.NOT_APPLICABLE,
            candidate_tag_id=None,
            moving_stone_tag_id=semantic.moving_stone_tag_id,
            resolved_direction="UNKNOWN",
            resolved_source_end=None,
            resolved_target_end=None,
        )

    def _result(self, semantic: StoneStateSemanticEvent, alignment: _ActiveShotDirection, context) -> ShotCoordinationResult:
        """组装测试和 Replay 可观察的协调结果。"""

        return ShotCoordinationResult(
            semantic_event=semantic,
            shot_context=context,
            alignment_status=alignment.alignment_status,
            candidate_tag_id=alignment.candidate_tag_id,
            moving_stone_tag_id=semantic.moving_stone_tag_id,
            resolved_direction=alignment.resolved_direction,
            resolved_source_end=alignment.resolved_source_end,
            resolved_target_end=alignment.resolved_target_end,
        )

    def _is_matched(self, lock: PreShotDirectionLock, moving_stone_tag_id: str) -> bool:
        """严格字符串相等；不做 stoneId、颜色、前缀或大小写猜测。"""

        return lock.candidate_tag_id == moving_stone_tag_id
