"""Phase 4.6 Integration/Mock V2 公网联调模式测试。"""

from fastapi.testclient import TestClient

from app.core.config import get_config_manager, get_settings
from app.core.runtime import runtime_manager
from app.main import create_app
from app.services.integration_mock_service import IntegrationMockService


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
        "sheet_id": sheet_id,
        "scene_type": "competition",
        "start_time": "2026-08-15T10:00:00+08:00",
    }
    if with_players:
        payload["teams"] = [{"team_id": "team_red", "team_name": "Red"}]
        payload["players"] = [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}]
    return payload


def _force_complete(match_id: str) -> None:
    """把 Integration Mock 赛后开始时间前移，模拟时间推进。"""

    match = runtime_manager.get_match(match_id)
    match.postprocess_started_at = (match.postprocess_started_at or 0) - 10


def test_integration_config_health_public_base_url_and_resources(monkeypatch) -> None:
    """integration 配置、mock_mode、PUBLIC_BASE_URL 和 /site/resources 应可用。"""

    client = _enable_integration(monkeypatch)
    assert IntegrationMockService().enabled()
    health = client.get("/health")
    assert health.status_code == 200
    data = health.json()["data"]
    assert data["environment"] == "integration"
    assert data["mock_mode"] is True

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    assert len(resources) == 6
    assert resources[0]["live_status"] == "idle"
    assert resources[0]["preview_url"].startswith("https://algorithm-test.example.com/integration/media/site/")


def test_integration_v2_single_sheet_flow(monkeypatch) -> None:
    """完整覆盖 V2 公网联调主链路。"""

    client = _enable_integration(monkeypatch)
    response = client.post("/api/v1/match/control", json=_start_payload("match_integration_001", "sheet_01"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sheet_id"] == "sheet_01"
    assert data["media_url"].startswith("https://algorithm-test.example.com/integration/media/")
    assert "outputs" not in data

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
    assert sheet_01["live_status"] == "running"
    assert sheet_01["match_id"] == "match_integration_001"

    output = client.get("/api/v1/director/output", params={"match_id": "match_integration_001"}).json()["data"]
    assert output["sheet_id"] == "sheet_01"
    assert output["media_url"] == data["media_url"]

    assert client.post("/api/v1/match/control", json=_start_payload("match_conflict", "sheet_01")).status_code == 400
    assert client.post("/api/v1/match/control", json=_start_payload("match_sheet_02", "sheet_02")).status_code == 200

    update = client.post(
        "/api/v1/match/control",
        json={"action": "update_config", "match_id": "match_integration_001", "sheet_id": "sheet_01", "players": [{"player_id": "p2"}]},
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
