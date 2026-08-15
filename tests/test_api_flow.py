"""软件接口 V2 Mock 闭环测试。"""

import time

from fastapi.testclient import TestClient

from app.core.runtime import runtime_manager
from app.main import create_app


def _client() -> TestClient:
    """创建独立 TestClient。"""

    return TestClient(create_app())


def _start_payload(match_id: str = "match_001", sheet_id: str = "sheet_01") -> dict:
    """构造 V2 单赛道 start 请求。"""

    return {
        "action": "start",
        "match_id": match_id,
        "sheet_id": sheet_id,
        "scene_type": "competition",
        "start_time": "2026-08-15T10:00:00+08:00",
        "teams": [{"team_id": "team_red", "team_name": "Red"}],
        "players": [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}],
    }


def test_health_and_site_resources() -> None:
    """健康检查和赛道资源查询应返回统一响应结构。"""

    client = _client()
    assert client.get("/health").json()["data"]["status"] == "ok"
    response = client.get("/api/v1/site/resources")
    assert response.status_code == 200
    sheets = response.json()["data"]["sheets"]
    assert len(sheets) == 6
    assert sheets[0]["live_status"] == "idle"
    assert sheets[0]["match_id"] is None
    assert sheets[0]["cameras"]


def test_v2_start_output_stop_history_edit_flow() -> None:
    """覆盖 V2：resources -> start -> output -> stop -> history -> edit/control -> status -> result。"""

    client = _client()
    response = client.post("/api/v1/match/control", json=_start_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["match_id"] == "match_001"
    assert data["sheet_id"] == "sheet_01"
    assert data["status"] == "running"
    assert data["media_url"]
    assert "outputs" not in data

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
    assert sheet_01["live_status"] == "running"
    assert sheet_01["match_id"] == "match_001"

    output = client.get("/api/v1/director/output", params={"match_id": "match_001"}).json()["data"]
    assert output["sheet_id"] == "sheet_01"
    assert output["media_url"] == data["media_url"]

    conflict = client.post("/api/v1/match/control", json=_start_payload("match_002", "sheet_01"))
    assert conflict.status_code == 400

    update = client.post(
        "/api/v1/match/control",
        json={"action": "update_config", "match_id": "match_001", "sheet_id": "sheet_01", "players": [{"player_id": "p2"}]},
    )
    assert update.status_code == 200
    bad_update = client.post(
        "/api/v1/match/control",
        json={"action": "update_config", "match_id": "match_001", "sheet_id": "sheet_03"},
    )
    assert bad_update.status_code == 400

    stop = client.post("/api/v1/match/control", json={"action": "stop", "match_id": "match_001"})
    assert stop.status_code == 200
    assert stop.json()["data"]["status"] == "completed"
    assert stop.json()["data"]["edit_status"] == "not_started"

    resources = client.get("/api/v1/site/resources").json()["data"]["sheets"]
    sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
    assert sheet_01["live_status"] == "idle"

    history = client.get("/api/v1/match/history").json()["data"]["records"]
    record = next(item for item in history if item["match_id"] == "match_001")
    assert record["record_status"] == "completed"
    assert record["edit_status"] == "not_started"

    status = client.get("/api/v1/edit/status", params={"match_id": "match_001"}).json()["data"]
    assert status["status"] == "not_started"
    assert status["progress"] == 0
    assert client.get("/api/v1/edit/result", params={"match_id": "match_001"}).json()["data"]["results"] == []

    edit = client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_001"})
    assert edit.status_code == 200
    assert edit.json()["data"]["status"] in {"processing", "completed"}
    # 重复 start 不应创建第二个任务或报错。
    assert client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_001"}).status_code == 200

    deadline = time.time() + 1
    final_status = None
    while time.time() < deadline:
        status = client.get("/api/v1/edit/status", params={"match_id": "match_001"}).json()["data"]
        final_status = status["status"]
        if final_status == "completed":
            break
        time.sleep(0.02)
    assert final_status == "completed"
    result = client.get("/api/v1/edit/result", params={"match_id": "match_001"}).json()["data"]
    assert result["status"] == "completed"
    assert result["results"]


def test_v2_error_cases() -> None:
    """覆盖不存在 match、重复 start、非法场景、缺 sheet、running 时剪辑等基础异常。"""

    client = _client()
    assert client.get("/api/v1/director/output", params={"match_id": "missing"}).status_code == 404
    assert client.post("/api/v1/edit/control", json={"action": "start", "match_id": "missing"}).status_code == 404

    response = client.post("/api/v1/match/control", json=_start_payload("dup_001"))
    assert response.status_code == 200
    assert client.post("/api/v1/match/control", json=_start_payload("dup_001", "sheet_02")).status_code == 400
    assert client.post("/api/v1/edit/control", json={"action": "start", "match_id": "dup_001"}).status_code == 400

    bad_scene = _start_payload("bad_scene")
    bad_scene["scene_type"] = "bad"
    assert client.post("/api/v1/match/control", json=bad_scene).status_code == 400

    missing_sheet = _start_payload("missing_sheet")
    missing_sheet.pop("sheet_id")
    assert client.post("/api/v1/match/control", json=missing_sheet).status_code == 400

    invalid_sheet = _start_payload("invalid_sheet", "sheet_99")
    assert client.post("/api/v1/match/control", json=invalid_sheet).status_code == 400

    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "dup_001"}).status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": "dup_001"}).status_code == 400


def test_overview_scene_returns_single_overview_live() -> None:
    """非竞赛场景实时阶段应返回唯一 overview_live。"""

    client = _client()
    payload = _start_payload("training_001")
    payload["scene_type"] = "personal_training"
    response = client.post("/api/v1/match/control", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sheet_id"] == "sheet_01"
    assert data["stream_type"] == "overview_live"


def test_match_id_cannot_be_reused_after_runtime_clear() -> None:
    """历史记录中已有的 match_id 即使 Runtime 清空后也不能再次 start。"""

    client = _client()
    match_id = "persist_match_001"
    assert client.post("/api/v1/match/control", json=_start_payload(match_id, "sheet_01")).status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}).status_code == 200

    # 模拟服务重启后的进程内状态丢失；SQLite match_records 仍应拦截重复 match_id。
    runtime_manager.clear()
    response = client.post("/api/v1/match/control", json=_start_payload(match_id, "sheet_02"))
    assert response.status_code == 400
    assert "match_id already exists" in response.json()["detail"]["message"]


def test_edit_control_restores_teams_players_after_runtime_clear() -> None:
    """stop 后清空 Runtime，再启动剪辑时应从 match_records 恢复 teams/players。"""

    client = _client()
    match_id = "restore_context_001"
    payload = _start_payload(match_id, "sheet_01")
    payload["teams"] = [{"team_id": "team_blue", "team_name": "Blue Team"}]
    payload["players"] = [{"player_id": "player_009", "player_name": "Bob", "team_id": "team_blue"}]
    assert client.post("/api/v1/match/control", json=payload).status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}).status_code == 200

    # edit/control 是重启后一段时间才触发的剪辑入口，因此这里先清空进程内 Runtime。
    runtime_manager.clear()
    edit = client.post("/api/v1/edit/control", json={"action": "start", "match_id": match_id})
    assert edit.status_code == 200
    restored = runtime_manager.get_match(match_id)
    assert restored.teams == payload["teams"]
    assert restored.players == payload["players"]

    deadline = time.time() + 1
    final_status = None
    while time.time() < deadline:
        status = client.get("/api/v1/edit/status", params={"match_id": match_id}).json()["data"]
        final_status = status["status"]
        if final_status == "completed":
            break
        time.sleep(0.02)
    assert final_status == "completed"

    result = client.get("/api/v1/edit/result", params={"match_id": match_id}).json()["data"]
    result_types = {item["result_type"] for item in result["results"]}
    assert "player_highlight" in result_types
    assert "team_highlight" in result_types

