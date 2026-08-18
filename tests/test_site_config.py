"""现场配置适配测试。"""

from app.core.config import get_config_manager
from app.services.director_service import DirectorService


def _ids(cameras) -> list[str]:
    """提取 camera_id，便于断言顺序和集合。"""

    return [camera.camera_id for camera in cameras]


def test_site_config_supports_six_sheets_and_camera_roles() -> None:
    """当前 site_config 应支持 6 条赛道及每条赛道 A/B 两端镜头配置。"""

    manager = get_config_manager()
    sheet_ids = {sheet.sheet_id for sheet in manager.site_config.sheets}
    assert sheet_ids == {"sheet_01", "sheet_02", "sheet_03", "sheet_04", "sheet_05", "sheet_06"}

    lane_mapping = {item.lane_id: item.sheet_id for item in manager.site_config.lane_mappings}
    assert lane_mapping == {
        "curlingLane1Data": "sheet_01",
        "curlingLane2Data": "sheet_02",
        "curlingLane3Data": "sheet_03",
        "curlingLane4Data": "sheet_04",
        "curlingLane5Data": "sheet_05",
        "curlingLane6Data": "sheet_06",
    }

    for sheet_id in sorted(sheet_ids):
        medium = manager.get_sheet_cameras(sheet_id, camera_role="medium_shot")
        close = manager.get_sheet_cameras(sheet_id, camera_role="close_shot")
        house = manager.get_sheet_cameras(sheet_id, camera_role="house_top")
        assert {camera.install_end for camera in medium} == {"A", "B"}
        assert {camera.install_end for camera in close} == {"A", "B"}
        assert {camera.install_end for camera in house} == {"A", "B"}


def test_overview_array_camera_mapping_uses_structured_config() -> None:
    """overview_A/B 应按 sheet_id + install_end + camera_role 展开，不包含 house_top。"""

    manager = get_config_manager()
    assert _ids(manager.get_array_cameras("sheet_01", "overview_A")) == ["sheet_01_me_A", "sheet_01_cl_A"]
    assert _ids(manager.get_array_cameras("sheet_01", "overview_B")) == ["sheet_01_me_B", "sheet_01_cl_B"]
    assert _ids(manager.get_array_cameras("sheet_03", "overview_A")) == ["sheet_03_me_A", "sheet_03_cl_A"]

    overview_a_ids = set(_ids(manager.get_array_cameras("sheet_01", "overview_A")))
    assert "sheet_01_house_A" not in overview_a_ids
    assert "sheet_01_me_B" not in overview_a_ids
    assert "sheet_01_cl_B" not in overview_a_ids


def test_invalid_overview_and_house_camera_validation() -> None:
    """非法 overview 和跨赛道 house camera 必须拒绝。"""

    manager = get_config_manager()
    try:
        manager.get_array_cameras("sheet_01", "overview_C")
    except ValueError as exc:
        assert "unsupported overview camera" in str(exc)
    else:
        raise AssertionError("overview_C should be rejected")

    assert manager.get_house_camera("sheet_01", "sheet_01_house_A").camera_id == "sheet_01_house_A"
    try:
        manager.get_house_camera("sheet_01", "sheet_02_house_A")
    except ValueError as exc:
        assert "does not belong to sheet" in str(exc)
    else:
        raise AssertionError("cross-sheet house camera should be rejected")


def test_director_runtime_uses_selected_camera_candidates_only() -> None:
    """竞赛 Runtime 只携带 MatchService 解析后的候选镜头，未选择的 house/端位不应自动出现。"""

    sheet = DirectorService().start_sheet(
        "match_config",
        "sheet_06",
        {
            "medium_shot": ["sheet_06_me_A"],
            "close_shot": ["sheet_06_cl_A"],
            "house_top": ["sheet_06_house_A"],
        },
    )
    assert set(sheet.available_camera_ids) == {"medium_shot", "close_shot", "house_top"}
    assert sheet.available_camera_ids["medium_shot"] == ["sheet_06_me_A"]
    assert sheet.available_camera_ids["close_shot"] == ["sheet_06_cl_A"]
    assert sheet.available_camera_ids["house_top"] == ["sheet_06_house_A"]
    assert "sheet_06_house_B" not in sheet.available_camera_ids["house_top"]
