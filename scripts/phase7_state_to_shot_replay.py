"""Phase 7.4 State Edge 到 Shot 生命周期 Replay。

使用 fake Raw type=4 JSON 经过 Parser、Phase 7.3 EdgeDetector、Phase 7.4 Bridge，最终进入
现有 Phase 5 StoneEventService。脚本使用临时 SQLite，不污染 data/db/curling.db。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import ConfigManager, Settings, get_config_manager, get_settings
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.curling_raw import parse_raw_curling_message
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_edge_detector import StoneStateEdgeDetector
from app.services.stone_state_event_bridge import StoneStateEventBridge
from app.storage.shot_repository import ShotRepository


def configure_temp_sqlite() -> str:
    """为 Replay 分配临时 SQLite，避免污染正式历史库。"""

    path = str(Path(tempfile.gettempdir()) / "curling_phase74_replay.sqlite")
    if Path(path).exists():
        Path(path).unlink()
    os.environ["CURLING_SQLITE_PATH"] = path
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    return path


def fake_manager() -> ConfigManager:
    """构造 TEST ONLY State/Trigger lane 配置。"""

    return ConfigManager(Settings(site_config={
        "site_id": "phase74_replay",
        "sheets": [{"sheet_id": "sheet_01", "enabled": True, "trigger_lane_id": "state_lane_01", "position_lane_id": "position_lane_01"}],
        "lane_mappings": [{"lane_id": "position_lane_01", "sheet_id": "sheet_01"}],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}}],
    }))


def register_match(match_id: str = "match_phase74", sheet_id: str = "sheet_01") -> None:
    """模拟软件 V2 /match/control start 后的 running MatchRuntime。"""

    sheet = SheetRuntime(sheet_id=sheet_id, enabled=True, stream_type="smart_director", media_url="mock://live")
    runtime_manager.create_match(MatchRuntime(match_id=match_id, sheet_id=sheet_id, scene_type="competition", start_time="2026-08-26T10:00:00+08:00", sheets={sheet_id: sheet}))


def raw_state(state: str, *, lane_id: str = "state_lane_01", tag_id: str = "stone0", h1=379, h2=0, total=379) -> str:
    """构造真实协议形态 fake type=4 JSON。"""

    return json.dumps({
        "type": 4,
        "laneId": lane_id,
        "movingStoneTagId": tag_id,
        "stoneState": state,
        "hogLine1Timing": h1,
        "hogLine2Timing": h2,
        "totalTiming": total,
    }, ensure_ascii=False)


def shot_status(match_id: str, service: StoneEventService) -> dict:
    """输出当前 Shot 或最终持久化 Shot 摘要。"""

    current = service.get_current_shot(match_id, "sheet_01")
    if current is not None:
        return {"shot_id": current.shot_id, "status": current.status, "quality_status": current.quality_status, "touch_time": current.touch_time}
    records = ShotRepository().list_by_match(match_id)
    if records:
        shot = records[-1]
        return {
            "shot_id": shot.shot_id,
            "status": shot.status,
            "quality_status": shot.quality_status,
            "touch_time": shot.touch_time,
            "departure_time": shot.departure_time,
            "first_magnetic_time": shot.first_magnetic_time,
            "second_magnetic_time": shot.second_magnetic_time,
            "stop_time": shot.stop_time,
            "direction": shot.direction,
            "abnormal_reason": shot.abnormal_reason,
        }
    return {"shot": "NONE"}


def run_messages(name: str, raw_messages: list[str], *, register: bool = True, match_id: str = "match_phase74") -> dict:
    """执行一组 Raw type=4 消息并返回 Edge/Event/Shot 时间线。"""

    runtime_manager.clear()
    if register:
        register_match(match_id)
    detector = StoneStateEdgeDetector()
    service = StoneEventService()
    bridge = StoneStateEventBridge(fake_manager(), runtime_manager, service)
    timeline = []
    for index, raw in enumerate(raw_messages):
        message = parse_raw_curling_message(raw)
        state = getattr(message, "stone_state", None)
        edge = detector.detect(message, received_at_ms=10_000 + index)
        if edge is None:
            timeline.append({"raw_state": state, "edge": "NO_EDGE", "event": None, "shot": shot_status(match_id, service)})
            continue
        semantic = bridge.convert(edge)
        context = None if semantic is None else bridge.dispatch(semantic)
        timeline.append({
            "raw_state": state,
            "edge": edge.edge_type.value,
            "event": None if semantic is None else semantic.event_type,
            "shot_context": None if context is None else {"event_type": context.event_type, "shot_status": context.shot_status},
            "shot": shot_status(match_id, service),
        })
    return {"scenario": name, "timeline": timeline}


def main() -> None:
    """输出 Phase 7.4 五个核心 Replay 场景。"""

    sqlite_path = configure_temp_sqlite()
    rows = [
        run_messages("NORMAL", [raw_state(state, h2=index, total=400 + index) for index, state in enumerate(["start", "start", "hogline1", "hogline1", "hogline2", "end", "end"])]),
        run_messages("NO_RUNNING_MATCH", [raw_state("start")], register=False, match_id="match_no_running"),
        run_messages("UNKNOWN_LANE", [raw_state("start", lane_id="unknown_state_lane")]),
        run_messages("FORWARD_SKIP", [raw_state("start"), raw_state("hogline2", h2=100, total=479), raw_state("end", h2=100, total=500)], match_id="match_skip"),
        run_messages("NO_ACTIVE_SHOT", [raw_state("hogline1")], match_id="match_no_active"),
    ]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    print(json.dumps({"temp_sqlite_path": sqlite_path}, ensure_ascii=False))

    normal_events = [item["event"] for item in rows[0]["timeline"]]
    assert normal_events == ["departure", None, "magnetic_1", None, "magnetic_2", "stop", None]
    assert rows[0]["timeline"][-2]["shot"]["status"] == "FINISHED"
    assert rows[0]["timeline"][-2]["shot"]["touch_time"] is None
    assert rows[1]["timeline"][0]["event"] is None
    assert rows[2]["timeline"][0]["event"] is None
    assert [item["event"] for item in rows[3]["timeline"]] == ["departure", "magnetic_2", "stop"]
    assert rows[4]["timeline"][0]["event"] == "magnetic_1"
    assert rows[4]["timeline"][0]["shot"] == {"shot": "NONE"}


if __name__ == "__main__":
    main()
