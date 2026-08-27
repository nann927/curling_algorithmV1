"""Phase 7.5 Shot 方向协调 Replay。

脚本使用临时 SQLite，演示 Position direction_locked 与 State movingStoneTagId 在 departure
时对齐，并验证 stop 后释放 Pre-shot Lock；不连接真实 WebSocket、不调用 Director、不切视频。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


TEMP_DB = Path(tempfile.gettempdir()) / "curling_phase75_replay.sqlite"
os.environ["CURLING_SQLITE_PATH"] = str(TEMP_DB)

from app.core.config import ConfigManager, Settings, get_config_manager, get_settings
from app.core.enums import RuntimeStatus
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.curling_state_edge import StoneStateEdge, StoneStateEdgeType
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService
from app.services.position_cache import PositionCache
from app.services.pre_shot_direction_service import PreShotDirectionService
from app.services.shot_direction_coordination_service import ShotDirectionCoordinationService
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_event_bridge import StoneStateEventBridge
from app.storage.shot_repository import ShotRepository

NOW_MS = 10_000
A_POINT = (2.0, 2.0)
B_POINT = (8.0, 8.0)


def site_config() -> dict:
    """Replay 专用 fake site_config，明确区分 position lane 和 state lane。"""

    return {
        "site_id": "phase75_replay",
        "sheets": [
            {"sheet_id": "sheet_01", "enabled": True, "trigger_lane_id": "state_lane_01", "position_lane_id": "position_lane_01"},
        ],
        "lane_mappings": [{"lane_id": "position_lane_01", "sheet_id": "sheet_01"}],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}}],
        "calibration": {
            "position": [
                {
                    "sheet_id": "sheet_01",
                    "enabled": True,
                    "position_lane_id": "position_lane_01",
                    "lane_bounds": {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
                    "ready_zones": {
                        "A": {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0, "y_max": 3.0},
                        "B": {"x_min": 7.0, "x_max": 10.0, "y_min": 7.0, "y_max": 10.0},
                    },
                    "hoglines": {"A": {"y": 3.5}, "B": {"y": 6.5}},
                }
            ]
        },
    }


def components() -> tuple[ShotDirectionCoordinationService, PreShotDirectionService, PositionCache]:
    """创建 Replay 使用的一组共享服务。"""

    manager = ConfigManager(Settings(site_config=site_config()))
    cache = PositionCache(max_size=10)
    pre_shot = PreShotDirectionService(cache, manager, position_freshness_ms=1000, direction_confirm_count=3)
    direction = DirectionService(config_manager=manager)
    stone_service = StoneEventService(direction_service=direction)
    bridge = StoneStateEventBridge(manager, runtime_manager, stone_service)
    return ShotDirectionCoordinationService(
        pre_shot_direction_service=pre_shot,
        direction_service=direction,
        stone_event_service=stone_service,
        bridge=bridge,
    ), pre_shot, cache


def register_match(match_id: str) -> None:
    """注册 running match，模拟软件 start 后状态。"""

    sheet = SheetRuntime(sheet_id="sheet_01", enabled=True, stream_type="smart_director", media_url="mock://live")
    runtime_manager.create_match(MatchRuntime(match_id=match_id, sheet_id="sheet_01", scene_type="competition", start_time="2026-08-27T10:00:00+08:00", status=RuntimeStatus.RUNNING.value, sheets={"sheet_01": sheet}))


def edge(edge_type: StoneStateEdgeType, tag_id: str, timestamp: int) -> StoneStateEdge:
    """构造 State Edge，模拟 Phase 7.3 输出。"""

    state_by_edge = {
        StoneStateEdgeType.START_ENTERED: "start",
        StoneStateEdgeType.HOGLINE1_ENTERED: "hogline1",
        StoneStateEdgeType.HOGLINE2_ENTERED: "hogline2",
        StoneStateEdgeType.END_ENTERED: "end",
    }
    return StoneStateEdge(edge_type=edge_type, lane_id="state_lane_01", moving_stone_tag_id=tag_id, previous_state=None, current_state=state_by_edge[edge_type], received_at_ms=timestamp)


def lock_direction(pre_shot: PreShotDirectionService, cache: PositionCache, match_id: str, tag_id: str, end: str) -> dict:
    """通过 PositionCache + PreShotDirectionService 生成真实 direction_locked。"""

    point = A_POINT if end == "A" else B_POINT
    for index in range(3):
        cache.add(StonePosition(sheet_id="sheet_01", lane_id="position_lane_01", tag_id=tag_id, timestamp=5000 + index, x=point[0] + index * 0.1, y=point[1] + index * 0.1), received_at_ms=NOW_MS)
    context = pre_shot.evaluate(match_id, "sheet_01", tag_id, now_ms=NOW_MS)
    assert context is not None
    return context.model_dump()


def result_row(result) -> dict:
    """把协调结果压缩成 replay 输出。"""

    if result is None:
        return {"event": None}
    context = result.shot_context
    return {
        "event": result.semantic_event.event_type,
        "alignment": result.alignment_status.value,
        "candidate_tag_id": result.candidate_tag_id,
        "moving_stone_tag_id": result.moving_stone_tag_id,
        "resolved_direction": result.resolved_direction,
        "shot_direction": None if context is None else context.direction,
        "shot_status": None if context is None else context.shot_status,
    }


def run_chain(coordinator: ShotDirectionCoordinationService, tag_id: str, start_ts: int = 1000) -> list[dict]:
    """执行完整 State 链路。"""

    return [
        result_row(coordinator.process(edge(StoneStateEdgeType.START_ENTERED, tag_id, start_ts))),
        result_row(coordinator.process(edge(StoneStateEdgeType.HOGLINE1_ENTERED, tag_id, start_ts + 100))),
        result_row(coordinator.process(edge(StoneStateEdgeType.HOGLINE2_ENTERED, tag_id, start_ts + 200))),
        result_row(coordinator.process(edge(StoneStateEdgeType.END_ENTERED, tag_id, start_ts + 300))),
    ]


def shot_summary(match_id: str) -> dict:
    """读取该 match 最新 Shot 摘要。"""

    shots = ShotRepository().list_by_match(match_id)
    if not shots:
        return {"shot": "NONE"}
    shot = shots[-1]
    return {"shot_id": shot.shot_id, "direction": shot.direction, "source_end": shot.source_end, "target_end": shot.target_end, "status": shot.status, "quality_status": shot.quality_status, "abnormal_reason": shot.abnormal_reason}


def scenario_matched_a_to_b() -> None:
    """MATCHED_A_TO_B：candidate stone0 与 moving stone0 对齐。"""

    runtime_manager.clear()
    coordinator, pre_shot, cache = components()
    register_match("matched_a")
    lock = lock_direction(pre_shot, cache, "matched_a", "stone0", "A")
    rows = run_chain(coordinator, "stone0")
    print(json.dumps({"scenario": "MATCHED_A_TO_B", "direction_locked": lock, "timeline": rows, "shot": shot_summary("matched_a"), "lock_after_stop": pre_shot.get_lock("matched_a", "sheet_01") is not None}, ensure_ascii=False))


def scenario_matched_b_to_a() -> None:
    """MATCHED_B_TO_A：candidate stone5 与 moving stone5 对齐。"""

    runtime_manager.clear()
    coordinator, pre_shot, cache = components()
    register_match("matched_b")
    lock = lock_direction(pre_shot, cache, "matched_b", "stone5", "B")
    rows = run_chain(coordinator, "stone5")
    print(json.dumps({"scenario": "MATCHED_B_TO_A", "direction_locked": lock, "timeline": rows, "shot": shot_summary("matched_b"), "lock_after_stop": pre_shot.get_lock("matched_b", "sheet_01") is not None}, ensure_ascii=False))


def scenario_no_pre_shot_lock() -> None:
    """NO_PRE_SHOT_LOCK：没有 Position 预锁，Shot 仍完成但方向 UNKNOWN。"""

    runtime_manager.clear()
    coordinator, pre_shot, _ = components()
    register_match("no_lock")
    rows = run_chain(coordinator, "stone0")
    print(json.dumps({"scenario": "NO_PRE_SHOT_LOCK", "timeline": rows, "shot": shot_summary("no_lock"), "lock_after_stop": pre_shot.get_lock("no_lock", "sheet_01") is not None}, ensure_ascii=False))


def scenario_candidate_mismatch() -> None:
    """CANDIDATE_MISMATCH：candidate stone0 不能继承给 moving stone5。"""

    runtime_manager.clear()
    coordinator, pre_shot, cache = components()
    register_match("mismatch")
    lock = lock_direction(pre_shot, cache, "mismatch", "stone0", "A")
    rows = run_chain(coordinator, "stone5")
    print(json.dumps({"scenario": "CANDIDATE_MISMATCH", "direction_locked": lock, "timeline": rows, "shot": shot_summary("mismatch"), "lock_after_stop": pre_shot.get_lock("mismatch", "sheet_01") is not None}, ensure_ascii=False))


def scenario_late_direction() -> None:
    """LATE_DIRECTION：departure 后晚到方向不能修改当前 Shot。"""

    runtime_manager.clear()
    coordinator, pre_shot, cache = components()
    register_match("late_direction")
    rows = [result_row(coordinator.process(edge(StoneStateEdgeType.START_ENTERED, "stone0", 1000)))]
    lock = lock_direction(pre_shot, cache, "late_direction", "stone0", "A")
    rows.extend([
        result_row(coordinator.process(edge(StoneStateEdgeType.HOGLINE1_ENTERED, "stone0", 1100))),
        result_row(coordinator.process(edge(StoneStateEdgeType.HOGLINE2_ENTERED, "stone0", 1200))),
        result_row(coordinator.process(edge(StoneStateEdgeType.END_ENTERED, "stone0", 1300))),
    ])
    print(json.dumps({"scenario": "LATE_DIRECTION", "late_direction_locked": lock, "timeline": rows, "shot": shot_summary("late_direction"), "lock_after_stop": pre_shot.get_lock("late_direction", "sheet_01") is not None}, ensure_ascii=False))


def scenario_stop_without_active_shot() -> None:
    """STOP_WITHOUT_ACTIVE_SHOT：缺 start 时 stop 仍释放 stale lock。"""

    runtime_manager.clear()
    coordinator, pre_shot, cache = components()
    register_match("stop_only")
    lock = lock_direction(pre_shot, cache, "stop_only", "stone0", "A")
    row = result_row(coordinator.process(edge(StoneStateEdgeType.END_ENTERED, "stone0", 1300)))
    print(json.dumps({"scenario": "STOP_WITHOUT_ACTIVE_SHOT", "direction_locked": lock, "timeline": [row], "shot": shot_summary("stop_only"), "lock_after_stop": pre_shot.get_lock("stop_only", "sheet_01") is not None}, ensure_ascii=False))


def scenario_next_throw() -> None:
    """NEXT_THROW：第一投 stop 后第二投可重新锁定反向方向。"""

    runtime_manager.clear()
    coordinator, pre_shot, cache = components()
    register_match("next_throw")
    first_lock = lock_direction(pre_shot, cache, "next_throw", "stone0", "A")
    first = run_chain(coordinator, "stone0", 1000)
    second_lock = lock_direction(pre_shot, cache, "next_throw", "stone5", "B")
    second = run_chain(coordinator, "stone5", 2000)
    print(json.dumps({"scenario": "NEXT_THROW", "first_direction_locked": first_lock, "first_timeline": first, "second_direction_locked": second_lock, "second_timeline": second, "latest_shot": shot_summary("next_throw")}, ensure_ascii=False))


def main() -> None:
    """执行全部 Phase 7.5 replay 场景。"""

    if TEMP_DB.exists():
        TEMP_DB.unlink()
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    scenario_matched_a_to_b()
    scenario_matched_b_to_a()
    scenario_no_pre_shot_lock()
    scenario_candidate_mismatch()
    scenario_late_direction()
    scenario_stop_without_active_shot()
    scenario_next_throw()
    print(json.dumps({"temp_sqlite_path": str(TEMP_DB)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
