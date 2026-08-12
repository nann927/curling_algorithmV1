"""Phase 4.5 Integration/Mock 公网联调模式测试。"""

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


def _competition_payload(match_id: str, sheets: list[str], with_players: bool = True) -> dict:
    """构造竞赛 start 请求。"""

    payload = {
        "action": "start",
        "match_id": match_id,
        "scene_type": "competition",
        "start_time": "2026-08-11T10:00:00+08:00",
        "camera_config": {
            "overview_cameras": ["overview_A"],
            "sheets": [{"sheet_id": sheet_id, "house_camera_ends": ["A", "B"]} for sheet_id in sheets],
        },
    }
    if with_players:
        payload["teams"] = [{"team_id": "team_red", "team_name": "Red"}]
        payload["players"] = [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}]
    return payload


def _overview_payload(match_id: str) -> dict:
    """构造 overview 场景 start 请求。"""

    return {
        "action": "start",
        "match_id": match_id,
        "scene_type": "personal_training",
        "start_time": "2026-08-11T10:00:00+08:00",
        "camera_config": {"overview_cameras": ["overview_A"], "sheets": [{"sheet_id": "sheet_01"}]},
    }


def _force_complete(match_id: str) -> None:
    """把 Integration Mock 赛后开始时间前移，模拟时间推进。"""

    match = runtime_manager.get_match(match_id)
    match.postprocess_started_at = (match.postprocess_started_at or 0) - 10


def test_integration_config_health_and_public_base_url(monkeypatch) -> None:
    """integration 配置、mock_mode 和 /health 应可用。"""

    client = _enable_integration(monkeypatch)
    assert IntegrationMockService().enabled()
    health = client.get("/health")
    assert health.status_code == 200
    data = health.json()["data"]
    assert data["environment"] == "integration"
    assert data["mock_mode"] is True


def test_integration_competition_start_update_output_stop_status_result(monkeypatch) -> None:
    """完整覆盖 PC 后端主联调链路。"""

    client = _enable_integration(monkeypatch)
    response = client.post("/api/v1/match/control", json=_competition_payload("match_integration_001", ["sheet_01", "sheet_02"]))
    assert response.status_code == 200
    outputs = response.json()["data"]["outputs"]
    assert {item["sheet_id"] for item in outputs} == {"sheet_01", "sheet_02"}
    assert all(item["media_url"].startswith("https://algorithm-test.example.com/integration/media/") for item in outputs)

    response = client.get("/api/v1/director/output", params={"match_id": "match_integration_001"})
    assert {item["sheet_id"] for item in response.json()["data"]["outputs"]} == {"sheet_01", "sheet_02"}

    update_payload = {
        "action": "update_config",
        "match_id": "match_integration_001",
        "camera_config": {
            "overview_cameras": ["overview_A"],
            "sheets": [
                {"sheet_id": "sheet_01", "house_camera_ends": ["A", "B"]},
                {"sheet_id": "sheet_03", "house_camera_ends": ["A", "B"]},
            ],
        },
    }
    response = client.post("/api/v1/match/control", json=update_payload)
    assert response.status_code == 200
    assert {item["sheet_id"] for item in response.json()["data"]["outputs"]} == {"sheet_01", "sheet_03"}

    response = client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_integration_001"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "post_processing"

    status = client.get("/api/v1/edit/status", params={"match_id": "match_integration_001"}).json()["data"]
    assert status["status"] == "processing"
    assert 0 < status["progress"] < 100

    early_result = client.get("/api/v1/edit/result", params={"match_id": "match_integration_001"}).json()["data"]
    assert early_result["status"] == "processing"
    assert early_result["results"] == []

    _force_complete("match_integration_001")
    completed = client.get("/api/v1/edit/status", params={"match_id": "match_integration_001"}).json()["data"]
    assert completed["status"] == "completed"
    assert completed["progress"] == 100

    result = client.get("/api/v1/edit/result", params={"match_id": "match_integration_001"}).json()["data"]
    assert result["status"] == "completed"
    assert result["result_mode"] == "matched_highlights"
    assert all(item["media_url"].startswith("https://algorithm-test.example.com/integration/media/") for item in result["results"])
    assert client.get("/api/v1/edit/result", params={"match_id": "match_integration_001"}).status_code == 200


def test_integration_labeled_clips_and_overview_result(monkeypatch) -> None:
    """无人员竞赛走 labeled_clips，overview 场景走 participant_media。"""

    client = _enable_integration(monkeypatch)
    response = client.post("/api/v1/match/control", json=_competition_payload("match_no_players", ["sheet_01"], with_players=False))
    assert response.status_code == 200
    client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_no_players"})
    _force_complete("match_no_players")
    client.get("/api/v1/edit/status", params={"match_id": "match_no_players"})
    result = client.get("/api/v1/edit/result", params={"match_id": "match_no_players"}).json()["data"]
    assert result["result_mode"] == "labeled_clips"

    response = client.post("/api/v1/match/control", json=_overview_payload("match_overview"))
    assert response.status_code == 200
    assert response.json()["data"]["outputs"][0]["stream_type"] == "overview_live"
    client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_overview"})
    _force_complete("match_overview")
    client.get("/api/v1/edit/status", params={"match_id": "match_overview"})
    result = client.get("/api/v1/edit/result", params={"match_id": "match_overview"}).json()["data"]
    assert result["result_mode"] == "participant_media"


def test_integration_multi_match_and_error_cases(monkeypatch) -> None:
    """多 match 隔离，并覆盖公网联调常见异常。"""

    client = _enable_integration(monkeypatch)
    assert client.post("/api/v1/match/control", json=_competition_payload("match_a", ["sheet_01"])).status_code == 200
    assert client.post("/api/v1/match/control", json=_competition_payload("match_b", ["sheet_02"])).status_code == 200
    assert {item["sheet_id"] for item in client.get("/api/v1/director/output", params={"match_id": "match_a"}).json()["data"]["outputs"]} == {"sheet_01"}
    assert {item["sheet_id"] for item in client.get("/api/v1/director/output", params={"match_id": "match_b"}).json()["data"]["outputs"]} == {"sheet_02"}

    assert client.post("/api/v1/match/control", json=_competition_payload("match_a", ["sheet_01"])).status_code == 400
    assert client.get("/api/v1/director/output", params={"match_id": "missing"}).status_code == 404
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "missing"}).status_code == 404

    invalid_scene = _competition_payload("bad_scene", ["sheet_01"])
    invalid_scene["scene_type"] = "bad"
    assert client.post("/api/v1/match/control", json=invalid_scene).status_code == 400

    missing_camera = _competition_payload("missing_camera", ["sheet_01"])
    missing_camera.pop("camera_config")
    assert client.post("/api/v1/match/control", json=missing_camera).status_code == 400

    empty_sheets = _competition_payload("empty_sheets", [])
    assert client.post("/api/v1/match/control", json=empty_sheets).status_code == 400

    invalid_sheet = _competition_payload("invalid_sheet", ["sheet_99"])
    assert client.post("/api/v1/match/control", json=invalid_sheet).status_code == 400

    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_a"}).status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_a"}).status_code == 400


def test_production_does_not_enable_integration_mock(monkeypatch) -> None:
    """production 环境即使误设 MOCK_MODE=true，也不能启用 integration mock。"""

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MOCK_MODE", "true")
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    assert not IntegrationMockService().enabled()
