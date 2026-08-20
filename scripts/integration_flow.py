"""PC 后端 Integration/Mock V2 联调流程脚本。

该脚本只调用正式接口，不依赖任何内部调试接口。
"""

import json
import os
import time
from pathlib import Path

import httpx


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
CONFIG_PATH = Path(os.getenv("INTEGRATION_MOCK_PATH", "config/integration_mock.json"))


def dump(name: str, response: httpx.Response) -> dict | None:
    """打印 HTTP 状态和 JSON/原始响应，避免 JSONDecodeError 丢失诊断信息。"""

    print(f"\n{name} {response.status_code}")
    try:
        data = response.json()
    except json.JSONDecodeError:
        print(response.text or "<empty response body>")
        return None
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def require_success(name: str, response: httpx.Response) -> dict:
    """关键步骤必须成功，否则停止流程并给出失败步骤。"""

    data = dump(name, response)
    if response.status_code != 200 or data is None or data.get("code") != 0:
        raise SystemExit(f"{name} failed, status={response.status_code}")
    return data


def require_failure(name: str, response: httpx.Response) -> None:
    """确认冲突或非法请求被拒绝。"""

    dump(name, response)
    if response.status_code < 400:
        raise SystemExit(f"{name} should fail, status={response.status_code}")


def expected_sheet_media(sheet_id: str) -> dict:
    """从 integration_mock.json 读取期望媒体地址，避免在 Python 中硬编码 RTSP。"""

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return config.get("sheet_media", {}).get(sheet_id, {})


def assert_sheet_01_camera_choices(sheet: dict) -> None:
    """确认资源接口只暴露软件侧可选 camera_id，不暴露 me/cl 内部镜头。"""

    camera_ids = {camera["camera_id"] for camera in sheet["cameras"]}
    expected = {"overview_A", "overview_B", "sheet_01_house_A", "sheet_01_house_B"}
    if camera_ids != expected:
        raise SystemExit(f"sheet_01 camera choices wrong, got={sorted(camera_ids)}")
    forbidden = {"sheet_01_me_A", "sheet_01_cl_A", "sheet_01_me_B", "sheet_01_cl_B"}
    if camera_ids & forbidden:
        raise SystemExit(f"internal cameras should not be exposed, got={sorted(camera_ids & forbidden)}")


def main() -> None:
    """执行 V2 resources → start → stop → history → edit/control → result 完整流程。"""

    match_id = os.getenv("MATCH_ID", f"match_integration_{int(time.time())}")
    conflict_match_id = f"{match_id}_conflict"
    start_name = "8月18日冰壶联赛第一场"
    updated_name = "8月18日冰壶联赛更新场"
    updated_description = "红队 vs 黄队"
    sheet_01_media = expected_sheet_media("sheet_01")
    with httpx.Client(base_url=BASE_URL, timeout=10.0, trust_env=False) as client:
        require_success("health", client.get("/health"))

        resources = require_success("site/resources before start", client.get("/api/v1/site/resources"))["data"]["sheets"]
        if len(resources) != 6:
            raise SystemExit(f"expected 6 sheets, got {len(resources)}")
        sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
        if sheet_01["live_status"] != "idle":
            raise SystemExit(f"sheet_01 should be idle, got {sheet_01['live_status']}")
        if sheet_01_media.get("preview_url") and sheet_01["preview_url"] != sheet_01_media["preview_url"]:
            raise SystemExit("sheet_01 preview_url does not match integration_mock.json")
        assert_sheet_01_camera_choices(sheet_01)

        start_payload = {
            "action": "start",
            "match_id": match_id,
            "match_name": start_name,
            "description": "红队 vs 蓝队",
            "sheet_id": "sheet_01",
            "scene_type": "competition",
            "start_time": "2026-08-18T10:00:00+08:00",
            "camera_config": {
                "overview_cameras": ["overview_A", "overview_B"],
                "house_cameras": ["sheet_01_house_A", "sheet_01_house_B"],
            },
            "teams": [{"team_id": "team_red", "team_name": "Red"}],
            "players": [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}],
        }
        start = require_success("start", client.post("/api/v1/match/control", json=start_payload))["data"]
        if sheet_01_media.get("media_url") and start["media_url"] != sheet_01_media["media_url"]:
            raise SystemExit("sheet_01 media_url does not match integration_mock.json")
        if sheet_01["preview_url"] == start["media_url"]:
            raise SystemExit("sheet_01 preview_url and media_url should differ in current integration config")

        resources = require_success("site/resources after start", client.get("/api/v1/site/resources"))["data"]["sheets"]
        sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
        if sheet_01["live_status"] != "running" or sheet_01["match_id"] != match_id:
            raise SystemExit("sheet_01 running state is wrong")

        output = require_success("director/output", client.get("/api/v1/director/output", params={"match_id": match_id}))["data"]
        if output["sheet_id"] != "sheet_01" or output["media_url"] != start["media_url"]:
            raise SystemExit("director/output media_url is invalid")

        conflict_payload = dict(start_payload)
        conflict_payload["match_id"] = conflict_match_id
        require_failure("start conflict same sheet", client.post("/api/v1/match/control", json=conflict_payload))

        require_success(
            "update_config",
            client.post(
                "/api/v1/match/control",
                json={
                    "action": "update_config",
                    "match_id": match_id,
                    "sheet_id": "sheet_01",
                    "match_name": updated_name,
                    "description": updated_description,
                    "players": [{"player_id": "player_002"}],
                },
            ),
        )
        require_failure(
            "update_config change sheet",
            client.post("/api/v1/match/control", json={"action": "update_config", "match_id": match_id, "sheet_id": "sheet_03"}),
        )

        require_success("stop", client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}))

        resources = require_success("site/resources after stop", client.get("/api/v1/site/resources"))["data"]["sheets"]
        sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
        if sheet_01["live_status"] != "idle":
            raise SystemExit("sheet_01 should be idle after stop")

        history = require_success("match/history", client.get("/api/v1/match/history"))["data"]["records"]
        record = next((item for item in history if item["match_id"] == match_id), None)
        if record is None or record["record_status"] != "completed" or record["edit_status"] != "not_started":
            raise SystemExit("history record is invalid")
        if record["match_name"] != updated_name or record["description"] != updated_description:
            raise SystemExit("history match metadata is invalid")

        status = require_success("edit/status before control", client.get("/api/v1/edit/status", params={"match_id": match_id}))["data"]
        if status["status"] != "not_started":
            raise SystemExit("edit should be not_started before edit/control")

        require_success("edit/control", client.post("/api/v1/edit/control", json={"action": "start", "match_id": match_id}))

        final_status = None
        for _ in range(30):
            data = require_success("edit/status", client.get("/api/v1/edit/status", params={"match_id": match_id}))
            final_status = data["data"]["status"]
            if final_status == "completed":
                break
            time.sleep(0.5)
        if final_status != "completed":
            raise SystemExit(f"edit/status did not complete, last_status={final_status}")

        result = require_success("edit/result", client.get("/api/v1/edit/result", params={"match_id": match_id}))["data"]
        for item in result["results"]:
            if "duration_seconds" not in item or not isinstance(item["duration_seconds"], (int, float)) or item["duration_seconds"] <= 0:
                raise SystemExit(f"invalid duration_seconds in edit/result: {item}")


if __name__ == "__main__":
    main()
