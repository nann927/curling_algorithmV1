"""RuntimeManager 多赛道隔离测试。"""

from app.core.enums import SceneType
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager


def test_one_match_can_hold_three_independent_sheets() -> None:
    """同一个 match_id 下可以同时维护三条独立赛道。"""

    match = MatchRuntime(
        match_id="match_001",
        scene_type=SceneType.COMPETITION.value,
        start_time="2026-08-06T10:00:00+08:00",
        sheets={
            "sheet_01": SheetRuntime("sheet_01", True, "smart_director", "mock://1"),
            "sheet_02": SheetRuntime("sheet_02", True, "smart_director", "mock://2"),
            "sheet_03": SheetRuntime("sheet_03", True, "smart_director", "mock://3"),
        },
    )

    runtime_manager.create_match(match)
    loaded = runtime_manager.get_match("match_001")

    assert set(loaded.sheets) == {"sheet_01", "sheet_02", "sheet_03"}
    # 模拟单赛道异常，确认不会改写其他赛道状态。
    loaded.sheets["sheet_02"].status = "failed"
    assert loaded.sheets["sheet_01"].status != "failed"
    assert loaded.sheets["sheet_03"].status != "failed"
