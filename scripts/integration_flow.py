"""PC 后端 Integration/Mock 联调流程脚本。

该脚本只调用正式 IF-01～IF-04，不依赖任何内部调试接口。
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


def main() -> None:
    """执行 health → start → output → update → stop → status → result 完整流程。"""

    match_id = os.getenv("MATCH_ID", f"match_integration_{int(time.time())}")
    with httpx.Client(base_url=BASE_URL, timeout=10.0, trust_env=False) as client:
        require_success("health", client.get("/health"))

        start_payload = {
            "action": "start",
            "match_id": match_id,
            "scene_type": "competition",
            "start_time": "2026-08-11T10:00:00+08:00",
            "teams": [{"team_id": "team_red", "team_name": "Red"}],
            "players": [{"player_id": "player_001", "player_name": "Alice", "team_id": "team_red"}],
            "camera_config": {
                "overview_cameras": ["overview_A"],
                "sheets": [
                    {"sheet_id": "sheet_01", "house_camera_ends": ["A", "B"]},
                    {"sheet_id": "sheet_02", "house_camera_ends": ["A", "B"]},
                ],
            },
        }
        require_success("start", client.post("/api/v1/match/control", json=start_payload))
        require_success("director/output after start", client.get("/api/v1/director/output", params={"match_id": match_id}))

        update_payload = {
            "action": "update_config",
            "match_id": match_id,
            "camera_config": {
                "overview_cameras": ["overview_A"],
                "sheets": [
                    {"sheet_id": "sheet_01", "house_camera_ends": ["A", "B"]},
                    {"sheet_id": "sheet_03", "house_camera_ends": ["A", "B"]},
                ],
            },
        }
        require_success("update_config", client.post("/api/v1/match/control", json=update_payload))
        require_success("director/output after update", client.get("/api/v1/director/output", params={"match_id": match_id}))
        require_success("stop", client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}))

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
