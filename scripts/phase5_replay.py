"""Phase 5 Shot Replay 验证脚本。

脚本只回放 Mock Trigger/Position，不连接真实电子冰壶、摄像头或融合服务器。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.stone.replay import JsonlReplaySource
from app.models.event import TriggerEvent
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService
from app.services.stone_event_service import StoneEventService
from app.storage.shot_repository import ShotRepository


ZONES = {
    "sheet_01": {
        "A": {"x_min": 0, "x_max": 2, "y_min": 0, "y_max": 2},
        "B": {"x_min": 8, "x_max": 10, "y_min": 8, "y_max": 10},
    }
}


def run_case(match_id: str, path: str) -> dict:
    """执行一个 Replay case 并返回 SQLite 中的 Shot 摘要。"""

    service = StoneEventService(DirectionService(confirm_count=3, direction_zones_by_sheet=ZONES))
    last_shot_id = None
    for record in JsonlReplaySource(path).all_records():
        if isinstance(record.payload, TriggerEvent):
            context = service.process_trigger_event(record.payload, match_id=match_id)
            if context is not None:
                last_shot_id = context.shot_id
        elif isinstance(record.payload, StonePosition):
            service.process_position(record.payload, match_id=match_id)
    if last_shot_id is None:
        raise RuntimeError(f"replay did not produce shot_id: {path}")
    shot = ShotRepository().get(last_shot_id)
    if shot is None:
        raise RuntimeError(f"shot not found in sqlite: {last_shot_id}")
    return shot.model_dump()


def main() -> None:
    """输出 A_TO_B 和 B_TO_A 两个 Replay 的最终 Shot 与 SQLite 验证结果。"""

    for match_id, path in [
        ("phase5_replay_a", "data/mock/stone/phase5_A_to_B_complete.jsonl"),
        ("phase5_replay_b", "data/mock/stone/phase5_B_to_A_alarm.jsonl"),
    ]:
        shot = run_case(match_id, path)
        print(json.dumps(shot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

