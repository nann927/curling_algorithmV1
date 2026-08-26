"""Phase 7.3 type=4 stoneState Edge Detector 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from time import time_ns

from app.models.curling_raw import FullDataRawMessage, StoneStateRawMessage, TrajectoryRawMessage, parse_raw_curling_message
from app.models.curling_state_edge import StoneStateEdge, StoneStateEdgeType
from app.services.stone_state_edge_detector import StoneStateEdgeDetector


def _state(
    stone_state: str | None,
    *,
    lane_id: str | None = "curlingLane1Data",
    tag_id: str | None = "stone0",
    hog_line_1_timing=379,
    hog_line_2_timing=0,
    total_timing=379,
) -> StoneStateRawMessage:
    """构造真实协议形态的 fake type=4 Raw Message。"""

    payload = {
        "type": 4,
        "laneId": lane_id,
        "movingStoneTagId": tag_id,
        "stoneState": stone_state,
        "hogLine1Timing": hog_line_1_timing,
        "hogLine2Timing": hog_line_2_timing,
        "totalTiming": total_timing,
    }
    message = parse_raw_curling_message(json.dumps(payload))
    assert isinstance(message, StoneStateRawMessage)
    return message


def _edge_values(edges: list[StoneStateEdge | None]) -> list[str]:
    """提取实际产生的 EdgeType，过滤重复 state 返回的 None。"""

    return [edge.edge_type.value for edge in edges if edge is not None]


def test_normal_state_chain_deduplicates_repeated_states() -> None:
    """start/start/.../end/end 只产生四个进入边沿。"""

    detector = StoneStateEdgeDetector()
    states = ["start", "start", "start", "hogline1", "hogline1", "hogline2", "hogline2", "end", "end"]
    edges = [detector.detect(_state(state), received_at_ms=1000 + index) for index, state in enumerate(states)]
    assert _edge_values(edges) == ["start_entered", "hogline1_entered", "hogline2_entered", "end_entered"]
    assert [edge.previous_state for edge in edges if edge is not None] == [None, "start", "hogline1", "hogline2"]


def test_duplicate_timing_updates_do_not_create_edges_and_snapshot_is_raw() -> None:
    """同一 stoneState 下 timing 变化不产生重复 Edge，首次 Edge 保存原始 timing 快照。"""

    detector = StoneStateEdgeDetector()
    first = detector.detect(_state("hogline1", hog_line_1_timing=379, hog_line_2_timing=21, total_timing=400), received_at_ms=123456789)
    second = detector.detect(_state("hogline1", hog_line_1_timing=379, hog_line_2_timing=22, total_timing=401), received_at_ms=123456790)
    third = detector.detect(_state("hogline1", hog_line_1_timing=379, hog_line_2_timing=23, total_timing=402), received_at_ms=123456791)

    assert first is not None
    assert first.edge_type == StoneStateEdgeType.HOGLINE1_ENTERED
    assert second is None
    assert third is None
    assert first.received_at_ms == 123456789
    assert first.hog_line_1_timing == 379
    assert first.hog_line_2_timing == 21
    assert first.total_timing == 400


def test_first_seen_states_are_edges_without_backfilling() -> None:
    """首次观察到 hogline1/hogline2/end 时如实产出当前 Edge，不补造缺失状态。"""

    for state, edge_type in [
        ("hogline1", "hogline1_entered"),
        ("hogline2", "hogline2_entered"),
        ("end", "end_entered"),
    ]:
        detector = StoneStateEdgeDetector()
        edge = detector.detect(_state(state), received_at_ms=2000)
        assert edge is not None
        assert edge.edge_type.value == edge_type
        assert edge.previous_state is None


def test_forward_skip_allows_current_edge_without_faking_missing_states() -> None:
    """start->hogline2 和 start->end 均允许，但不补造中间 Edge。"""

    detector = StoneStateEdgeDetector()
    skip_hogline2 = [detector.detect(_state("start")), detector.detect(_state("hogline2"))]
    assert _edge_values(skip_hogline2) == ["start_entered", "hogline2_entered"]

    detector = StoneStateEdgeDetector()
    skip_end = [detector.detect(_state("start")), detector.detect(_state("end"))]
    assert _edge_values(skip_end) == ["start_entered", "end_entered"]


def test_backward_state_is_ignored_and_does_not_rollback_internal_state() -> None:
    """hogline2 后收到 hogline1 属于 backward，不能回退并再次产生 hogline2。"""

    detector = StoneStateEdgeDetector()
    states = ["start", "hogline1", "hogline2", "hogline1", "hogline2"]
    edges = [detector.detect(_state(state)) for state in states]
    assert _edge_values(edges) == ["start_entered", "hogline1_entered", "hogline2_entered"]
    assert detector.get_state("curlingLane1Data", "stone0") == "hogline2"


def test_end_to_start_starts_next_cycle_but_hogline2_to_start_is_ignored() -> None:
    """只有 end->start 自动视为下一轮；hogline2->start 先按乱序忽略。"""

    detector = StoneStateEdgeDetector()
    states = ["start", "hogline1", "hogline2", "end", "start"]
    edges = [detector.detect(_state(state)) for state in states]
    assert _edge_values(edges) == ["start_entered", "hogline1_entered", "hogline2_entered", "end_entered", "start_entered"]
    assert edges[-1] is not None
    assert edges[-1].previous_state == "end"

    detector = StoneStateEdgeDetector()
    assert detector.detect(_state("hogline2")) is not None
    assert detector.detect(_state("start")) is None
    assert detector.get_state("curlingLane1Data", "stone0") == "hogline2"


def test_reset_clear_lane_and_clear_release_state() -> None:
    """reset/clear_lane/clear 能显式释放状态跟踪。"""

    detector = StoneStateEdgeDetector()
    detector.detect(_state("hogline2"))
    detector.reset("curlingLane1Data", "stone0")
    reset_edge = detector.detect(_state("start"))
    assert reset_edge is not None
    assert reset_edge.edge_type == StoneStateEdgeType.START_ENTERED
    assert reset_edge.previous_state is None

    detector.detect(_state("start", lane_id="curlingLane1Data", tag_id="stone1"))
    detector.detect(_state("start", lane_id="curlingLane2Data", tag_id="stone0"))
    detector.clear_lane("curlingLane1Data")
    assert detector.get_state("curlingLane1Data", "stone0") is None
    assert detector.get_state("curlingLane1Data", "stone1") is None
    assert detector.get_state("curlingLane2Data", "stone0") == "start"

    detector.clear()
    assert detector.get_state("curlingLane2Data", "stone0") is None
    assert detector.detect(_state("start", lane_id="curlingLane2Data", tag_id="stone0")) is not None


def test_lane_and_tag_are_isolated() -> None:
    """同 lane 不同 tag、不同 lane 同 tag 都应分别产生 Edge。"""

    detector = StoneStateEdgeDetector()
    edge_a = detector.detect(_state("start", lane_id="curlingLane1Data", tag_id="stone0"))
    edge_b = detector.detect(_state("start", lane_id="curlingLane1Data", tag_id="stone1"))
    edge_c = detector.detect(_state("start", lane_id="curlingLane2Data", tag_id="stone0"))
    assert edge_a is not None
    assert edge_b is not None
    assert edge_c is not None
    assert edge_a.lane_id == "curlingLane1Data" and edge_a.moving_stone_tag_id == "stone0"
    assert edge_b.lane_id == "curlingLane1Data" and edge_b.moving_stone_tag_id == "stone1"
    assert edge_c.lane_id == "curlingLane2Data" and edge_c.moving_stone_tag_id == "stone0"


def test_missing_lane_missing_tag_and_unknown_state_are_ignored_without_state_key() -> None:
    """缺 lane/tag 或未知 state 均不建立模糊 key，也不修改已有合法状态。"""

    detector = StoneStateEdgeDetector()
    assert detector.detect(_state("start", lane_id=None)) is None
    assert detector.detect(_state("start", tag_id=None)) is None
    assert detector.detect(_state("moving")) is None
    assert detector.get_state("curlingLane1Data", "stone0") is None

    assert detector.detect(_state("start")) is not None
    assert detector.detect(_state("moving")) is None
    assert detector.get_state("curlingLane1Data", "stone0") == "start"
    assert detector.detect(_state("hogline1")) is not None


def test_non_type4_messages_return_none() -> None:
    """Detector 接收 RawCurlingMessage 时，type=3/type=12 安全返回 None。"""

    detector = StoneStateEdgeDetector()
    type3 = parse_raw_curling_message('{"type":3,"laneId":"curlingLane1Data","trajectoryData":[]}')
    type12 = parse_raw_curling_message('{"type":12,"stone0":[]}')
    assert isinstance(type3, TrajectoryRawMessage)
    assert isinstance(type12, FullDataRawMessage)
    assert detector.detect(type3) is None
    assert detector.detect(type12) is None


def test_default_received_at_ms_uses_wall_clock_epoch_ms() -> None:
    """未显式传 received_at_ms 时使用 wall-clock epoch ms，不使用 timing 字段。"""

    detector = StoneStateEdgeDetector()
    before = time_ns() // 1_000_000
    edge = detector.detect(_state("start", total_timing=5))
    after = time_ns() // 1_000_000
    assert edge is not None
    assert before <= edge.received_at_ms <= after
    assert edge.received_at_ms != edge.total_timing


def test_state_and_lane_values_are_canonicalized_safely() -> None:
    """stoneState 支持 strip/lower 归一化，Edge 保存 canonical state。"""

    detector = StoneStateEdgeDetector()
    edge = detector.detect(_state(" HOGline1 ", lane_id=" curlingLane1Data ", tag_id=" stone0 "))
    assert edge is not None
    assert edge.current_state == "hogline1"
    assert edge.lane_id == "curlingLane1Data"
    assert edge.moving_stone_tag_id == "stone0"


def test_phase73_boundaries_do_not_generate_business_events() -> None:
    """Edge Detector 不依赖后续业务层，也不产生 Phase 5/6/7.2 事件模型。"""

    source = Path("app/services/stone_state_edge_detector.py").read_text(encoding="utf-8")
    model_source = Path("app/models/curling_state_edge.py").read_text(encoding="utf-8")
    combined = source + model_source
    assert "ThrowStateMachine" not in combined
    assert "StoneEventService" not in combined
    assert "DirectorService" not in combined
    assert "PreShotDirectionService" not in combined
    assert "PositionCache" not in combined
    assert "TriggerEvent" not in combined
    assert "ShotEventContext" not in combined
    assert "PreShotDirectorContext" not in combined
    assert "DirectorDecision" not in combined
    assert "departure" not in combined
    assert "magnetic_1" not in combined
    assert "magnetic_2" not in combined
    assert "touch" not in combined
    assert "alarm" not in combined
