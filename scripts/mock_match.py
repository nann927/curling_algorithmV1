"""手工联调脚本。

需要先启动服务，然后执行本脚本验证 start/update/output/stop/status/result 全链路。
"""

import json
import os
import time

import httpx


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def dump(name: str, response: httpx.Response) -> dict | None:
    """格式化打印 HTTP 响应，便于联调观察。"""

    print(f"\n{name} {response.status_code}")
    try:
        data = response.json()
    except json.JSONDecodeError:
        print(response.text or "<empty response body>")
        return None
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def require_success(name: str, response: httpx.Response) -> dict:
    """关键步骤必须成功；失败时打印诊断并终止脚本。"""

    data = dump(name, response)
    if response.status_code != 200 or data is None or data.get("code") != 0:
        raise SystemExit(f"{name} failed, status={response.status_code}")
    return data


def main() -> None:
    """按固定顺序调用软件平台接口。"""

    # 默认使用时间戳 match_id，避免重复执行脚本时触发重复 start。
    match_id = os.getenv("MATCH_ID", f"match_{int(time.time())}")
    # trust_env=False 可避免 Windows/IDE 环境变量中的 HTTP_PROXY 影响本地 localhost 调用。
    with httpx.Client(base_url=BASE_URL, timeout=5.0, trust_env=False) as client:
        require_success("health", client.get("/health"))

        start_payload = {
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
        require_success("start", client.post("/api/v1/match/control", json=start_payload))

        update_payload = {
            "action": "update_config",
            "match_id": match_id,
            "camera_config": {
                "overview_cameras": ["overview_B"],
                "sheets": [
                    {"sheet_id": "sheet_01", "house_camera_ends": ["A", "B"]},
                    {"sheet_id": "sheet_03", "house_camera_ends": ["B"]},
                ],
            },
        }
        require_success("update_config", client.post("/api/v1/match/control", json=update_payload))
        require_success("director/output", client.get("/api/v1/director/output", params={"match_id": match_id}))
        require_success("stop", client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}))

        for _ in range(20):
            status = client.get("/api/v1/edit/status", params={"match_id": match_id})
            data = require_success("edit/status", status)
            if data["data"]["status"] == "completed":
                break
            # Phase 2 Mock 处理很快；真实剪辑接入后可加长轮询间隔。
            time.sleep(0.1)

        require_success("edit/result", client.get("/api/v1/edit/result", params={"match_id": match_id}))


if __name__ == "__main__":
    main()
