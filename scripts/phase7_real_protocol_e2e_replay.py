"""Phase 7.6 真实协议 Raw JSON E2E Replay。

Replay 从 fake Raw JSON 文本进入 CurlingRealtimeOrchestrator，验证 Parser、Position、State、
Shot、Director 的主链路；不连接真实 WebSocket、不切视频、不启动软件 V2 API。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

TEMP_DB = Path(tempfile.gettempdir()) / "curling_phase76_real_protocol_replay.sqlite"
if TEMP_DB.exists():
    TEMP_DB.unlink()
os.environ["CURLING_SQLITE_PATH"] = str(TEMP_DB)

from app.core.config import get_config_manager, get_settings
from app.core.runtime import runtime_manager
from app.storage.shot_repository import ShotRepository
from tests.test_phase7_real_protocol_e2e import (  # noqa: E402
    A_POINTS,
    B_POINTS,
    _full_state_chain,
    _lock_from_positions,
    _orchestrator,
    _raw_position,
    _register_match,
    _state,
)


def reset() -> None:
    """清空 Replay 进程状态，确保每个场景互不污染。"""

    runtime_manager.clear()
    get_settings.cache_clear()
    get_config_manager.cache_clear()


def shot_row(match_id: str) -> dict:
    """读取某个 match 的第一投持久化摘要。"""

    shots = ShotRepository().list_by_match(match_id)
    if not shots:
        return {"match_id": match_id, "shot": None}
    shot = shots[0]
    return {
        "match_id": match_id,
        "shot_id": shot.shot_id,
        "direction": shot.direction,
        "source_end": shot.source_end,
        "target_end": shot.target_end,
        "touch_time": shot.touch_time,
        "status": shot.status,
        "quality_status": shot.quality_status,
        "abnormal_reason": shot.abnormal_reason,
    }


def decision_ids(results) -> list[str | None]:
    """提取 DirectorDecision camera_id 序列。"""

    return [item.director_decisions[0].camera_id if item.director_decisions else None for item in results]


def run_matched_a_to_b() -> dict:
    """A_TO_B 完整真实协议链路。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_a_to_b", manager, director)
    lock = _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    states = _full_state_chain(orchestrator, "state_lane_01", "stone0")
    assert decision_ids(states) == ["sheet_01_cl_B", "sheet_01_me_B", "sheet_01_house_B", "sheet_01_cl_A"]
    return {"scenario": "MATCHED_A_TO_B_FULL", "lock_camera": lock.director_decisions[0].camera_id, "state_cameras": decision_ids(states), **shot_row("replay_a_to_b")}


def run_matched_b_to_a() -> dict:
    """B_TO_A 完整真实协议链路。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_b_to_a", manager, director)
    lock = _lock_from_positions(orchestrator, "position_lane_01", "stone5", B_POINTS)
    states = _full_state_chain(orchestrator, "state_lane_01", "stone5")
    assert decision_ids(states) == ["sheet_01_cl_A", "sheet_01_me_A", "sheet_01_house_A", "sheet_01_cl_B"]
    return {"scenario": "MATCHED_B_TO_A_FULL", "lock_camera": lock.director_decisions[0].camera_id, "state_cameras": decision_ids(states), **shot_row("replay_b_to_a")}


def run_no_direction_lock() -> dict:
    """无预锁时 UNKNOWN 但生命周期完整。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_no_lock", manager, director)
    states = _full_state_chain(orchestrator, "state_lane_01", "stone0")
    assert states[0].coordination_result.alignment_status == "NO_PRE_SHOT_LOCK"
    row = shot_row("replay_no_lock")
    assert row["direction"] == "UNKNOWN"
    assert row["quality_status"] == "complete"
    return {"scenario": "NO_DIRECTION_LOCK", "alignment": states[0].coordination_result.alignment_status, "state_cameras": decision_ids(states), **row}


def run_candidate_mismatch() -> dict:
    """candidate mismatch 不继承任何方向。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_mismatch", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    states = _full_state_chain(orchestrator, "state_lane_01", "stone9")
    assert states[0].coordination_result.alignment_status == "CANDIDATE_MISMATCH"
    row = shot_row("replay_mismatch")
    assert row["direction"] == "UNKNOWN"
    return {"scenario": "CANDIDATE_MISMATCH", "alignment": states[0].coordination_result.alignment_status, "state_cameras": decision_ids(states), **row}


def run_duplicate_state() -> dict:
    """重复 type=4 状态只产生首次 Edge。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_duplicate", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    states = ["start", "start", "hogline1", "hogline1", "hogline2", "hogline2", "end", "end"]
    results = [_state(orchestrator, "state_lane_01", "stone0", state, 5000 + index) for index, state in enumerate(states)]
    emitted = [item.shot_context.event_type for item in results if item.shot_context is not None]
    assert emitted == ["departure", "magnetic_1", "magnetic_2", "stop"]
    return {"scenario": "DUPLICATE_STATE", "emitted_events": emitted, "ignored_count": len([item for item in results if item.ignored_reason == "no_state_edge"]), **shot_row("replay_duplicate")}


def run_missing_hogline2() -> dict:
    """缺 hogline2 不自动 house。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_missing_h2", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    results = [_state(orchestrator, "state_lane_01", "stone0", "start", 6000), _state(orchestrator, "state_lane_01", "stone0", "hogline1", 6100)]
    assert "house_top" not in [decision.camera_role for result in results for decision in result.director_decisions]
    return {"scenario": "MISSING_HOGLINE2", "state_cameras": decision_ids(results), "finished_shots": len(ShotRepository().list_by_match("replay_missing_h2"))}


def run_missing_stop() -> dict:
    """缺 stop 不自动完成，也不回 source close。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_missing_stop", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    results = [_state(orchestrator, "state_lane_01", "stone0", "start", 7000), _state(orchestrator, "state_lane_01", "stone0", "hogline1", 7100), _state(orchestrator, "state_lane_01", "stone0", "hogline2", 7200)]
    current = orchestrator.stone_event_service.get_current_shot("replay_missing_stop", "sheet_01")
    assert current is not None
    return {"scenario": "MISSING_STOP", "state_cameras": decision_ids(results), "current_status": current.status, "finished_shots": len(ShotRepository().list_by_match("replay_missing_stop"))}


def run_late_position_after_departure() -> dict:
    """departure 后 type=3 继续缓存但不触发预投导演决策。"""

    reset()
    orchestrator, manager, director, cache = _orchestrator()
    _register_match("replay_late_position", manager, director)
    _state(orchestrator, "state_lane_01", "stone0", "start", 8000)
    for index, (x, y) in enumerate(A_POINTS):
        result = orchestrator.process_raw_text(_raw_position("position_lane_01", "stone0", 8100 + index, x, y), received_at_ms=8200 + index)[0]
    assert result.ignored_reason == "active_shot_pre_shot_window_closed"
    assert cache.get_latest("sheet_01", "stone0") is not None
    return {"scenario": "LATE_POSITION_AFTER_DEPARTURE", "ignored_reason": result.ignored_reason, "cached": cache.get_latest("sheet_01", "stone0") is not None}


def run_next_throw_relock() -> dict:
    """stop 后下一投重新打开预投窗口。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_next_throw", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    _full_state_chain(orchestrator, "state_lane_01", "stone0")
    lock = _lock_from_positions(orchestrator, "position_lane_01", "stone5", B_POINTS, start_time=9000)
    assert lock.pre_shot_contexts[0].direction == "B_TO_A"
    return {"scenario": "NEXT_THROW_RELOCK", "next_direction": lock.pre_shot_contexts[0].direction, "next_camera": lock.director_decisions[0].camera_id}


def run_multi_sheet_isolation() -> dict:
    """同一编排器下多赛道隔离。"""

    reset()
    orchestrator, manager, director, _ = _orchestrator()
    _register_match("replay_sheet_01", manager, director, "sheet_01")
    _register_match("replay_sheet_02", manager, director, "sheet_02")
    lock_01 = _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    lock_02 = _lock_from_positions(orchestrator, "position_lane_02", "stone5", B_POINTS)
    start_01 = _state(orchestrator, "state_lane_01", "stone0", "start", 10_000)
    start_02 = _state(orchestrator, "state_lane_02", "stone5", "start", 10_010)
    assert start_01.shot_context.match_id == "replay_sheet_01"
    assert start_02.shot_context.match_id == "replay_sheet_02"
    return {"scenario": "MULTI_SHEET_ISOLATION", "directions": [lock_01.pre_shot_contexts[0].direction, lock_02.pre_shot_contexts[0].direction], "cameras": [start_01.director_decisions[0].camera_id, start_02.director_decisions[0].camera_id]}


def run_ignored_protocol_messages() -> list[dict]:
    """type=12 与 type=1/type=2 均不控制业务生命周期。"""

    reset()
    orchestrator, _, _, _ = _orchestrator()
    payloads = [
        ("TYPE12_IGNORED", {"type": 12, "data": {}}),
        ("TYPE1_TYPE2_DO_NOT_CONTROL_MATCH", {"type": 1, "laneId": "state_lane_01"}),
        ("TYPE1_TYPE2_DO_NOT_CONTROL_MATCH", {"type": 2, "laneId": "state_lane_01"}),
    ]
    rows = []
    for name, payload in payloads:
        result = orchestrator.process_raw_text(json.dumps(payload))[0]
        rows.append({"scenario": name, "raw_type": payload["type"], "ignored_reason": result.ignored_reason, "running_matches": len(runtime_manager.list_matches())})
    assert all(row["running_matches"] == 0 for row in rows)
    return rows


def main() -> None:
    """执行所有 Phase 7.6 Replay 场景。"""

    rows = [
        run_matched_a_to_b(),
        run_matched_b_to_a(),
        run_no_direction_lock(),
        run_candidate_mismatch(),
        run_duplicate_state(),
        run_missing_hogline2(),
        run_missing_stop(),
        run_late_position_after_departure(),
        run_next_throw_relock(),
        run_multi_sheet_isolation(),
    ]
    rows.extend(run_ignored_protocol_messages())
    print(json.dumps({"phase": "7.6", "status": "passed", "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
