"""Phase 7.1 Position Cache Replay。

使用 Phase 7.0 Raw Parser 解析 fake type=3 JSON，再经 PositionAdapter 写入 PositionCache。
不连接真实 WebSocket，不输出方向，也不调用 Director。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.stone.position_adapter import TrajectoryPositionAdapter
from app.models.curling_raw import parse_raw_curling_message
from app.services.position_cache import PositionCache

RAW_MESSAGES = [
    {
        "type": 3,
        "laneId": "curlingLane1Data",
        "trajectoryData": {"laneId": "curlingLane1Data", "tagId": "stone0", "time": 1786078169550, "x": 2.376, "y": 6.268},
    },
    {
        "type": 3,
        "laneId": "curlingLane1Data",
        "trajectoryData": {"laneId": "curlingLane1Data", "tagId": "stone0", "time": 1786078169650, "x": 2.476, "y": 6.468},
    },
    {
        "type": 3,
        "laneId": "curlingLane1Data",
        "trajectoryData": {"laneId": "curlingLane1Data", "tagId": "stone1", "time": 1786078169750, "x": 3.100, "y": 6.900},
    },
    {
        "type": 3,
        "laneId": "curlingLane2Data",
        "trajectoryData": {"laneId": "curlingLane2Data", "tagId": "stone0", "time": 1786078169850, "x": 1.500, "y": 5.500},
    },
]


def main() -> None:
    """展示 Raw type=3 -> PositionAdapter -> PositionCache 的最小链路。"""

    adapter = TrajectoryPositionAdapter()
    cache = PositionCache(max_size=20)
    for raw in RAW_MESSAGES:
        message = parse_raw_curling_message(json.dumps(raw))
        adapter.add_to_cache(message, cache)

    for sheet_id, tag_id in [("sheet_01", "stone0"), ("sheet_01", "stone1"), ("sheet_02", "stone0")]:
        latest = cache.get_latest(sheet_id, tag_id)
        recent = cache.get_recent(sheet_id, tag_id)
        print(json.dumps({
            "sheet_id": sheet_id,
            "tag_id": tag_id,
            "latest": None if latest is None else {
                "lane_id": latest.position.lane_id,
                "source_time": latest.position.timestamp,
                "x": latest.position.x,
                "y": latest.position.y,
                "received_at_ms": latest.received_at_ms,
            },
            "recent_count": len(recent),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
