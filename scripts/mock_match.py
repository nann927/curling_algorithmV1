"""手工联调脚本。

需要先启动服务，然后执行本脚本验证 V2 start/update/output/stop/edit/control 全链路。
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

    # 默认使用时间戳 match_id，避免重复执行脚本时触发跨重启唯一性校验。
    match_id = os.getenv("MATCH_ID", f"match_{int(time.time())}")
    with httpx.Client(base_url=BASE_URL, timeout=5.0, trust_env=False) as client:
        require_success("health", client.get("/health"))
        require_success("site/resources", client.get("/api/v1/site/resources"))

        start_payload = {
            "action": "start",
            "match_id": match_id,
            "match_name": "手工联调比赛",
            "description": "手工脚本验证",
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
        require_success("start", client.post("/api/v1/match/control", json=start_payload))

        update_payload = {
            "action": "update_config",
            "match_id": match_id,
            "sheet_id": "sheet_01",
            "match_name": "手工联调比赛-更新",
            "description": "手工脚本更新说明",
            "players": [{"player_id": "player_002"}],
        }
        require_success("update_config", client.post("/api/v1/match/control", json=update_payload))
        require_success("director/output", client.get("/api/v1/director/output", params={"match_id": match_id}))
        require_success("stop", client.post("/api/v1/match/control", json={"action": "stop", "match_id": match_id}))
        require_success("match/history", client.get("/api/v1/match/history"))
        require_success("edit/control", client.post("/api/v1/edit/control", json={"action": "start", "match_id": match_id}))

        for _ in range(20):
            status = client.get("/api/v1/edit/status", params={"match_id": match_id})
            data = require_success("edit/status", status)
            if data["data"]["status"] == "completed":
                break
            time.sleep(0.5)

        require_success("edit/result", client.get("/api/v1/edit/result", params={"match_id": match_id}))


if __name__ == "__main__":
    main()
