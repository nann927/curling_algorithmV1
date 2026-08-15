"""PC 后端 Integration/Mock V2 联调流程脚本。

该脚本只调用正式接口，不依赖任何内部调试接口。
"""

import json
import os
import time

import httpx


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


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


def main() -> None:
    """执行 V2 resources → start → stop → history → edit/control → result 完整流程。"""

    match_id = os.getenv("MATCH_ID", f"match_integration_{int(time.time())}")
    conflict_match_id = f"{match_id}_conflict"
    with httpx.Client(base_url=BASE_URL, timeout=10.0, trust_env=False) as client:
        require_success("health", client.get("/health"))

        resources = require_success("site/resources before start", client.get("/api/v1/site/resources"))["data"]["sheets"]
        if len(resources) != 6:
            raise SystemExit(f"expected 6 sheets, got {len(resources)}")
        sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
        if sheet_01["live_status"] != "idle":
            raise SystemExit(f"sheet_01 should be idle, got {sheet_01['live_status']}")

        start_payload = {
            "action": "start",
            "match_id": match_id,
            "sheet_id": "sheet_01",
            "scene_type": "competition",
            "start_time": "2026-08-15T10:00:00+08:00",
            "teams": [{"team_id": "team_red", "team_name": "Red"}],
            "players": [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}],
        }
        require_success("start", client.post("/api/v1/match/control", json=start_payload))

        resources = require_success("site/resources after start", client.get("/api/v1/site/resources"))["data"]["sheets"]
        sheet_01 = next(item for item in resources if item["sheet_id"] == "sheet_01")
        if sheet_01["live_status"] != "running" or sheet_01["match_id"] != match_id:
            raise SystemExit("sheet_01 running state is wrong")

        output = require_success("director/output", client.get("/api/v1/director/output", params={"match_id": match_id}))["data"]
        if output["sheet_id"] != "sheet_01" or not output["media_url"]:
            raise SystemExit("director/output media_url is invalid")

        conflict_payload = dict(start_payload)
        conflict_payload["match_id"] = conflict_match_id
        require_failure("start conflict same sheet", client.post("/api/v1/match/control", json=conflict_payload))

        require_success(
            "update_config",
            client.post(
                "/api/v1/match/control",
                json={"action": "update_config", "match_id": match_id, "sheet_id": "sheet_01", "players": [{"player_id": "player_002"}]},
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

        require_success("edit/result", client.get("/api/v1/edit/result", params={"match_id": match_id}))


if __name__ == "__main__":
    main()
