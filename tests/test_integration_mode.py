"""Phase 4.6 Integration/Mock V2 公网联调模式测试。"""

import json

from fastapi.testclient import TestClient

from app.core.config import get_config_manager, get_settings
from app.core.runtime import runtime_manager
from app.main import create_app
from app.services.integration_mock_service import IntegrationMockService


SHEET_SEQUENCE = ["sheet_01", "sheet_02", "sheet_03", "sheet_04", "sheet_05", "sheet_06"]


def _enable_integration(monkeypatch) -> TestClient:
    """启用 integration/mock 环境并创建独立 TestClient。"""

    monkeypatch.setenv("APP_ENV", "integration")
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://algorithm-test.example.com")
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    runtime_manager.clear()
    return TestClient(create_app())


def _start_payload(match_id: str, sheet_id: str = "sheet_01", with_players: bool = True) -> dict:
    """构造 V2 竞赛 start 请求。"""

    payload = {
        "action": "start",
        "match_id": match_id,
        "match_name": "Integration Mock 比赛",
        "description": "公网联调说明",
        "sheet_id": sheet_id,
        "scene_type": "competition",
        "start_time": "2026-08-18T10:00:00+08:00",
        "camera_config": {
            "overview_cameras": ["overview_A", "overview_B"],
            "house_cameras": [f"{sheet_id}_house_A", f"{sheet_id}_house_B"],
        },
    }
    if with_players:
        payload["teams"] = [{"team_id": "team_red", "team_name": "Red"}]
        payload["players"] = [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}]
    return payload



def _assert_video_results_have_duration(results: list[dict]) -> None:
    """确认所有视频结果项都返回秒级时长。"""

    assert results
    for item in results:
        assert "duration_seconds" in item
        assert isinstance(item["duration_seconds"], (int, float))
        assert item["duration_seconds"] > 0
        assert item["media_url"]
def _force_complete(match_id: str) -> None:
    """把 Integration Mock 赛后开始时间前移，模拟时间推进。"""

    match = runtime_manager.get_match(match_id)
    match.postprocess_started_at = (match.postprocess_started_at or 0) - 10


def _configured_media() -> dict:
    """读取 integration_mock.json 中的 sheet_media，测试不复制真实 RTSP 字符串。"""

    return get_config_manager().integration_mock_config.sheet_media


def _assert_configured_cross_mapping() -> None:
    """确认当前六赛道配置关系为 A->B、B->A、C->D、D->C、A->C、B->D。"""

    media = _configured_media()
    a = media["sheet_01"].preview_url
    b = media["sheet_01"].media_url
    c = media["sheet_03"].preview_url
    d = media["sheet_03"].media_url
    assert media["sheet_02"].preview_url == b
    assert media["sheet_02"].media_url == a
    assert media["sheet_04"].preview_url == d
    assert media["sheet_04"].media_url == c
    assert media["sheet_05"].preview_url == a
    assert media["sheet_05"].media_url == c
    assert media["sheet_06"].preview_url == b
    assert media["sheet_06"].media_url == d
    for sheet_id in SHEET_SEQUENCE:
        assert media[sheet_id].preview_url
        assert media[sheet_id].media_url
        assert media[sheet_id].preview_url != media[sheet_id].media_url
        assert media[sheet_id].preview_url.startswith("rtsp")
        assert media[sheet_id].media_url.startswith("rtsp")


def test_integration_config_health_public_base_url_and_resources(monkeypatch) -> None:
    """integration 配置、mock_mode、RTSP preview 和 /site/resources 应可用。"""

    client = _enable_integration(monkeypatch)
    assert IntegrationMockService().enabled()
    _assert_configured_cross_mapping()
    health = client.get("/health")
    assert health.status_code == 200
    data = health.json()["data"]
    assert data["environment"] == "integration"
    assert data["mock_mode"] is True

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    assert len(resources) == 6
    media = _configured_media()
    for sheet in resources:
        sheet_id = sheet["sheet_id"]
        assert sheet["live_status"] == "idle"
        assert sheet["preview_url"] == media[sheet_id].preview_url
        camera_ids = {camera["camera_id"] for camera in sheet["cameras"]}
        assert {"overview_A", "overview_B", f"{sheet_id}_house_A", f"{sheet_id}_house_B"} == camera_ids
        assert f"{sheet_id}_me_A" not in camera_ids
        assert f"{sheet_id}_cl_A" not in camera_ids


def test_integration_six_sheet_rtsp_media_mapping(monkeypatch) -> None:
    """六条赛道均按 sheet_id 返回各自配置的 preview_url 和 start media_url。"""

    client = _enable_integration(monkeypatch)
    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    resource_by_sheet = {item["sheet_id"]: item for item in resources}
    media = _configured_media()
    for sheet_id in SHEET_SEQUENCE:
        assert resource_by_sheet[sheet_id]["preview_url"] == media[sheet_id].preview_url
        response = client.post("/api/v1/match/control", json=_start_payload(f"rtsp_{sheet_id}", sheet_id))
        assert response.status_code == 200
        start_data = response.json()["data"]
        assert start_data["media_url"] == media[sheet_id].media_url
        assert start_data["media_url"] != resource_by_sheet[sheet_id]["preview_url"]
        output = client.get("/api/v1/director/output", params={"match_id": f"rtsp_{sheet_id}"}).json()["data"]
        assert output["media_url"] == start_data["media_url"]


def test_integration_sheet_media_fallback(monkeypatch, tmp_path) -> None:
    """当某条 sheet_media 缺失 URL 时，仍保留 PUBLIC_BASE_URL fallback。"""

    config_path = tmp_path / "integration_mock_fallback.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "sheets": ["sheet_01"],
                "sheet_media": {"sheet_01": {"preview_url": None, "media_url": None}},
                "mock_media": {"enabled": True, "stream_format": "m3u8"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "integration")
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://fallback.example.com")
    monkeypatch.setenv("INTEGRATION_MOCK_PATH", str(config_path))
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    service = IntegrationMockService()
    assert service.preview_media_url("sheet_01") == "https://fallback.example.com/integration/media/site/sheet_01/preview/program.m3u8"
    assert service.live_media_url("match_fallback", "sheet_01", "smart_director") == "https://fallback.example.com/integration/media/match_fallback/sheet_01/smart_director/program.m3u8"


def test_integration_v2_single_sheet_flow(monkeypatch) -> None:
    """完整覆盖 V2 公网联调主链路。"""

    client = _enable_integration(monkeypatch)
    media = _configured_media()
    response = client.post("/api/v1/match/control", json=_start_payload("match_integration_001", "sheet_01"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sheet_id"] == "sheet_01"
    assert data["media_url"] == media["sheet_01"].media_url
    assert "outputs" not in data

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
    assert sheet_01["live_status"] == "running"
    assert sheet_01["match_id"] == "match_integration_001"
    assert sheet_01["preview_url"] == media["sheet_01"].preview_url

    output = client.get("/api/v1/director/output", params={"match_id": "match_integration_001"}).json()["data"]
    assert output["sheet_id"] == "sheet_01"
    assert output["media_url"] == data["media_url"]

    assert client.post("/api/v1/match/control", json=_start_payload("match_conflict", "sheet_01")).status_code == 400
    assert client.post("/api/v1/match/control", json=_start_payload("match_sheet_02", "sheet_02")).status_code == 200

    update = client.post(
        "/api/v1/match/control",
        json={
            "action": "update_config",
            "match_id": "match_integration_001",
            "sheet_id": "sheet_01",
            "match_name": "Integration Mock 更新比赛",
            "description": "公网联调更新说明",
            "players": [{"player_id": "p2"}],
        },
    )
    assert update.status_code == 200
    bad_update = client.post(
        "/api/v1/match/control",
        json={"action": "update_config", "match_id": "match_integration_001", "sheet_id": "sheet_03"},
    )
    assert bad_update.status_code == 400

    stop = client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_integration_001"})
    assert stop.status_code == 200
    stop_data = stop.json()["data"]
    assert stop_data["status"] == "completed"
    assert stop_data["edit_status"] == "not_started"
    assert stop_data["record_url"].startswith("https://algorithm-test.example.com/integration/media/")

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
    assert sheet_01["live_status"] == "idle"

    history = client.get("/api/v1/match/history").json()["data"]["records"]
    record = next(item for item in history if item["match_id"] == "match_integration_001")
    assert record["match_name"] == "Integration Mock 更新比赛"
    assert record["description"] == "公网联调更新说明"
    assert record["record_status"] == "completed"
    assert record["edit_status"] == "not_started"

    status = client.get("/api/v1/edit/status", params={"match_id": "match_integration_001"}).json()["data"]
    assert status["status"] == "not_started"
    assert status["progress"] == 0
    assert client.get("/api/v1/edit/result", params={"match_id": "match_integration_001"}).json()["data"]["results"] == []

    edit = client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_integration_001"})
    assert edit.status_code == 200
    assert edit.json()["data"]["status"] == "processing"
    assert client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_integration_001"}).status_code == 200

    processing = client.get("/api/v1/edit/status", params={"match_id": "match_integration_001"}).json()["data"]
    assert processing["status"] == "processing"
    assert 0 < processing["progress"] < 100

    _force_complete("match_integration_001")
    completed = client.get("/api/v1/edit/status", params={"match_id": "match_integration_001"}).json()["data"]
    assert completed["status"] == "completed"
    assert completed["progress"] == 100

    result = client.get("/api/v1/edit/result", params={"match_id": "match_integration_001"}).json()["data"]
    assert result["status"] == "completed"
    assert result["result_mode"] == "matched_highlights"
    assert all(item["media_url"].startswith("https://algorithm-test.example.com/integration/media/") for item in result["results"])
    _assert_video_results_have_duration(result["results"])
    by_type = {item["result_type"]: item for item in result["results"]}
    durations = get_config_manager().integration_mock_config.mock_media
    assert by_type["player_highlight"]["duration_seconds"] == durations["player_highlight_duration_seconds"]
    assert by_type["team_highlight"]["duration_seconds"] == durations["team_highlight_duration_seconds"]


def test_integration_labeled_clips_overview_and_errors(monkeypatch) -> None:
    """无人员竞赛走 labeled_clips，overview 场景走 participant_media，并覆盖异常。"""

    client = _enable_integration(monkeypatch)
    assert client.post("/api/v1/match/control", json=_start_payload("match_no_players", "sheet_01", with_players=False)).status_code == 200
    client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_no_players"})
    client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_no_players"})
    _force_complete("match_no_players")
    client.get("/api/v1/edit/status", params={"match_id": "match_no_players"})
    result = client.get("/api/v1/edit/result", params={"match_id": "match_no_players"}).json()["data"]
    assert result["result_mode"] == "labeled_clips"
    _assert_video_results_have_duration(result["results"])

    overview_payload = _start_payload("match_overview", "sheet_02")
    overview_payload["scene_type"] = "personal_training"
    response = client.post("/api/v1/match/control", json=overview_payload)
    assert response.status_code == 200
    assert response.json()["data"]["stream_type"] == "overview_live"

    assert client.get("/api/v1/director/output", params={"match_id": "missing"}).status_code == 404
    assert client.post("/api/v1/edit/control", json={"action": "start", "match_id": "missing"}).status_code == 404
    assert client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_overview"}).status_code == 400

    invalid_scene = _start_payload("bad_scene", "sheet_03")
    invalid_scene["scene_type"] = "bad"
    assert client.post("/api/v1/match/control", json=invalid_scene).status_code == 400

    missing_sheet = _start_payload("missing_sheet", "sheet_03")
    missing_sheet.pop("sheet_id")
    assert client.post("/api/v1/match/control", json=missing_sheet).status_code == 400

    invalid_sheet = _start_payload("invalid_sheet", "sheet_99")
    assert client.post("/api/v1/match/control", json=invalid_sheet).status_code == 400


def test_production_does_not_enable_integration_mock(monkeypatch) -> None:
    """production 环境即使误设 MOCK_MODE=true，也不能启用 integration mock。"""

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MOCK_MODE", "true")
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    assert not IntegrationMockService().enabled()

