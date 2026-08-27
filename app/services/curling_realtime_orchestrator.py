"""Phase 7.6 真实协议实时编排器。

Orchestrator 只把已解析 Raw 消息分发到现有 Phase 7.1~7.5 与 Phase 6 服务；
它不实现镜头选择规则、不推进 Shot 状态机、不做 tag 对齐、不连接真实 WebSocket。
"""

from __future__ import annotations

import logging

from app.adapters.stone.position_adapter import TrajectoryPositionAdapter
from app.core.config import ConfigManager, get_config_manager
from app.core.enums import RuntimeStatus
from app.core.runtime import RuntimeManager, runtime_manager
from app.models.curling_raw import (
    FullDataRawMessage,
    GenericRawMessage,
    MalformedRawMessage,
    MatchStartRawMessage,
    MatchStopRawMessage,
    RawCurlingMessage,
    StoneStateRawMessage,
    TrajectoryRawMessage,
    parse_raw_curling_message,
)
from app.models.realtime_orchestration import RealtimeOrchestrationResult
from app.services.direction_service import DirectionService
from app.services.director_service import DirectorService
from app.services.position_cache import PositionCache, position_cache
from app.services.pre_shot_direction_service import PreShotDirectionService
from app.services.shot_direction_coordination_service import ShotDirectionCoordinationService
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_edge_detector import StoneStateEdgeDetector
from app.services.stone_state_event_bridge import StoneStateEventBridge

logger = logging.getLogger(__name__)


class CurlingRealtimeOrchestrator:
    """统一编排 type=3 Position 支路和 type=4 State 支路。"""

    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
        runtime_registry: RuntimeManager | None = None,
        position_adapter: TrajectoryPositionAdapter | None = None,
        cache: PositionCache | None = None,
        pre_shot_direction_service: PreShotDirectionService | None = None,
        direction_service: DirectionService | None = None,
        stone_event_service: StoneEventService | None = None,
        edge_detector: StoneStateEdgeDetector | None = None,
        bridge: StoneStateEventBridge | None = None,
        coordinator: ShotDirectionCoordinationService | None = None,
        director_service: DirectorService | None = None,
    ) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._runtime_registry = runtime_registry or runtime_manager
        self._cache = cache or position_cache
        self._position_adapter = position_adapter or TrajectoryPositionAdapter(self._config_manager)
        self._pre_shot_direction_service = pre_shot_direction_service or PreShotDirectionService(self._cache, self._config_manager)
        self._direction_service = direction_service or DirectionService(config_manager=self._config_manager)
        self._stone_event_service = stone_event_service or StoneEventService(direction_service=self._direction_service)
        self._edge_detector = edge_detector or StoneStateEdgeDetector()
        self._bridge = bridge or StoneStateEventBridge(self._config_manager, self._runtime_registry, self._stone_event_service)
        self._coordinator = coordinator or ShotDirectionCoordinationService(
            pre_shot_direction_service=self._pre_shot_direction_service,
            direction_service=self._direction_service,
            stone_event_service=self._stone_event_service,
            bridge=self._bridge,
        )
        self._director_service = director_service or DirectorService(self._config_manager)

    @property
    def pre_shot_direction_service(self) -> PreShotDirectionService:
        """暴露共享 PreShotDirectionService，方便测试和诊断确认对象图。"""

        return self._pre_shot_direction_service

    @property
    def direction_service(self) -> DirectionService:
        """暴露共享 DirectionService，避免外部误建第二套状态。"""

        return self._direction_service

    @property
    def stone_event_service(self) -> StoneEventService:
        """暴露共享 StoneEventService，供 E2E 测试检查 active Shot。"""

        return self._stone_event_service

    @property
    def coordinator(self) -> ShotDirectionCoordinationService:
        """暴露共享 Coordinator，供测试检查 reset/active 状态。"""

        return self._coordinator

    def process_raw_text(self, raw_text: str, *, received_at_ms: int | None = None) -> list[RealtimeOrchestrationResult]:
        """从 fake/raw JSON 文本开始处理，验证 Raw Parser 也在链路内。"""

        return self.process(parse_raw_curling_message(raw_text), received_at_ms=received_at_ms)

    def process(self, message: RawCurlingMessage, *, received_at_ms: int | None = None) -> list[RealtimeOrchestrationResult]:
        """处理一条已解析 Raw 消息；一条 type=3 可产生多个 position 结果。"""

        if isinstance(message, TrajectoryRawMessage):
            return self._process_trajectory(message, received_at_ms=received_at_ms)
        if isinstance(message, StoneStateRawMessage):
            return [self._process_stone_state(message, received_at_ms=received_at_ms)]
        if isinstance(message, FullDataRawMessage):
            return [RealtimeOrchestrationResult(raw_type=message.type, ignored_reason="type12_ignored")]
        if isinstance(message, MatchStartRawMessage):
            return [RealtimeOrchestrationResult(raw_type=message.type, ignored_reason="type1_does_not_control_match")]
        if isinstance(message, MatchStopRawMessage):
            return [RealtimeOrchestrationResult(raw_type=message.type, ignored_reason="type2_does_not_control_match")]
        if isinstance(message, GenericRawMessage):
            return [RealtimeOrchestrationResult(raw_type=message.type, ignored_reason="unknown_type_ignored")]
        if isinstance(message, MalformedRawMessage):
            return [RealtimeOrchestrationResult(raw_type=None, ignored_reason=message.error)]
        return [RealtimeOrchestrationResult(raw_type=None, ignored_reason="unsupported_message")]

    def _process_trajectory(self, message: TrajectoryRawMessage, *, received_at_ms: int | None) -> list[RealtimeOrchestrationResult]:
        """type=3：PositionAdapter -> PositionCache -> PreShotDirectionService -> Director。"""

        positions = self._position_adapter.convert(message)
        if not positions:
            return [RealtimeOrchestrationResult(raw_type=message.type, ignored_reason="no_valid_position")]

        results: list[RealtimeOrchestrationResult] = []
        for position in positions:
            self._cache.add(position, received_at_ms=received_at_ms)
            result = RealtimeOrchestrationResult(raw_type=message.type, positions=[position])
            match_id = self._resolve_running_match_id(position.sheet_id)
            if match_id is None:
                result.ignored_reason = "no_single_running_match"
                results.append(result)
                continue
            if self._stone_event_service.get_current_shot(match_id, position.sheet_id) is not None:
                # departure 后 pre-shot 窗口关闭；Position 继续缓存，但不再触发当前 Shot 的预切镜。
                result.ignored_reason = "active_shot_pre_shot_window_closed"
                results.append(result)
                continue
            context = self._pre_shot_direction_service.evaluate(match_id, position.sheet_id, position.tag_id, now_ms=received_at_ms)
            if context is None:
                result.ignored_reason = "direction_not_locked"
                results.append(result)
                continue
            result.pre_shot_contexts.append(context)
            result.director_decisions.append(self._director_service.decide(context))
            results.append(result)
        return results

    def _process_stone_state(self, message: StoneStateRawMessage, *, received_at_ms: int | None) -> RealtimeOrchestrationResult:
        """type=4：EdgeDetector -> Coordinator -> Phase 5 Shot -> Director。"""

        edge = self._edge_detector.detect(message, received_at_ms=received_at_ms)
        if edge is None:
            return RealtimeOrchestrationResult(raw_type=message.type, ignored_reason="no_state_edge")
        result = RealtimeOrchestrationResult(raw_type=message.type, state_edge=edge)
        coordination = self._coordinator.process(edge)
        if coordination is None:
            result.ignored_reason = "coordination_ignored"
            return result
        result.coordination_result = coordination
        result.shot_context = coordination.shot_context
        if coordination.shot_context is not None:
            result.director_decisions.append(self._director_service.decide(coordination.shot_context))
        return result

    def _resolve_running_match_id(self, sheet_id: str) -> str | None:
        """只从 RuntimeManager 查 running match；0 个或多个都不继续方向判断。"""

        matches = [
            match
            for match in self._runtime_registry.list_matches()
            if match.sheet_id == sheet_id and match.status == RuntimeStatus.RUNNING.value
        ]
        if len(matches) != 1:
            if len(matches) > 1:
                logger.error("multiple running matches for sheet_id=%s match_ids=%s", sheet_id, [match.match_id for match in matches])
            return None
        return matches[0].match_id
