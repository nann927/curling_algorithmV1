"""现场配置适配测试。"""

from app.core.config import get_config_manager


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


def test_director_runtime_exposes_configured_camera_groups() -> None:
    """竞赛 Runtime 应携带配置层查到的候选镜头，供后续切镜使用。"""

    from app.services.director_service import DirectorService

    sheet = DirectorService().start_sheet("match_config", "sheet_06", ["A", "B"])
    assert set(sheet.available_camera_ids) == {"medium_shot", "close_shot", "house_top"}
    assert "sheet_06_me_A" in sheet.available_camera_ids["medium_shot"]
    assert "sheet_06_cl_B" in sheet.available_camera_ids["close_shot"]
    assert "sheet_06_house_A" in sheet.available_camera_ids["house_top"]
