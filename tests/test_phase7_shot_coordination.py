"""Phase 7.5 Shot 方向协调测试。

本文件只使用 TEST ONLY fake calibration，验证 Position 预锁方向与 State movingStoneTagId
在 departure 时严格对齐，不代表现场真实标定参数。
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import ConfigManager, Settings
from app.core.enums import RuntimeStatus, ShotQualityStatus, ThrowStatus
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.curling_state_edge import StoneStateEdge, StoneStateEdgeType
from app.models.shot_coordination import ShotDirectionAlignmentStatus
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService
from app.services.position_cache import PositionCache
from app.services.pre_shot_direction_service import PreShotDirectionService
from app.services.shot_direction_coordination_service import ShotDirectionCoordinationService
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_event_bridge import StoneStateEventBridge
from app.storage.shot_repository import ShotRepository


A_POINT = (2.0, 2.0)
B_POINT = (8.0, 8.0)
NOW_MS = 10_000


def _site_config() -> dict:
    """构造同时具备 position lane、trigger lane 和 Ready Zone 的测试配置。"""

    return {
        "site_id": "phase75_test",
        "sheets": [
            {"sheet_id": "sheet_01", "enabled": True, "trigger_lane_id": "state_lane_01", "position_lane_id": "position_lane_01"},
            {"sheet_id": "sheet_02", "enabled": True, "trigger_lane_id": "state_lane_02", "position_lane_id": "position_lane_02"},
        ],
        "lane_mappings": [
            {"lane_id": "position_lane_01", "sheet_id": "sheet_01"},
            {"lane_id": "position_lane_02", "sheet_id": "sheet_02"},
        ],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}}],
        "calibration": {
            "position": [
                {
                    "sheet_id": "sheet_01",
                    "enabled": True,
                    "position_lane_id": "position_lane_01",
                    "lane_bounds": {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
                    "ready_zones": {
                        "A": {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0, "y_max": 3.0},
                        "B": {"x_min": 7.0, "x_max": 10.0, "y_min": 7.0, "y_max": 10.0},
                    },
                    "hoglines": {"A": {"y": 3.5}, "B": {"y": 6.5}},
                },
                {
                    "sheet_id": "sheet_02",
                    "enabled": True,
                    "position_lane_id": "position_lane_02",
                    "lane_bounds": {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
                    "ready_zones": {
                        "A": {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0, "y_max": 3.0},
                        "B": {"x_min": 7.0, "x_max": 10.0, "y_min": 7.0, "y_max": 10.0},
                    },
                    "hoglines": {"A": {"y": 3.5}, "B": {"y": 6.5}},
                },
            ]
        },
    }


def _manager() -> ConfigManager:
    """创建隔离 ConfigManager，避免依赖正式现场配置。"""

    return ConfigManager(Settings(site_config=_site_config()))


def _edge(edge_type: StoneStateEdgeType, *, lane_id: str = "state_lane_01", tag_id: str = "stone0", timestamp: int = 1000) -> StoneStateEdge:
    """构造 Phase 7.3 StoneStateEdge，输入给 Phase 7.5 Coordinator。"""

    state_by_edge = {
        StoneStateEdgeType.START_ENTERED: "start",
        StoneStateEdgeType.HOGLINE1_ENTERED: "hogline1",
        StoneStateEdgeType.HOGLINE2_ENTERED: "hogline2",
        StoneStateEdgeType.END_ENTERED: "end",
    }
    return StoneStateEdge(
        edge_type=edge_type,
        lane_id=lane_id,
        moving_stone_tag_id=tag_id,
        previous_state=None,
        current_state=state_by_edge[edge_type],
        received_at_ms=timestamp,
        hog_line_1_timing=379,
        hog_line_2_timing=21,
        total_timing=400,
    )


def _register_match(match_id: str, sheet_id: str = "sheet_01") -> MatchRuntime:
    """注册 running match，模拟软件 V2 start 后的 Runtime。"""

    sheet = SheetRuntime(sheet_id=sheet_id, enabled=True, stream_type="smart_director", media_url="mock://live")
    match = MatchRuntime(match_id=match_id, sheet_id=sheet_id, scene_type="competition", start_time="2026-08-27T10:00:00+08:00", status=RuntimeStatus.RUNNING.value, sheets={sheet_id: sheet})
    runtime_manager.create_match(match)
    return match


def _components() -> tuple[ShotDirectionCoordinationService, PreShotDirectionService, StoneEventService, PositionCache]:
    """创建共享 DirectionService 的 Coordinator 组件组。"""

    manager = _manager()
    cache = PositionCache(max_size=10)
    pre_shot = PreShotDirectionService(cache, manager, position_freshness_ms=1000, direction_confirm_count=3)
    direction_service = DirectionService(config_manager=manager)
    stone_event_service = StoneEventService(direction_service=direction_service)
    bridge = StoneStateEventBridge(manager, runtime_manager, stone_event_service)
    coordinator = ShotDirectionCoordinationService(
        pre_shot_direction_service=pre_shot,
        direction_service=direction_service,
        stone_event_service=stone_event_service,
        bridge=bridge,
    )
    return coordinator, pre_shot, stone_event_service, cache


def _lock_direction(pre_shot: PreShotDirectionService, cache: PositionCache, match_id: str, sheet_id: str, tag_id: str, end: str) -> None:
    """通过真实 PreShotDirectionService.evaluate 建立预投方向锁。"""

    point = A_POINT if end == "A" else B_POINT
    lane_id = "position_lane_01" if sheet_id == "sheet_01" else "position_lane_02"
    for index in range(3):
        cache.add(
            StonePosition(sheet_id=sheet_id, lane_id=lane_id, tag_id=tag_id, timestamp=5000 + index, x=point[0] + index * 0.1, y=point[1] + index * 0.1),
            received_at_ms=NOW_MS,
        )
    assert pre_shot.evaluate(match_id, sheet_id, tag_id, now_ms=NOW_MS) is not None


def _run_full_chain(coordinator: ShotDirectionCoordinationService, *, lane_id: str = "state_lane_01", tag_id: str = "stone0") -> None:
    """跑完 type=4 start/hogline1/hogline2/end 全链路。"""

    coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, lane_id=lane_id, tag_id=tag_id, timestamp=1000))
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, lane_id=lane_id, tag_id=tag_id, timestamp=1100))
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, lane_id=lane_id, tag_id=tag_id, timestamp=1200))
    coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, lane_id=lane_id, tag_id=tag_id, timestamp=1300))


def test_matched_a_to_b_inherits_direction_and_resets_only_after_stop() -> None:
    """stone0 预锁 A_TO_B 且 moving tag 一致时，departure 后 Shot 立即具备方向。"""

    coordinator, pre_shot, service, cache = _components()
    _register_match("match_a")
    _lock_direction(pre_shot, cache, "match_a", "sheet_01", "stone0", "A")

    start = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone0", timestamp=1000))
    assert start is not None
    assert start.alignment_status == ShotDirectionAlignmentStatus.MATCHED
    assert start.candidate_tag_id == "stone0"
    assert start.moving_stone_tag_id == "stone0"
    assert start.shot_context is not None
    assert start.shot_context.direction == "A_TO_B"
    assert start.shot_context.source_end == "A"
    assert start.shot_context.target_end == "B"
    assert service.get_current_shot("match_a", "sheet_01").direction == "A_TO_B"  # type: ignore[union-attr]
    assert pre_shot.get_lock("match_a", "sheet_01") is not None

    coordinator.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id="stone0", timestamp=1100))
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, tag_id="stone0", timestamp=1200))
    stop = coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, tag_id="stone0", timestamp=1300))
    assert stop is not None
    assert stop.alignment_status == ShotDirectionAlignmentStatus.MATCHED
    assert pre_shot.get_lock("match_a", "sheet_01") is None
    assert coordinator.get_active_alignment("match_a", "sheet_01") is None

    shot = ShotRepository().get("match_a_sheet_01_shot_0001")
    assert shot is not None
    assert shot.direction == "A_TO_B"
    assert shot.source_end == "A"
    assert shot.target_end == "B"
    assert shot.status == ThrowStatus.FINISHED.value
    assert shot.touch_time is None
    assert shot.quality_status == ShotQualityStatus.COMPLETE.value
    assert shot.abnormal_reason is None


def test_matched_b_to_a_inherits_reverse_direction() -> None:
    """stone5 预锁 B_TO_A 且 moving tag 一致时，Shot 继承 B->A。"""

    coordinator, pre_shot, _, cache = _components()
    _register_match("match_b")
    _lock_direction(pre_shot, cache, "match_b", "sheet_01", "stone5", "B")

    result = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone5", timestamp=2000))
    assert result is not None
    assert result.alignment_status == ShotDirectionAlignmentStatus.MATCHED
    assert result.resolved_direction == "B_TO_A"
    assert result.resolved_source_end == "B"
    assert result.resolved_target_end == "A"
    _run_full_chain(coordinator, tag_id="stone5")

    shot = ShotRepository().get("match_b_sheet_01_shot_0001")
    assert shot is not None
    assert shot.direction == "B_TO_A"
    assert shot.source_end == "B"
    assert shot.target_end == "A"
    assert shot.status == ThrowStatus.FINISHED.value


def test_no_pre_shot_lock_keeps_unknown_but_does_not_block_business_flow() -> None:
    """没有预投锁时，业务 state 流继续，Shot 方向保持 UNKNOWN。"""

    coordinator, pre_shot, _, _ = _components()
    _register_match("match_no_lock")
    start = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone0"))
    assert start is not None
    assert start.alignment_status == ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK
    assert start.shot_context is not None
    assert start.shot_context.direction == "UNKNOWN"
    assert pre_shot.get_lock("match_no_lock", "sheet_01") is None

    coordinator.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id="stone0", timestamp=1100))
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, tag_id="stone0", timestamp=1200))
    coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, tag_id="stone0", timestamp=1300))
    shot = ShotRepository().get("match_no_lock_sheet_01_shot_0001")
    assert shot is not None
    assert shot.direction == "UNKNOWN"
    assert shot.status == ThrowStatus.FINISHED.value


def test_candidate_mismatch_keeps_unknown_continues_and_resets_after_stop() -> None:
    """candidate 与 moving tag 不一致时绝不继承错误方向，但完整 Shot 链路继续。"""

    coordinator, pre_shot, service, cache = _components()
    _register_match("match_mismatch")
    _lock_direction(pre_shot, cache, "match_mismatch", "sheet_01", "stone0", "A")

    start = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone5", timestamp=1000))
    assert start is not None
    assert start.alignment_status == ShotDirectionAlignmentStatus.CANDIDATE_MISMATCH
    assert start.candidate_tag_id == "stone0"
    assert start.moving_stone_tag_id == "stone5"
    assert start.resolved_direction == "UNKNOWN"
    assert start.shot_context is not None
    assert start.shot_context.direction == "UNKNOWN"
    assert service.get_current_shot("match_mismatch", "sheet_01").direction == "UNKNOWN"  # type: ignore[union-attr]
    assert pre_shot.get_lock("match_mismatch", "sheet_01") is not None

    coordinator.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id="stone5", timestamp=1100))
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, tag_id="stone5", timestamp=1200))
    coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, tag_id="stone5", timestamp=1300))
    assert pre_shot.get_lock("match_mismatch", "sheet_01") is None
    shot = ShotRepository().get("match_mismatch_sheet_01_shot_0001")
    assert shot is not None
    assert shot.direction == "UNKNOWN"
    assert shot.status == ThrowStatus.FINISHED.value


def test_late_direction_after_departure_does_not_modify_current_shot() -> None:
    """departure 已确定 UNKNOWN 后，晚到的 pre-shot lock 不得回填当前 Shot。"""

    coordinator, pre_shot, service, cache = _components()
    _register_match("match_late")
    coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone0", timestamp=1000))
    assert service.get_current_shot("match_late", "sheet_01").direction == "UNKNOWN"  # type: ignore[union-attr]

    _lock_direction(pre_shot, cache, "match_late", "sheet_01", "stone0", "A")
    assert pre_shot.get_lock("match_late", "sheet_01") is not None
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id="stone0", timestamp=1100))
    assert service.get_current_shot("match_late", "sheet_01").direction == "UNKNOWN"  # type: ignore[union-attr]
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, tag_id="stone0", timestamp=1200))
    coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, tag_id="stone0", timestamp=1300))

    shot = ShotRepository().get("match_late_sheet_01_shot_0001")
    assert shot is not None
    assert shot.direction == "UNKNOWN"
    assert pre_shot.get_lock("match_late", "sheet_01") is None


def test_stop_without_active_shot_still_resets_stale_pre_shot_lock() -> None:
    """end_entered 能解析到 running match 时，即使 Phase 5 无 active Shot 也释放 stale lock。"""

    coordinator, pre_shot, _, cache = _components()
    _register_match("match_stop_only")
    _lock_direction(pre_shot, cache, "match_stop_only", "sheet_01", "stone0", "A")
    result = coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, tag_id="stone0", timestamp=1300))
    assert result is not None
    assert result.shot_context is None
    assert pre_shot.get_lock("match_stop_only", "sheet_01") is None
    assert ShotRepository().list_by_match("match_stop_only") == []


def test_next_throw_can_relock_with_different_tag_and_reverse_direction() -> None:
    """第一投 stop 后 reset，下一投可以重新锁定另一颗冰壶和反向方向。"""

    coordinator, pre_shot, _, cache = _components()
    _register_match("match_next")
    _lock_direction(pre_shot, cache, "match_next", "sheet_01", "stone0", "A")
    _run_full_chain(coordinator, tag_id="stone0")
    assert pre_shot.get_lock("match_next", "sheet_01") is None

    _lock_direction(pre_shot, cache, "match_next", "sheet_01", "stone5", "B")
    second = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone5", timestamp=2000))
    assert second is not None
    assert second.alignment_status == ShotDirectionAlignmentStatus.MATCHED
    assert second.shot_context is not None
    assert second.shot_context.shot_id == "match_next_sheet_01_shot_0002"
    assert second.shot_context.direction == "B_TO_A"



def test_previous_matched_direction_does_not_leak_into_next_no_lock_shot() -> None:
    """第一投 A_TO_B 完整结束后，第二投无预锁必须保持 UNKNOWN。"""

    coordinator, pre_shot, service, cache = _components()
    _register_match("match_seq_no_lock")
    _lock_direction(pre_shot, cache, "match_seq_no_lock", "sheet_01", "stone0", "A")
    _run_full_chain(coordinator, tag_id="stone0")
    first = ShotRepository().get("match_seq_no_lock_sheet_01_shot_0001")
    assert first is not None
    assert first.direction == "A_TO_B"
    assert first.source_end == "A"
    assert first.target_end == "B"
    assert first.status == ThrowStatus.FINISHED.value

    second = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone8", timestamp=2000))
    assert second is not None
    assert second.alignment_status == ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK
    assert second.shot_context is not None
    assert second.shot_context.shot_id == "match_seq_no_lock_sheet_01_shot_0002"
    assert second.shot_context.direction == "UNKNOWN"
    assert second.shot_context.source_end is None
    assert second.shot_context.target_end is None

    current = service.get_current_shot("match_seq_no_lock", "sheet_01")
    assert current is not None
    assert current.direction == "UNKNOWN"
    assert current.source_end is None
    assert current.target_end is None


def test_previous_matched_direction_does_not_leak_into_next_mismatch_shot() -> None:
    """第一投 A_TO_B 完整结束后，第二投 mismatch 不能继承上一投或错误 candidate 方向。"""

    coordinator, pre_shot, service, cache = _components()
    _register_match("match_seq_mismatch")
    _lock_direction(pre_shot, cache, "match_seq_mismatch", "sheet_01", "stone0", "A")
    _run_full_chain(coordinator, tag_id="stone0")
    first = ShotRepository().get("match_seq_mismatch_sheet_01_shot_0001")
    assert first is not None
    assert first.direction == "A_TO_B"

    _lock_direction(pre_shot, cache, "match_seq_mismatch", "sheet_01", "stone5", "B")
    second = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone9", timestamp=2000))
    assert second is not None
    assert second.alignment_status == ShotDirectionAlignmentStatus.CANDIDATE_MISMATCH
    assert second.candidate_tag_id == "stone5"
    assert second.moving_stone_tag_id == "stone9"
    assert second.resolved_direction == "UNKNOWN"
    assert second.resolved_source_end is None
    assert second.resolved_target_end is None
    assert second.shot_context is not None
    assert second.shot_context.shot_id == "match_seq_mismatch_sheet_01_shot_0002"
    assert second.shot_context.direction == "UNKNOWN"
    assert second.shot_context.source_end is None
    assert second.shot_context.target_end is None

    current = service.get_current_shot("match_seq_mismatch", "sheet_01")
    assert current is not None
    assert current.direction == "UNKNOWN"
    assert current.source_end is None
    assert current.target_end is None

def test_sheet_isolation_prevents_cross_sheet_candidate_reuse() -> None:
    """sheet_01 的 candidate=stone0 不能被 sheet_02 的 moving stone0 使用。"""

    coordinator, pre_shot, _, cache = _components()
    _register_match("match_01", "sheet_01")
    _register_match("match_02", "sheet_02")
    _lock_direction(pre_shot, cache, "match_01", "sheet_01", "stone0", "A")

    result = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_02", tag_id="stone0", timestamp=1000))
    assert result is not None
    assert result.semantic_event.match_id == "match_02"
    assert result.alignment_status == ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK
    assert result.shot_context is not None
    assert result.shot_context.direction == "UNKNOWN"


def test_match_isolation_prevents_old_match_lock_reuse() -> None:
    """旧 match 的 lock 不能被同 sheet 新 running match 继承。"""

    coordinator, pre_shot, _, cache = _components()
    _lock_direction(pre_shot, cache, "old_match", "sheet_01", "stone0", "A")
    _register_match("new_match", "sheet_01")

    result = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone0", timestamp=1000))
    assert result is not None
    assert result.semantic_event.match_id == "new_match"
    assert result.alignment_status == ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK
    assert result.shot_context is not None
    assert result.shot_context.direction == "UNKNOWN"
    assert pre_shot.get_lock("old_match", "sheet_01") is not None


def test_tag_compare_is_strict_string_equality() -> None:
    """tag 比较严格区分大小写，不做 stone0/Stone0 等猜测。"""

    coordinator, pre_shot, _, cache = _components()
    _register_match("match_strict")
    _lock_direction(pre_shot, cache, "match_strict", "sheet_01", "stone0", "A")
    result = coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="Stone0", timestamp=1000))
    assert result is not None
    assert result.alignment_status == ShotDirectionAlignmentStatus.CANDIDATE_MISMATCH
    assert result.shot_context is not None
    assert result.shot_context.direction == "UNKNOWN"


def test_non_departure_events_do_not_change_frozen_direction() -> None:
    """方向只在 departure 决定一次，后续 magnetic/stop 不重新解析。"""

    coordinator, pre_shot, service, cache = _components()
    _register_match("match_freeze")
    _lock_direction(pre_shot, cache, "match_freeze", "sheet_01", "stone0", "A")
    coordinator.process(_edge(StoneStateEdgeType.START_ENTERED, tag_id="stone0", timestamp=1000))
    pre_shot.reset("match_freeze", "sheet_01")
    _lock_direction(pre_shot, cache, "match_freeze", "sheet_01", "stone5", "B")

    coordinator.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id="stone0", timestamp=1100))
    assert service.get_current_shot("match_freeze", "sheet_01").direction == "A_TO_B"  # type: ignore[union-attr]
    coordinator.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, tag_id="stone0", timestamp=1200))
    coordinator.process(_edge(StoneStateEdgeType.END_ENTERED, tag_id="stone0", timestamp=1300))
    shot = ShotRepository().get("match_freeze_sheet_01_shot_0001")
    assert shot is not None
    assert shot.direction == "A_TO_B"


def test_phase75_boundaries_do_not_cross_into_future_or_frozen_services() -> None:
    """Coordinator 不读取 PositionCache、不查 registry、不调用 Director、不处理视频/Clip/API。"""

    source = Path("app/services/shot_direction_coordination_service.py").read_text(encoding="utf-8")
    assert "from app.services.position_cache" not in source
    assert "PositionCache(" not in source
    assert "stone_registry" not in source
    assert "color" not in source.lower()
    assert "DirectorService" not in source
    assert "DirectorDecision" not in source
    assert "Clip" not in source
    assert "camera" not in source.lower()
    assert "media timestamp" not in source.lower()
    assert "CurlingWebSocketTransport" not in source
    assert "get_sheet_id_by_position_lane" not in source
    assert "StoneStateEdgeDetector" not in source
    assert "touch" not in source.split("EDGE_TO_BUSINESS_EVENT")[-1]
    assert "alarm" not in source.split("EDGE_TO_BUSINESS_EVENT")[-1]
