"""Phase 6 Director Rule Replay。

脚本复用 Phase 5 Mock/Replay 链生成 ShotEventContext，再交给 DirectorService 输出 DirectorDecision 时间线。
不连接真实 WebSocket，不拉 RTSP，也不真正切换视频。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.stone.replay import JsonlReplaySource
from app.core.runtime import MatchRuntime, runtime_manager
from app.models.director import PreShotDirectorContext
from app.models.event import TriggerEvent
from app.models.shot import ShotEventContext
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService
from app.services.director_service import DirectorService
from app.services.stone_event_service import StoneEventService


ZONES = {
    "sheet_01": {
        "A": {"x_min": 0, "x_max": 2, "y_min": 0, "y_max": 2},
        "B": {"x_min": 8, "x_max": 10, "y_min": 8, "y_max": 10},
    }
}

FULL_CAMERAS_HOUSE_B = {
    "medium_shot": ["sheet_01_me_A", "sheet_01_me_B"],
    "close_shot": ["sheet_01_cl_A", "sheet_01_cl_B"],
    "house_top": ["sheet_01_house_B"],
}

FULL_CAMERAS_HOUSE_A = {
    "medium_shot": ["sheet_01_me_A", "sheet_01_me_B"],
    "close_shot": ["sheet_01_cl_A", "sheet_01_cl_B"],
    "house_top": ["sheet_01_house_A"],
}

NO_HOUSE_CAMERAS = {
    "medium_shot": ["sheet_01_me_A", "sheet_01_me_B"],
    "close_shot": ["sheet_01_cl_A", "sheet_01_cl_B"],
}


def register_match(match_id: str, available_camera_ids: dict[str, list[str]], director_service: DirectorService) -> None:
    """复用正式 DirectorService.start_sheet 初始化 Match，避免 Replay 预知未来方向。"""

    sheet = director_service.start_sheet(match_id, "sheet_01", available_camera_ids)
    runtime_manager.create_match(
        MatchRuntime(
            match_id=match_id,
            sheet_id="sheet_01",
            scene_type="competition",
            start_time="2026-08-21T10:00:00+08:00",
            sheets={"sheet_01": sheet},
        )
    )


def pre_shot_context(match_id: str, direction: str, source_end: str, target_end: str, timestamp: int = 900) -> PreShotDirectorContext:
    """人工构造 Phase 6 synthetic pre-shot event；不修改 Phase 5 Replay 数据。"""

    return PreShotDirectorContext(
        match_id=match_id,
        sheet_id="sheet_01",
        event_type="direction_locked",
        timestamp=timestamp,
        direction=direction,
        source_end=source_end,
        target_end=target_end,
        candidate_tag_id=None,
    )


def decision_summary(context: ShotEventContext | PreShotDirectorContext, decision) -> dict:
    """把 DirectorDecision 转为便于肉眼检查的时间线摘要。"""

    return {
        "timestamp": context.timestamp,
        "match_id": decision.match_id,
        "sheet_id": decision.sheet_id,
        "shot_id": decision.shot_id,
        "event_type": decision.event_type,
        "direction": decision.direction,
        "source_end": decision.source_end,
        "target_end": decision.target_end,
        "camera_id": decision.camera_id,
        "camera_role": decision.camera_role,
        "install_end": decision.install_end,
        "fallback_used": decision.fallback_used,
        "hold_previous": decision.hold_previous,
        "hold_duration_ms": decision.hold_duration_ms,
        "reason": decision.reason,
    }


def run_replay_case(
    name: str,
    match_id: str,
    path: str,
    available_camera_ids: dict[str, list[str]],
    *,
    direction: str,
    source_end: str,
    target_end: str,
) -> list[dict]:
    """执行一个 Phase 5 Replay，并输出 Phase 6 导播决策时间线。"""

    director_service = DirectorService()
    register_match(match_id, available_camera_ids, director_service)
    initial_camera_id = runtime_manager.get_match(match_id).sheets["sheet_01"].current_camera_id
    stone_service = StoneEventService(DirectionService(confirm_count=3, direction_zones_by_sheet=ZONES))
    timeline: list[dict] = []

    locked_context = pre_shot_context(match_id, direction, source_end, target_end)
    locked_decision = director_service.decide(locked_context)
    timeline.append(decision_summary(locked_context, locked_decision))

    for record in JsonlReplaySource(path).all_records():
        if isinstance(record.payload, TriggerEvent):
            context = stone_service.process_trigger_event(record.payload, match_id=match_id)
            if context is not None:
                decision = director_service.decide(context)
                timeline.append(decision_summary(context, decision))
        elif isinstance(record.payload, StonePosition):
            stone_service.process_position(record.payload, match_id=match_id)
    print()
    print(name)
    print(json.dumps({"initial_camera_id": initial_camera_id, "direction_locked_is_synthetic": True}, ensure_ascii=False))
    for item in timeline:
        print(json.dumps(item, ensure_ascii=False))
    runtime_manager.remove_match(match_id)
    return timeline


def run_unknown_case() -> None:
    """单独验证 UNKNOWN direction 不崩溃，并输出可解释 hold/fallback。"""

    match_id = "phase6_replay_unknown"
    director_service = DirectorService()
    register_match(match_id, FULL_CAMERAS_HOUSE_B, director_service)
    context = ShotEventContext(
        match_id=match_id,
        sheet_id="sheet_01",
        shot_id="phase6_replay_unknown_sheet_01_shot_0001",
        event_type="touch",
        timestamp=3000,
        shot_status=None,
        direction="UNKNOWN",
        source_end=None,
        target_end=None,
        quality_status=None,
    )
    decision = director_service.decide(context)
    print()
    print("UNKNOWN_DIRECTION")
    print(json.dumps({"initial_camera_id": runtime_manager.get_match(match_id).sheets["sheet_01"].current_camera_id}, ensure_ascii=False))
    print(json.dumps(decision_summary(context, decision), ensure_ascii=False))
    runtime_manager.remove_match(match_id)


def main() -> None:
    """输出 A_TO_B、B_TO_A、fallback 和 UNKNOWN 四类 DirectorDecision 时间线。"""

    runtime_manager.clear()
    run_replay_case(
        "A_TO_B_FULL",
        "phase6_replay_a",
        "data/mock/stone/phase5_A_to_B_complete.jsonl",
        FULL_CAMERAS_HOUSE_B,
        direction="A_TO_B",
        source_end="A",
        target_end="B",
    )
    run_replay_case(
        "B_TO_A_FULL_WITH_ALARM",
        "phase6_replay_b",
        "data/mock/stone/phase5_B_to_A_alarm.jsonl",
        FULL_CAMERAS_HOUSE_A,
        direction="B_TO_A",
        source_end="B",
        target_end="A",
    )
    run_replay_case(
        "A_TO_B_NO_HOUSE_FALLBACK",
        "phase6_replay_fallback",
        "data/mock/stone/phase5_A_to_B_complete.jsonl",
        NO_HOUSE_CAMERAS,
        direction="A_TO_B",
        source_end="A",
        target_end="B",
    )
    run_unknown_case()


if __name__ == "__main__":
    main()
