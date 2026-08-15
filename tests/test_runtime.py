"""RuntimeManager V2 单赛道占用测试。"""

import pytest

from app.core.enums import SceneType
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager


def test_one_match_holds_single_sheet_and_sheet_occupancy() -> None:
    """V2 中一个 match 只绑定一条赛道，同赛道 running 时不能重复占用。"""

    match = MatchRuntime(
        match_id="match_001",
        sheet_id="sheet_01",
        scene_type=SceneType.COMPETITION.value,
        start_time="2026-08-15T10:00:00+08:00",
        sheets={"sheet_01": SheetRuntime("sheet_01", True, "smart_director", "mock://1")},
    )
    runtime_manager.create_match(match)
    assert runtime_manager.is_sheet_occupied("sheet_01")
    assert runtime_manager.get_running_match_by_sheet("sheet_01").match_id == "match_001"

    with pytest.raises(ValueError, match="sheet already occupied"):
        runtime_manager.create_match(
            MatchRuntime(
                match_id="match_002",
                sheet_id="sheet_01",
                scene_type=SceneType.COMPETITION.value,
                start_time="2026-08-15T10:00:00+08:00",
                sheets={"sheet_01": SheetRuntime("sheet_01", True, "smart_director", "mock://2")},
            )
        )

    runtime_manager.stop_match("match_001")
    assert not runtime_manager.is_sheet_occupied("sheet_01")
