"""Phase 5 Throw State Machine + Shot 生命周期测试。"""

from __future__ import annotations

from app.adapters.stone.replay import JsonlReplaySource
from app.core.enums import ShotQualityStatus, ThrowStatus
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.event import TriggerEvent
from app.models.shot import ShotEventContext
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService
from app.services.stone_event_service import StoneEventService
from app.storage.shot_repository import ShotRepository


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


def _service(confirm_count: int = 3) -> StoneEventService:
    """构造带明确方向区域的 Phase 5 服务。"""

    return StoneEventService(DirectionService(confirm_count=confirm_count, direction_zones_by_sheet=ZONES))


def _trigger(event_type: str, timestamp: int, sheet_id: str = "sheet_01") -> TriggerEvent:
    """构造 TriggerEvent。"""

    return TriggerEvent(sheet_id=sheet_id, lane_id=f"trigger_{sheet_id}", timestamp=timestamp, event_type=event_type)


def _pos(sheet_id: str, x: float, y: float, timestamp: int) -> StonePosition:
    """构造 StonePosition。"""

    return StonePosition(sheet_id=sheet_id, lane_id=f"position_{sheet_id}", tag_id="tag_001", timestamp=timestamp, x=x, y=y)


def _assert_context(value) -> ShotEventContext:
    """帮助类型收窄：Phase 5 传 match_id 时应返回 ShotEventContext。"""

    assert isinstance(value, ShotEventContext)
    return value


def test_touch_creates_shot_and_duplicate_touch_is_idempotent() -> None:
    """touch 创建 Shot，重复 touch 不创建第二个 shot_id。"""

    service = _service()
    first = _assert_context(service.process_trigger_event(_trigger("touch", 1000), match_id="match_touch"))
    second = _assert_context(service.process_trigger_event(_trigger("touch", 1001), match_id="match_touch"))
    assert first.shot_status == ThrowStatus.TOUCHED.value
    assert first.shot_id == second.shot_id
    assert service.get_current_shot("match_touch", "sheet_01") is not None


def test_departure_freezes_direction_and_writes_shot() -> None:
    """departure 冻结方向，并把 direction/source/target 写入 Shot。"""

    service = _service()
    service.process_trigger_event(_trigger("touch", 1000), match_id="match_departure")
    for timestamp in (1100, 1200, 1300):
        service.process_position(_pos("sheet_01", 1, 1, timestamp), match_id="match_departure")
    context = _assert_context(service.process_trigger_event(_trigger("departure", 1400), match_id="match_departure"))
    assert context.shot_status == ThrowStatus.RELEASED.value
    assert context.direction == "A_TO_B"
    shot = service.get_current_shot("match_departure", "sheet_01")
    assert shot is not None
    assert shot.source_end == "A"
    service.process_position(_pos("sheet_01", 9, 9, 1500), match_id="match_departure")
    assert service.get_current_shot("match_departure", "sheet_01").direction == "A_TO_B"


def test_departure_unknown_direction_does_not_block() -> None:
    """departure 时方向 UNKNOWN 仍继续 Shot。"""

    service = _service()
    service.process_trigger_event(_trigger("touch", 1000), match_id="match_unknown")
    context = _assert_context(service.process_trigger_event(_trigger("departure", 1100), match_id="match_unknown"))
    assert context.direction == "UNKNOWN"
    assert context.source_end is None
    assert context.shot_status == ThrowStatus.RELEASED.value


def test_magnetic_alarm_and_stop_complete_without_alarm_required() -> None:
    """magnetic_1/magnetic_2/stop 推进 Shot，alarm 缺失不影响 complete。"""

    service = _service()
    match_id = "match_complete"
    service.process_trigger_event(_trigger("touch", 1000), match_id=match_id)
    service.process_trigger_event(_trigger("departure", 1100), match_id=match_id)
    m1 = _assert_context(service.process_trigger_event(_trigger("magnetic_1", 1200), match_id=match_id))
    assert m1.shot_status == ThrowStatus.PASSED_MAGNETIC_1.value
    m2 = _assert_context(service.process_trigger_event(_trigger("magnetic_2", 1300), match_id=match_id))
    assert m2.shot_status == ThrowStatus.PASSED_MAGNETIC_2.value
    finish = _assert_context(service.process_trigger_event(_trigger("stop", 1400), match_id=match_id))
    assert finish.shot_status == ThrowStatus.FINISHED.value
    assert finish.quality_status == ShotQualityStatus.COMPLETE.value
    assert service.get_current_shot(match_id, "sheet_01") is None
    assert ShotRepository().get(finish.shot_id).quality_status == ShotQualityStatus.COMPLETE.value


def test_alarm_records_time_and_keeps_state() -> None:
    """alarm 只记录 alarm_time，不改变主状态。"""

    service = _service()
    match_id = "match_alarm"
    service.process_trigger_event(_trigger("touch", 1000), match_id=match_id)
    service.process_trigger_event(_trigger("departure", 1100), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_1", 1200), match_id=match_id)
    alarm = _assert_context(service.process_trigger_event(_trigger("alarm", 1250), match_id=match_id))
    assert alarm.shot_status == ThrowStatus.PASSED_MAGNETIC_1.value
    shot = service.get_current_shot(match_id, "sheet_01")
    assert shot.alarm_time == 1250


def test_duplicate_departure_and_magnetic_keep_first_timestamp() -> None:
    """重复 departure/magnetic 不覆盖第一次时间。"""

    service = _service()
    match_id = "match_duplicate"
    service.process_trigger_event(_trigger("touch", 1000), match_id=match_id)
    service.process_trigger_event(_trigger("departure", 1100), match_id=match_id)
    service.process_trigger_event(_trigger("departure", 1110), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_1", 1200), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_1", 1210), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_2", 1300), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_2", 1310), match_id=match_id)
    finish = _assert_context(service.process_trigger_event(_trigger("stop", 1400), match_id=match_id))
    shot = ShotRepository().get(finish.shot_id)
    assert shot.departure_time == 1100
    assert shot.first_magnetic_time == 1200
    assert shot.second_magnetic_time == 1300
    assert ShotRepository().count_by_shot_id(finish.shot_id) == 1


def test_missing_magnetic_is_incomplete_but_finishable() -> None:
    """touch/departure/stop 可完成 Shot，但质量为 incomplete。"""

    service = _service()
    match_id = "match_missing_magnetic"
    service.process_trigger_event(_trigger("touch", 1000), match_id=match_id)
    service.process_trigger_event(_trigger("departure", 1100), match_id=match_id)
    finish = _assert_context(service.process_trigger_event(_trigger("stop", 1200), match_id=match_id))
    assert finish.quality_status == ShotQualityStatus.INCOMPLETE.value


def test_departure_without_touch_creates_degraded_shot() -> None:
    """缺 touch 时 departure 创建降级 Shot。"""

    service = _service()
    match_id = "match_degraded"
    context = _assert_context(service.process_trigger_event(_trigger("departure", 1000), match_id=match_id))
    assert context.shot_status == ThrowStatus.RELEASED.value
    service.process_trigger_event(_trigger("magnetic_2", 1100), match_id=match_id)
    finish = _assert_context(service.process_trigger_event(_trigger("stop", 1200), match_id=match_id))
    shot = ShotRepository().get(finish.shot_id)
    assert shot.touch_time is None
    assert shot.quality_status in {ShotQualityStatus.INCOMPLETE.value, ShotQualityStatus.ABNORMAL.value}


def test_events_without_shot_are_ignored() -> None:
    """无当前 Shot 时 magnetic/alarm/stop 安全忽略。"""

    service = _service()
    assert service.process_trigger_event(_trigger("magnetic_1", 1000), match_id="match_ignore") is None
    assert service.process_trigger_event(_trigger("magnetic_2", 1100), match_id="match_ignore") is None
    assert service.process_trigger_event(_trigger("alarm", 1200), match_id="match_ignore") is None
    assert service.process_trigger_event(_trigger("stop", 1300), match_id="match_ignore") is None


def test_continuous_shots_have_unique_ids_and_fresh_direction() -> None:
    """连续 Shot 的 shot_id 不重复，下一投不继承上一投方向。"""

    service = _service()
    match_id = "match_sequence"
    first = _assert_context(service.process_trigger_event(_trigger("touch", 1000), match_id=match_id))
    service.process_position(_pos("sheet_01", 1, 1, 1100), match_id=match_id)
    service.process_position(_pos("sheet_01", 1, 1, 1200), match_id=match_id)
    service.process_position(_pos("sheet_01", 1, 1, 1300), match_id=match_id)
    service.process_trigger_event(_trigger("departure", 1400), match_id=match_id)
    service.process_trigger_event(_trigger("stop", 1500), match_id=match_id)
    second = _assert_context(service.process_trigger_event(_trigger("touch", 2000), match_id=match_id))
    assert first.shot_id != second.shot_id
    assert service.get_current_shot(match_id, "sheet_01").direction == "UNKNOWN"


def test_multi_sheet_and_multi_match_are_isolated() -> None:
    """Shot 和 Direction 均按 match_id + sheet_id 隔离。"""

    service = _service()
    a = _assert_context(service.process_trigger_event(_trigger("touch", 1000, "sheet_01"), match_id="match_a"))
    b = _assert_context(service.process_trigger_event(_trigger("touch", 1000, "sheet_02"), match_id="match_a"))
    c = _assert_context(service.process_trigger_event(_trigger("touch", 1000, "sheet_01"), match_id="match_b"))
    assert len({a.shot_id, b.shot_id, c.shot_id}) == 3
    service.process_position(_pos("sheet_01", 1, 1, 1100), match_id="match_a")
    service.process_position(_pos("sheet_01", 1, 1, 1200), match_id="match_a")
    service.process_position(_pos("sheet_01", 1, 1, 1300), match_id="match_a")
    service.process_trigger_event(_trigger("departure", 1400, "sheet_01"), match_id="match_a")
    assert service.get_current_shot("match_b", "sheet_01").direction == "UNKNOWN"


def test_runtime_current_shot_and_history_are_synced() -> None:
    """StoneEventService 会同步 current_shot_id、current_shot 和 shot_history。"""

    match = MatchRuntime(
        match_id="match_runtime",
        scene_type="competition",
        start_time="2026-08-13T10:00:00+08:00",
        sheets={"sheet_01": SheetRuntime(sheet_id="sheet_01", enabled=True, stream_type="smart_director", media_url="mock://")},
    )
    runtime_manager.create_match(match)
    service = _service()
    touch = _assert_context(service.process_trigger_event(_trigger("touch", 1000), match_id="match_runtime"))
    sheet = runtime_manager.get_match("match_runtime").sheets["sheet_01"]
    assert sheet.current_shot_id == touch.shot_id
    assert sheet.current_shot is not None
    service.process_trigger_event(_trigger("departure", 1100), match_id="match_runtime")
    service.process_trigger_event(_trigger("stop", 1200), match_id="match_runtime")
    assert sheet.current_shot_id is None
    assert touch.shot_id in sheet.shot_history


def test_replay_a_to_b_and_b_to_a_persist_to_sqlite() -> None:
    """Phase 5 Replay A_TO_B/B_TO_A 应完成并保存 SQLite。"""

    for match_id, path, direction in [
        ("match_replay_a", "data/mock/stone/phase5_A_to_B_complete.jsonl", "A_TO_B"),
        ("match_replay_b", "data/mock/stone/phase5_B_to_A_alarm.jsonl", "B_TO_A"),
    ]:
        service = _service()
        last = None
        for record in JsonlReplaySource(path).all_records():
            if isinstance(record.payload, TriggerEvent):
                value = service.process_trigger_event(record.payload, match_id=match_id)
                if value is not None:
                    last = _assert_context(value)
            else:
                service.process_position(record.payload, match_id=match_id)
        assert last is not None
        shot = ShotRepository().get(last.shot_id)
        assert shot.status == ThrowStatus.FINISHED.value
        assert shot.direction == direction
        assert shot.quality_status == ShotQualityStatus.COMPLETE.value
        if direction == "B_TO_A":
            assert shot.alarm_time == 2550


def test_shot_event_context_structure_and_sqlite_fields() -> None:
    """ShotEventContext 和 SQLite 字段应包含后续 Director 所需字段。"""

    service = _service()
    match_id = "match_context"
    context = _assert_context(service.process_trigger_event(_trigger("touch", 1000), match_id=match_id))
    assert set(context.model_dump()).issuperset(
        {"match_id", "sheet_id", "shot_id", "event_type", "timestamp", "shot_status", "direction", "source_end", "target_end", "quality_status"}
    )
    service.process_trigger_event(_trigger("departure", 1100), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_1", 1200), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_2", 1300), match_id=match_id)
    finish = _assert_context(service.process_trigger_event(_trigger("stop", 1400), match_id=match_id))
    shot = ShotRepository().get(finish.shot_id)
    assert set(shot.model_dump()).issuperset(
        {"shot_id", "match_id", "sheet_id", "touch_time", "departure_time", "first_magnetic_time", "alarm_time", "second_magnetic_time", "stop_time", "direction", "source_end", "target_end", "status", "quality_status"}
    )


def test_abnormal_replay_order_does_not_crash() -> None:
    """乱序事件不做复杂缓冲，但不得崩溃。"""

    service = _service()
    match_id = "match_abnormal"
    service.process_trigger_event(_trigger("touch", 1000), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_2", 1100), match_id=match_id)
    service.process_trigger_event(_trigger("magnetic_1", 1200), match_id=match_id)
    finish = _assert_context(service.process_trigger_event(_trigger("stop", 1300), match_id=match_id))
    assert finish.quality_status == ShotQualityStatus.ABNORMAL.value
