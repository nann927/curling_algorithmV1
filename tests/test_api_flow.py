"""软件接口 Phase 2 Mock 闭环测试。"""

import time

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _start_payload(match_id: str = "match_001") -> dict:
    """构造竞赛场景 start 请求。"""

    return {
        "action": "start",
        "match_id": match_id,
        "scene_type": "competition",
        "start_time": "2026-08-06T10:00:00+08:00",
        "teams": [{"team_id": "team_red", "team_name": "Red"}],
        "players": [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}],
        "camera_config": {
            "overview_cameras": ["overview_A"],
            "sheets": [
                {"sheet_id": "sheet_01", "house_camera_ends": ["A", "B"]},
                {"sheet_id": "sheet_02", "house_camera_ends": ["A"]},
            ],
        },
    }


def test_health() -> None:
    """健康检查接口应返回统一响应结构。"""

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_start_update_output_stop_edit_result_flow() -> None:
    """覆盖 start -> update_config -> output -> stop -> status -> result 主链路。"""

    response = client.post("/api/v1/match/control", json=_start_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["match_id"] == "match_001"
    assert {item["sheet_id"] for item in data["outputs"]} == {"sheet_01", "sheet_02"}
    assert {item["stream_type"] for item in data["outputs"]} == {"smart_director"}

    response = client.get("/api/v1/director/output", params={"match_id": "match_001"})
    assert response.status_code == 200
    assert {item["sheet_id"] for item in response.json()["data"]["outputs"]} == {"sheet_01", "sheet_02"}

    update_payload = {
        "action": "update_config",
        "match_id": "match_001",
        "camera_config": {
            "overview_cameras": ["overview_B"],
            "sheets": [
                {"sheet_id": "sheet_01", "house_camera_ends": ["A", "B"]},
                {"sheet_id": "sheet_03", "house_camera_ends": ["B"]},
            ],
        },
    }
    response = client.post("/api/v1/match/control", json=update_payload)
    assert response.status_code == 200
    assert {item["sheet_id"] for item in response.json()["data"]["outputs"]} == {"sheet_01", "sheet_03"}

    response = client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_001"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "post_processing"

    response = client.get("/api/v1/edit/status", params={"match_id": "match_001"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] in {"processing", "completed"}

    deadline = time.time() + 1
    status = None
    while time.time() < deadline:
        # Mock 赛后处理在后台线程完成，这里轮询直到上传完成后进入 completed。
        status_data = client.get("/api/v1/edit/status", params={"match_id": "match_001"}).json()["data"]
        status = status_data["status"]
        if status == "completed":
            break
        time.sleep(0.02)

    assert status == "completed"
    response = client.get("/api/v1/edit/result", params={"match_id": "match_001"})
    assert response.status_code == 200
    result_data = response.json()["data"]
    assert result_data["status"] == "completed"
    assert result_data["result_mode"] == "matched_highlights"
    assert result_data["results"]
    assert all(item["media_url"].startswith("http://software-server/mock/") for item in result_data["results"])


def test_overview_scene_returns_overview_live() -> None:
    """非竞赛场景实时阶段应返回 overview_live。"""

    payload = _start_payload("training_001")
    payload["scene_type"] = "personal_training"
    payload["camera_config"]["sheets"] = [{"sheet_id": "sheet_01"}]
    response = client.post("/api/v1/match/control", json=payload)
    assert response.status_code == 200
    outputs = response.json()["data"]["outputs"]
    assert outputs[0]["stream_type"] == "overview_live"


def test_basic_errors() -> None:
    """覆盖不存在 match、重复 start、非法场景、缺配置、空赛道等基础异常。"""

    assert client.get("/api/v1/director/output", params={"match_id": "missing"}).status_code == 404

    response = client.post("/api/v1/match/control", json=_start_payload("dup_001"))
    assert response.status_code == 200
    assert client.post("/api/v1/match/control", json=_start_payload("dup_001")).status_code == 400

    bad_scene = _start_payload("bad_scene")
    bad_scene["scene_type"] = "bad"
    assert client.post("/api/v1/match/control", json=bad_scene).status_code == 400

    missing_camera = _start_payload("missing_camera")
    missing_camera.pop("camera_config")
    assert client.post("/api/v1/match/control", json=missing_camera).status_code == 400

    empty_sheets = _start_payload("empty_sheets")
    empty_sheets["camera_config"]["sheets"] = []
    assert client.post("/api/v1/match/control", json=empty_sheets).status_code == 400

    assert client.post(
        "/api/v1/match/control",
        json={
            "action": "update_config",
            "match_id": "missing",
            "camera_config": {"overview_cameras": ["overview_A"], "sheets": [{"sheet_id": "sheet_01"}]},
        },
    ).status_code == 404

    response = client.post("/api/v1/match/control", json=_start_payload("stop_twice"))
    assert response.status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "stop_twice"}).status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "stop_twice"}).status_code == 400
