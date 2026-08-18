"""软件接口 V2 Mock 闭环测试。"""

import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.runtime import runtime_manager
from app.main import create_app
from app.storage.database import init_db


def _client() -> TestClient:
    """创建独立 TestClient。"""

    return TestClient(create_app())


def _camera_config(sheet_id: str = "sheet_01") -> dict:
    """构造软件侧摄像头选择，只传 overview 逻辑 ID 和独立 house 摄像头。"""

    return {
        "overview_cameras": ["overview_A", "overview_B"],
        "house_cameras": [f"{sheet_id}_house_A", f"{sheet_id}_house_B"],
    }


def _start_payload(match_id: str = "match_001", sheet_id: str = "sheet_01") -> dict:
    """构造 V2 单赛道 start 请求。"""

    return {
        "action": "start",
        "match_id": match_id,
        "match_name": "8月18日冰壶联赛第一场",
        "description": "红队 vs 蓝队",
        "sheet_id": sheet_id,
        "scene_type": "competition",
        "start_time": "2026-08-18T10:00:00+08:00",
        "camera_config": _camera_config(sheet_id),
        "teams": [{"team_id": "team_red", "team_name": "Red"}],
        "players": [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}],
    }


def test_health_and_site_resources() -> None:
    """健康检查和赛道资源查询应返回软件侧逻辑镜头。"""

    client = _client()
    assert client.get("/health").json()["data"]["status"] == "ok"
    response = client.get("/api/v1/site/resources")
    assert response.status_code == 200
    sheets = response.json()["data"]["sheets"]
    assert len(sheets) == 6
    sheet_01 = next(item for item in sheets if item["sheet_id"] == "sheet_01")
    assert sheet_01["live_status"] == "idle"
    assert sheet_01["match_id"] is None
    camera_ids = {camera["camera_id"] for camera in sheet_01["cameras"]}
    assert camera_ids == {"overview_A", "overview_B", "sheet_01_house_A", "sheet_01_house_B"}
    assert "sheet_01_me_A" not in camera_ids
    assert "sheet_01_cl_B" not in camera_ids


def test_v2_start_output_stop_history_edit_flow() -> None:
    """覆盖 V2：resources -> start -> output -> update -> stop -> history -> edit/control -> status -> result。"""

    client = _client()
    response = client.post("/api/v1/match/control", json=_start_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["match_id"] == "match_001"
    assert data["sheet_id"] == "sheet_01"
    assert data["status"] == "running"
    assert data["media_url"]
    assert "outputs" not in data

    match = runtime_manager.get_match("match_001")
    assert match.match_name == "8月18日冰壶联赛第一场"
    assert match.description == "红队 vs 蓝队"
    sheet = match.sheets["sheet_01"]
    assert set(sheet.available_camera_ids) == {"medium_shot", "close_shot", "house_top"}
    assert sheet.available_camera_ids["medium_shot"] == ["sheet_01_me_A", "sheet_01_me_B"]
    assert sheet.available_camera_ids["close_shot"] == ["sheet_01_cl_A", "sheet_01_cl_B"]
    assert sheet.available_camera_ids["house_top"] == ["sheet_01_house_A", "sheet_01_house_B"]

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
        json={
            "action": "update_config",
            "match_id": "match_001",
            "sheet_id": "sheet_01",
            "match_name": "8月18日冰壶联赛更新场",
            "description": "红队 vs 黄队",
            "players": [{"player_id": "p2"}],
        },
    )
    assert update.status_code == 200
    match = runtime_manager.get_match("match_001")
    assert match.match_name == "8月18日冰壶联赛更新场"
    assert match.description == "红队 vs 黄队"
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
    assert record["match_name"] == "8月18日冰壶联赛更新场"
    assert record["description"] == "红队 vs 黄队"
    assert record["record_status"] == "completed"
    assert record["edit_status"] == "not_started"

    status = client.get("/api/v1/edit/status", params={"match_id": "match_001"}).json()["data"]
    assert status["status"] == "not_started"
    assert status["progress"] == 0
    assert client.get("/api/v1/edit/result", params={"match_id": "match_001"}).json()["data"]["results"] == []

    edit = client.post("/api/v1/edit/control", json={"action": "start", "match_id": "match_001"})
    assert edit.status_code == 200
    assert edit.json()["data"]["status"] in {"processing", "completed"}
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
    """覆盖不存在 match、重复 start、非法场景、缺 sheet、非法摄像头等基础异常。"""

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

    missing_name = _start_payload("missing_name")
    missing_name.pop("match_name")
    assert client.post("/api/v1/match/control", json=missing_name).status_code == 400

    empty_name = _start_payload("empty_name")
    empty_name["match_name"] = "   "
    assert client.post("/api/v1/match/control", json=empty_name).status_code == 400

    missing_sheet = _start_payload("missing_sheet")
    missing_sheet.pop("sheet_id")
    assert client.post("/api/v1/match/control", json=missing_sheet).status_code == 400

    invalid_sheet = _start_payload("invalid_sheet", "sheet_99")
    assert client.post("/api/v1/match/control", json=invalid_sheet).status_code == 400

    invalid_overview = _start_payload("invalid_overview")
    invalid_overview["camera_config"]["overview_cameras"] = ["overview_C"]
    assert client.post("/api/v1/match/control", json=invalid_overview).status_code == 400

    cross_sheet_house = _start_payload("cross_sheet_house")
    cross_sheet_house["camera_config"]["house_cameras"] = ["sheet_02_house_A"]
    assert client.post("/api/v1/match/control", json=cross_sheet_house).status_code == 400

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


def test_edit_control_restores_match_context_after_runtime_clear() -> None:
    """stop 后清空 Runtime，再启动剪辑时应从 match_records 恢复元数据和 teams/players。"""

    client = _client()
    match_id = "restore_context_001"
    payload = _start_payload(match_id, "sheet_01")
    payload["match_name"] = "恢复测试比赛"
    payload["description"] = "恢复测试说明"
    payload["teams"] = [{"team_id": "team_blue", "team_name": "Blue Team"}]
    payload["players"] = [{"player_id": "player_009", "player_name": "Bob", "team_id": "team_blue"}]
    assert client.post("/api/v1/match/control", json=payload).status_code == 200
    assert client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}).status_code == 200

    # edit/control 是重启后一段时间才触发的剪辑入口，因此这里先清空进程内 Runtime。
    runtime_manager.clear()
    edit = client.post("/api/v1/edit/control", json={"action": "start", "match_id": match_id})
    assert edit.status_code == 200
    restored = runtime_manager.get_match(match_id)
    assert restored.match_name == "恢复测试比赛"
    assert restored.description == "恢复测试说明"
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


def test_old_match_records_database_is_migrated(tmp_path: Path) -> None:
    """旧公网 SQLite 已有 match_records 时，init_db 应自动补 match_name/description 列。"""

    db_path = tmp_path / "old.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE match_records (
                match_id TEXT PRIMARY KEY,
                sheet_id TEXT NOT NULL,
                scene_type TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                record_status TEXT NOT NULL,
                edit_status TEXT NOT NULL,
                media_url TEXT,
                record_url TEXT,
                teams_json TEXT,
                players_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    init_db(str(db_path))
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(match_records)")}
    assert {"match_name", "description", "teams_json", "players_json"}.issubset(columns)
