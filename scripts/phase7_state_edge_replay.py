"""Phase 7.3 Stone State Edge Replay。

使用真实协议形态的 fake type=4 JSON，经 Raw Parser 和 StoneStateEdgeDetector 输出协议边沿。
本脚本不处理 type=4 到业务事件的映射，不调用 Phase 5/6/7.2，也不连接真实 WebSocket。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.curling_raw import parse_raw_curling_message
from app.services.stone_state_edge_detector import StoneStateEdgeDetector


def raw_state(state: str, *, lane_id: str = "curlingLane1Data", tag_id: str = "stone0", h1=379, h2=0, total=379) -> str:
    """构造真实协议形态的 fake type=4 JSON 文本。"""

    return json.dumps(
        {
            "type": 4,
            "laneId": lane_id,
            "movingStoneTagId": tag_id,
            "stoneState": state,
            "hogLine1Timing": h1,
            "hogLine2Timing": h2,
            "totalTiming": total,
        },
        ensure_ascii=False,
    )


def summarize(edge) -> dict:
    """把 Edge 压缩成便于肉眼检查的 Replay 输出。"""

    if edge is None:
        return {"edge": "NO_EDGE"}
    return {
        "edge": edge.edge_type.value,
        "lane_id": edge.lane_id,
        "moving_stone_tag_id": edge.moving_stone_tag_id,
        "previous_state": edge.previous_state,
        "current_state": edge.current_state,
        "received_at_ms": edge.received_at_ms,
        "hog_line_1_timing": edge.hog_line_1_timing,
        "hog_line_2_timing": edge.hog_line_2_timing,
        "total_timing": edge.total_timing,
    }


def run_sequence(name: str, raw_messages: list[str], *, reset_after_first: bool = False) -> dict:
    """执行一组 type=4 Raw 消息，返回实际产生的协议 Edge。"""

    detector = StoneStateEdgeDetector()
    timeline = []
    for index, raw in enumerate(raw_messages):
        message = parse_raw_curling_message(raw)
        edge = detector.detect(message, received_at_ms=100_000 + index)
        timeline.append(summarize(edge))
        if reset_after_first and index == 0:
            detector.reset("curlingLane1Data", "stone0")
            timeline.append({"action": "reset", "lane_id": "curlingLane1Data", "moving_stone_tag_id": "stone0"})
    return {"scenario": name, "timeline": timeline, "edges": [item["edge"] for item in timeline if "edge" in item and item["edge"] != "NO_EDGE"]}


def main() -> None:
    """输出 Phase 7.3 六个核心 Replay 场景。"""

    rows = [
        run_sequence(
            "NORMAL",
            [raw_state(state) for state in ["start", "start", "start", "hogline1", "hogline1", "hogline2", "hogline2", "end", "end"]],
        ),
        run_sequence(
            "TIMING_UPDATE",
            [
                raw_state("hogline1", h1=379, h2=21, total=400),
                raw_state("hogline1", h1=379, h2=22, total=401),
                raw_state("hogline1", h1=379, h2=23, total=402),
            ],
        ),
        run_sequence("FORWARD_SKIP", [raw_state("start"), raw_state("hogline2", h2=100, total=479), raw_state("end", h2=100, total=500)]),
        run_sequence("BACKWARD", [raw_state("start"), raw_state("hogline1"), raw_state("hogline2"), raw_state("hogline1"), raw_state("hogline2")]),
        run_sequence("NEXT_CYCLE", [raw_state("start"), raw_state("end"), raw_state("start")]),
        run_sequence("RESET", [raw_state("hogline2"), raw_state("start")], reset_after_first=True),
    ]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))

    assert rows[0]["edges"] == ["start_entered", "hogline1_entered", "hogline2_entered", "end_entered"]
    assert rows[1]["edges"] == ["hogline1_entered"]
    assert rows[2]["edges"] == ["start_entered", "hogline2_entered", "end_entered"]
    assert rows[3]["edges"] == ["start_entered", "hogline1_entered", "hogline2_entered"]
    assert rows[4]["edges"] == ["start_entered", "end_entered", "start_entered"]
    assert rows[5]["edges"] == ["hogline2_entered", "start_entered"]


if __name__ == "__main__":
    main()
