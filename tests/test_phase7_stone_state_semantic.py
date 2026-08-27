"""Phase 7.4 StoneState Edge Semantic Bridge 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import ConfigManager, Settings
from app.core.enums import RuntimeStatus, ShotQualityStatus, ThrowStatus
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.curling_raw import StoneStateRawMessage, parse_raw_curling_message
from app.models.curling_state_edge import StoneStateEdge, StoneStateEdgeType
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_edge_detector import StoneStateEdgeDetector
from app.services.stone_state_event_bridge import EDGE_TO_BUSINESS_EVENT, StoneStateEventBridge
from app.storage.shot_repository import ShotRepository


def _site_config() -> dict:
    """构造 TEST ONLY 配置，明确区分 State/Trigger lane 与 Position lane。"""

    return {
        "site_id": "phase74_test",
        "sheets": [
            {"sheet_id": "sheet_01", "enabled": True, "trigger_lane_id": "state_lane_01", "position_lane_id": "position_lane_01"},
            {"sheet_id": "sheet_02", "enabled": True, "trigger_lane_id": "state_lane_02", "position_lane_id": "position_lane_02"},
            {"sheet_id": "sheet_05", "enabled": True, "trigger_lane_id": "state_lane_05", "position_lane_id": "position_lane_05"},
            {"sheet_id": "sheet_06", "enabled": True, "trigger_lane_id": "state_lane_06", "position_lane_id": "position_lane_06"},
        ],
        "lane_mappings": [
            {"lane_id": "position_only_lane", "sheet_id": "sheet_02"},
            {"lane_id": "position_lane_01", "sheet_id": "sheet_01"},
            {"lane_id": "position_lane_05", "sheet_id": "sheet_05"},
            {"lane_id": "position_lane_06", "sheet_id": "sheet_06"},
        ],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}}],
    }


def _manager() -> ConfigManager:
    """创建隔离 ConfigManager，避免依赖正式 site_config 的未配置 trigger_lane_id。"""

    return ConfigManager(Settings(site_config=_site_config()))


def _edge(
    edge_type: StoneStateEdgeType,
    *,
    lane_id: str = "state_lane_01",
    tag_id: str = "stone0",
    received_at_ms: int = 1_786_000_000_123,
    h1=379,
    h2=21,
    total=400,
) -> StoneStateEdge:
    """构造协议层 Edge，timing 保持 raw snapshot。"""

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
        received_at_ms=received_at_ms,
        hog_line_1_timing=h1,
        hog_line_2_timing=h2,
        total_timing=total,
    )


def _register_match(match_id: str = "match_001", sheet_id: str = "sheet_01", *, status: str = RuntimeStatus.RUNNING.value) -> MatchRuntime:
    """注册测试用 running match，模拟软件 V2 /match/control start 后的 Runtime。"""

    sheet = SheetRuntime(sheet_id=sheet_id, enabled=True, stream_type="smart_director", media_url="mock://live")
    match = MatchRuntime(match_id=match_id, sheet_id=sheet_id, scene_type="competition", start_time="2026-08-26T10:00:00+08:00", status=status, sheets={sheet_id: sheet})
    runtime_manager.create_match(match)
    return match


def _bridge(service: StoneEventService | None = None) -> StoneStateEventBridge:
    """创建测试 Bridge。"""

    return StoneStateEventBridge(_manager(), runtime_manager, service or StoneEventService())


def _raw_state(state: str, *, lane_id: str = "state_lane_01", tag_id: str = "stone0", h1=379, h2=0, total=379) -> StoneStateRawMessage:
    """构造真实协议形态 fake type=4 Raw Message。"""

    message = parse_raw_curling_message(json.dumps({
        "type": 4,
        "laneId": lane_id,
        "movingStoneTagId": tag_id,
        "stoneState": state,
        "hogLine1Timing": h1,
        "hogLine2Timing": h2,
        "totalTiming": total,
    }))
    assert isinstance(message, StoneStateRawMessage)
    return message


def test_edge_to_business_event_mapping_is_one_to_one_without_touch_or_alarm() -> None:
    """Edge -> Event 映射集中且一对一，不产生 touch/alarm。"""

    assert EDGE_TO_BUSINESS_EVENT == {
        StoneStateEdgeType.START_ENTERED: "departure",
        StoneStateEdgeType.HOGLINE1_ENTERED: "magnetic_1",
        StoneStateEdgeType.HOGLINE2_ENTERED: "magnetic_2",
        StoneStateEdgeType.END_ENTERED: "stop",
    }
    assert "touch" not in EDGE_TO_BUSINESS_EVENT.values()
    assert "alarm" not in EDGE_TO_BUSINESS_EVENT.values()


def test_semantic_event_resolves_trigger_lane_running_match_and_keeps_tag_timing_timestamp() -> None:
    """Semantic Event 使用 trigger lane 和 running match，并保留 tag/timing/received timestamp。"""

    _register_match("match_001", "sheet_01")
    event = _bridge().convert(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id="stone5", received_at_ms=1_786_000_000_123, h1=379, h2=21, total=400))
    assert event is not None
    assert event.match_id == "match_001"
    assert event.sheet_id == "sheet_01"
    assert event.lane_id == "state_lane_01"
    assert event.moving_stone_tag_id == "stone5"
    assert event.edge_type == StoneStateEdgeType.HOGLINE1_ENTERED
    assert event.event_type == "magnetic_1"
    assert event.timestamp == 1_786_000_000_123
    assert event.received_at_ms == 1_786_000_000_123
    assert event.hog_line_1_timing == 379
    assert event.hog_line_2_timing == 21
    assert event.total_timing == 400


def test_position_lane_helper_is_not_used_for_type4_lane() -> None:
    """type=4 lane 只走 trigger lane；仅在 position lane mapping 中存在时也不 dispatch。"""

    _register_match("match_002", "sheet_02")
    assert _manager().get_sheet_id_by_position_lane("position_only_lane") == "sheet_02"
    assert _bridge().convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="position_only_lane")) is None


def test_unknown_lane_no_running_match_and_stopped_match_are_ignored() -> None:
    """unknown lane、无 running match、已 completed match 都不创建 Shot。"""

    assert _bridge().convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="unknown_state_lane")) is None
    assert _bridge().convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_01")) is None

    _register_match("match_stopped", "sheet_01", status=RuntimeStatus.COMPLETED.value)
    assert _bridge().convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_01")) is None
    assert ShotRepository().list_by_match("match_stopped") == []


def test_multiple_running_matches_are_not_selected() -> None:
    """异常存在多个 running match 时 Bridge 不随便选第一个。"""

    _register_match("match_a", "sheet_01")
    duplicate = MatchRuntime(match_id="match_b", sheet_id="sheet_01", scene_type="competition", start_time="2026-08-26T10:01:00+08:00", sheets={"sheet_01": SheetRuntime("sheet_01", True, "smart_director", "mock://live")})
    runtime_manager._matches[duplicate.match_id] = duplicate  # 测试防御分支：绕过 create_match 的正式保护。
    assert _bridge().convert(_edge(StoneStateEdgeType.START_ENTERED)) is None


def test_normal_chain_dispatches_to_phase5_without_touch_and_persists_finished_shot() -> None:
    """start/hogline1/hogline2/end 映射到 Phase 5，形成无 touch 的 finished Shot。"""

    _register_match("match_normal", "sheet_01")
    service = StoneEventService()
    bridge = _bridge(service)
    contexts = [
        bridge.process(_edge(StoneStateEdgeType.START_ENTERED, received_at_ms=1000)),
        bridge.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, received_at_ms=1100)),
        bridge.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, received_at_ms=1200)),
        bridge.process(_edge(StoneStateEdgeType.END_ENTERED, received_at_ms=1300)),
    ]
    assert [context.event_type for context in contexts if context is not None] == ["departure", "magnetic_1", "magnetic_2", "stop"]
    assert contexts[0].shot_status == ThrowStatus.RELEASED.value  # type: ignore[union-attr]
    assert contexts[1].shot_status == ThrowStatus.PASSED_MAGNETIC_1.value  # type: ignore[union-attr]
    assert contexts[2].shot_status == ThrowStatus.PASSED_MAGNETIC_2.value  # type: ignore[union-attr]
    assert contexts[3].shot_status == ThrowStatus.FINISHED.value  # type: ignore[union-attr]

    match = runtime_manager.get_match("match_normal")
    sheet = match.sheets["sheet_01"]
    assert sheet.current_shot is None
    assert sheet.current_shot_id is None
    assert sheet.shot_history == ["match_normal_sheet_01_shot_0001"]

    shot = ShotRepository().get("match_normal_sheet_01_shot_0001")
    assert shot is not None
    assert shot.touch_time is None
    assert shot.departure_time == 1000
    assert shot.first_magnetic_time == 1100
    assert shot.second_magnetic_time == 1200
    assert shot.stop_time == 1300
    assert shot.alarm_time is None
    assert shot.direction == "UNKNOWN"
    assert shot.status == ThrowStatus.FINISHED.value
    assert shot.quality_status == ShotQualityStatus.COMPLETE.value
    assert shot.abnormal_reason is None


def test_forward_skip_does_not_backfill_missing_event_and_uses_phase5_degraded_behavior() -> None:
    """start->hogline2->end 只派发 departure/magnetic_2/stop，不补 magnetic_1。"""

    _register_match("match_skip", "sheet_01")
    bridge = _bridge(StoneEventService())
    contexts = [
        bridge.process(_edge(StoneStateEdgeType.START_ENTERED, received_at_ms=2000)),
        bridge.process(_edge(StoneStateEdgeType.HOGLINE2_ENTERED, received_at_ms=2200)),
        bridge.process(_edge(StoneStateEdgeType.END_ENTERED, received_at_ms=2300)),
    ]
    assert [context.event_type for context in contexts if context is not None] == ["departure", "magnetic_2", "stop"]
    shot = ShotRepository().get("match_skip_sheet_01_shot_0001")
    assert shot is not None
    assert shot.first_magnetic_time is None
    assert shot.second_magnetic_time == 2200
    assert shot.status == ThrowStatus.FINISHED.value
    assert shot.quality_status == ShotQualityStatus.ABNORMAL.value
    assert shot.abnormal_reason == "magnetic_2_before_magnetic_1"


def test_first_hogline_or_end_without_active_shot_is_safely_ignored_by_phase5() -> None:
    """只有 hogline/end 时 Bridge 如实派发，Phase 5 按无 active Shot 安全忽略。"""

    _register_match("match_no_active", "sheet_01")
    bridge = _bridge(StoneEventService())
    assert bridge.process(_edge(StoneStateEdgeType.HOGLINE1_ENTERED, received_at_ms=3000)) is None
    assert bridge.process(_edge(StoneStateEdgeType.END_ENTERED, received_at_ms=3100)) is None
    assert runtime_manager.get_match("match_no_active").sheets["sheet_01"].current_shot is None
    assert ShotRepository().list_by_match("match_no_active") == []


def test_match_isolation_and_sheet05_sheet06_trigger_mapping_are_config_driven() -> None:
    """不同 sheet/match 隔离，sheet_05/sheet_06 通过 trigger_lane_id 配置驱动。"""

    _register_match("match_01", "sheet_01")
    _register_match("match_02", "sheet_02")
    _register_match("match_05", "sheet_05")
    _register_match("match_06", "sheet_06")
    bridge = _bridge(StoneEventService())
    event_01 = bridge.convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_01"))
    event_02 = bridge.convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_02"))
    event_05 = bridge.convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_05"))
    event_06 = bridge.convert(_edge(StoneStateEdgeType.START_ENTERED, lane_id="state_lane_06"))
    assert event_01.match_id == "match_01" and event_01.sheet_id == "sheet_01"  # type: ignore[union-attr]
    assert event_02.match_id == "match_02" and event_02.sheet_id == "sheet_02"  # type: ignore[union-attr]
    assert event_05.match_id == "match_05" and event_05.sheet_id == "sheet_05"  # type: ignore[union-attr]
    assert event_06.match_id == "match_06" and event_06.sheet_id == "sheet_06"  # type: ignore[union-attr]


def test_raw_type4_to_edge_to_semantic_to_phase5_e2e_consumes_each_edge_once() -> None:
    """真实协议形态 Raw type=4 经 Parser/EdgeDetector/Bridge/Phase5 形成 Shot。"""

    _register_match("match_e2e", "sheet_01")
    detector = StoneStateEdgeDetector()
    bridge = _bridge(StoneEventService())
    raw_states = ["start", "start", "hogline1", "hogline1", "hogline2", "end", "end"]
    dispatched = []
    for index, state in enumerate(raw_states):
        message = _raw_state(state, h1=379, h2=index, total=400 + index)
        edge = detector.detect(message, received_at_ms=4000 + index)
        if edge is None:
            dispatched.append("NO_EDGE")
            continue
        context = bridge.process(edge)
        dispatched.append(None if context is None else context.event_type)

    assert dispatched == ["departure", "NO_EDGE", "magnetic_1", "NO_EDGE", "magnetic_2", "stop", "NO_EDGE"]
    shot = ShotRepository().get("match_e2e_sheet_01_shot_0001")
    assert shot is not None
    assert shot.touch_time is None
    assert shot.departure_time == 4000
    assert shot.first_magnetic_time == 4002
    assert shot.second_magnetic_time == 4004
    assert shot.stop_time == 4005


def test_phase74_boundaries_do_not_enter_phase75_or_director() -> None:
    """Bridge 不读取 7.2 candidate，不继承方向，不调用 Director，也不启动 WebSocket。"""

    source = Path("app/services/stone_state_event_bridge.py").read_text(encoding="utf-8")
    model_source = Path("app/models/stone_state_semantic.py").read_text(encoding="utf-8")
    combined = source + model_source
    assert "PreShotDirectionService" not in combined
    assert "candidate_tag_id" not in combined
    assert "DirectorService" not in combined
    assert "DirectorDecision" not in combined
    assert "CurlingWebSocketTransport" not in combined
    assert "get_sheet_id_by_position_lane" not in source
    assert "match_records" not in source
    assert "touch" not in EDGE_TO_BUSINESS_EVENT.values()
    assert "alarm" not in EDGE_TO_BUSINESS_EVENT.values()
