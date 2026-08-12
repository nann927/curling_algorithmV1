"""Phase 4 电子冰壶 Trigger/Position/Direction 测试。"""

import pytest
from pydantic import ValidationError

from app.adapters.stone.replay import JsonlReplaySource
from app.core.config import ConfigManager, Settings, SiteConfig
from app.core.enums import DirectionStatus
from app.models.event import TriggerEvent
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService
from app.services.stone_event_service import StoneEventService


ZONES = {
    "sheet_01": {
        "A": {"x_min": 0, "x_max": 2, "y_min": 0, "y_max": 2},
        "B": {"x_min": 8, "x_max": 10, "y_min": 8, "y_max": 10},
    },
    "sheet_02": {
        "A": {"x_min": 20, "x_max": 22, "y_min": 0, "y_max": 2},
        "B": {"x_min": 28, "x_max": 30, "y_min": 8, "y_max": 10},
    },
}


def _pos(sheet_id: str, x: float, y: float, timestamp: int = 1000) -> StonePosition:
    """构造标准定位数据。"""

    return StonePosition(sheet_id=sheet_id, lane_id=f"position_{sheet_id}", tag_id="tag_001", timestamp=timestamp, x=x, y=y)


def _trigger(event_type: str, timestamp: int = 1000, sheet_id: str = "sheet_01") -> TriggerEvent:
    """构造标准触发事件。"""

    return TriggerEvent(sheet_id=sheet_id, lane_id=f"trigger_{sheet_id}", timestamp=timestamp, event_type=event_type)


def _direction_service(confirm_count: int = 3) -> DirectionService:
    """构造测试用方向服务，使用明确的 Mock 发球区。"""

    return DirectionService(confirm_count=confirm_count, max_position_age_ms=1000, direction_zones_by_sheet=ZONES)


def _site_config(**overrides) -> dict:
    """构造测试用 site_config。"""

    data = {
        "site_id": "phase4_test",
        "sheets": [
            {
                "sheet_id": "sheet_01",
                "enabled": True,
                "position_lane_id": "position_lane_01",
                "trigger_lane_id": "trigger_lane_01",
                "direction_zones": ZONES["sheet_01"],
            },
            {
                "sheet_id": "sheet_02",
                "enabled": True,
                "position_lane_id": "position_lane_02",
                "trigger_lane_id": "trigger_lane_02",
                "direction_zones": ZONES["sheet_02"],
            },
        ],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {"path": "data/test/overview_A.mp4"}}],
        "stone_registry": [{"stone_id": "stone_001", "tag_id": "tag_001"}, {"stone_id": "stone_002", "tag_id": None}],
    }
    data.update(overrides)
    return data


def test_trigger_event_and_stone_position_validation() -> None:
    """TriggerEvent 和 StonePosition 应校验必填字段及 event_type。"""

    event = _trigger("touch")
    position = _pos("sheet_01", 1, 1)
    assert event.event_type == "touch"
    assert position.x == 1
    with pytest.raises(ValidationError):
        TriggerEvent(sheet_id="sheet_01", lane_id="trigger_lane_01", timestamp=1, event_type="bad")


def test_position_and_trigger_lane_mapping() -> None:
    """定位 lane 与触发 lane 必须分别映射到 sheet_id。"""

    manager = ConfigManager(Settings(site_config=_site_config()))
    assert manager.get_sheet_id_by_position_lane("position_lane_01") == "sheet_01"
    assert manager.get_sheet_id_by_trigger_lane("trigger_lane_02") == "sheet_02"


@pytest.mark.parametrize(
    "sheets,error_text",
    [
        (
            [
                {"sheet_id": "sheet_01", "position_lane_id": "p1", "trigger_lane_id": "t1"},
                {"sheet_id": "sheet_02", "position_lane_id": "p1", "trigger_lane_id": "t2"},
            ],
            "position_lane_id must be unique",
        ),
        (
            [
                {"sheet_id": "sheet_01", "position_lane_id": "p1", "trigger_lane_id": "t1"},
                {"sheet_id": "sheet_02", "position_lane_id": "p2", "trigger_lane_id": "t1"},
            ],
            "trigger_lane_id must be unique",
        ),
    ],
)
def test_duplicate_lane_config_fails(sheets: list[dict], error_text: str) -> None:
    """重复 position_lane_id 或 trigger_lane_id 必须启动失败。"""

    data = _site_config(sheets=sheets)
    with pytest.raises(ValidationError, match=error_text):
        SiteConfig.model_validate(data)


@pytest.mark.parametrize(
    "stone_registry,error_text",
    [
        ([{"stone_id": "stone_001"}, {"stone_id": "stone_001"}], "stone_id must be unique"),
        ([{"stone_id": "stone_001", "tag_id": "tag_001"}, {"stone_id": "stone_002", "tag_id": "tag_001"}], "tag_id must be unique"),
    ],
)
def test_duplicate_stone_registry_fails(stone_registry: list[dict], error_text: str) -> None:
    """stone_id 和非空 tag_id 不允许重复。"""

    with pytest.raises(ValidationError, match=error_text):
        SiteConfig.model_validate(_site_config(stone_registry=stone_registry))


def test_touch_starts_detecting_and_a_positions_lock_a_to_b() -> None:
    """touch 后 A 区连续定位应锁定 A_TO_B。"""

    service = StoneEventService(_direction_service())
    state = service.process_trigger_event(_trigger("touch"))
    assert state.status == DirectionStatus.DETECTING.value
    for index in range(3):
        state = service.process_position(_pos("sheet_01", 1, 1, 1100 + index))
    assert state.status == DirectionStatus.LOCKED.value
    assert state.direction == "A_TO_B"


def test_b_positions_lock_b_to_a() -> None:
    """B 区连续定位应锁定 B_TO_A。"""

    direction = _direction_service()
    direction.start_monitoring("sheet_01")
    for index in range(3):
        state = direction.update_position(_pos("sheet_01", 9, 9, 1100 + index))
    assert state.status == DirectionStatus.LOCKED.value
    assert state.source_end == "B"
    assert state.direction == "B_TO_A"


def test_unknown_jitter_does_not_destroy_candidate_direction() -> None:
    """A/A/UNKNOWN/A 这种轻微抖动仍应锁定 A_TO_B。"""

    direction = _direction_service()
    direction.start_monitoring("sheet_01")
    direction.update_position(_pos("sheet_01", 1, 1, 1100))
    direction.update_position(_pos("sheet_01", 1, 1, 1200))
    direction.update_position(_pos("sheet_01", 5, 5, 1300))
    state = direction.update_position(_pos("sheet_01", 1, 1, 1400))
    assert state.status == DirectionStatus.LOCKED.value
    assert state.direction == "A_TO_B"


def test_departure_freezes_direction_and_later_position_cannot_change_it() -> None:
    """departure 后方向进入 FROZEN，后续定位不能改写本次方向。"""

    service = StoneEventService(_direction_service())
    service.process_trigger_event(_trigger("touch", 1000))
    for timestamp in (1100, 1200, 1300):
        service.process_position(_pos("sheet_01", 1, 1, timestamp))
    state = service.process_trigger_event(_trigger("departure", 1400))
    assert state.status == DirectionStatus.FROZEN.value
    assert state.direction == "A_TO_B"
    state = service.process_position(_pos("sheet_01", 9, 9, 1500))
    assert state.status == DirectionStatus.FROZEN.value
    assert state.direction == "A_TO_B"


def test_departure_fallback_uses_last_position_or_unknown() -> None:
    """departure 未锁定时，可用 last_position 降级判断；无可靠定位则 UNKNOWN。"""

    direction = _direction_service()
    direction.start_monitoring("sheet_01")
    direction.update_position(_pos("sheet_01", 1, 1, 1100))
    state = direction.freeze_direction("sheet_01", 1200)
    assert state.status == DirectionStatus.FROZEN.value
    assert state.direction == "A_TO_B"

    direction.start_monitoring("sheet_01")
    direction.update_position(_pos("sheet_01", 5, 5, 2100))
    state = direction.freeze_direction("sheet_01", 2200)
    assert state.status == DirectionStatus.FROZEN.value
    assert state.direction == "UNKNOWN"


def test_stop_then_next_touch_starts_fresh_detection() -> None:
    """stop 后下一次 touch 会开启新的检测窗口，避免上一投污染下一投。"""

    service = StoneEventService(_direction_service())
    service.process_trigger_event(_trigger("touch", 1000))
    for timestamp in (1100, 1200, 1300):
        service.process_position(_pos("sheet_01", 1, 1, timestamp))
    service.process_trigger_event(_trigger("departure", 1400))
    service.process_trigger_event(_trigger("stop", 1800))
    state = service.process_trigger_event(_trigger("touch", 2000))
    assert state.status == DirectionStatus.DETECTING.value
    assert state.direction == "UNKNOWN"


def test_multi_sheet_direction_state_is_isolated() -> None:
    """多赛道方向状态必须相互隔离。"""

    direction = _direction_service()
    direction.start_monitoring("sheet_01")
    direction.start_monitoring("sheet_02")
    for timestamp in (1100, 1200, 1300):
        direction.update_position(_pos("sheet_01", 1, 1, timestamp))
    assert direction.get_direction("sheet_01").direction == "A_TO_B"
    assert direction.get_direction("sheet_02").direction == "UNKNOWN"


def test_replay_reset_is_deterministic_and_cases_are_correct() -> None:
    """Replay reset 后重复运行结果一致，并能覆盖 A_TO_B/B_TO_A。"""

    for path, expected in [
        ("data/mock/stone/trigger_case_A_to_B.jsonl", "A_TO_B"),
        ("data/mock/stone/trigger_case_B_to_A.jsonl", "B_TO_A"),
    ]:
        replay = JsonlReplaySource(path)
        first = [(record.kind, record.timestamp) for record in replay.all_records()]
        replay.reset()
        second = [(record.kind, record.timestamp) for record in replay.all_records()]
        assert first == second

        service = StoneEventService(_direction_service())
        state = None
        for record in replay.all_records():
            if record.kind == "trigger":
                state = service.process_trigger_event(record.payload)
            else:
                state = service.process_position(record.payload)
        assert state is not None
        assert state.direction == expected
        assert state.status == DirectionStatus.FROZEN.value
