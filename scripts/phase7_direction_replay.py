"""Phase 7.2 Ready Zone 预投方向 Replay。

使用 TEST ONLY fake Ready Zone，验证 type=3 定位点能在出手前锁定方向并交给 Phase 6.6 Director。
不连接真实 WebSocket，不处理 type=4，不创建 Shot，也不真正切视频。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.stone.position_adapter import TrajectoryPositionAdapter
from app.core.config import ConfigManager, Settings
from app.core.runtime import MatchRuntime, runtime_manager
from app.models.curling_raw import TrajectoryRawMessage, parse_raw_curling_message
from app.services.director_service import DirectorService
from app.services.position_cache import PositionCache
from app.services.pre_shot_direction_service import PreShotDirectionService

NOW_MS = 10_000
A_POINTS = [(2.0, 2.0), (2.1, 2.1), (2.2, 2.2)]
B_POINTS = [(8.0, 8.0), (8.1, 8.1), (8.2, 8.2)]
OUTSIDE_POINTS = [(5.5, 5.5), (5.6, 5.6), (5.7, 5.7)]


def fake_manager() -> ConfigManager:
    """构造 TEST ONLY Ready Zone 标定；正式 site_config 不写入推测坐标。"""

    site_config = {
        "site_id": "phase72_replay",
        "sheets": [{"sheet_id": "sheet_01", "enabled": True, "position_lane_id": "curlingLane1Data"}],
        "lane_mappings": [{"lane_id": "curlingLane1Data", "sheet_id": "sheet_01"}],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}}],
        "calibration": {
            "position": [
                {
                    "sheet_id": "sheet_01",
                    "enabled": True,
                    "position_lane_id": "curlingLane1Data",
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
    return ConfigManager(Settings(site_config=site_config))


def raw_type3(tag_id: str, source_time: int, x: float, y: float) -> TrajectoryRawMessage:
    """构造真实协议形态的 fake type=3 消息。"""

    message = parse_raw_curling_message(json.dumps({
        "type": 3,
        "laneId": "curlingLane1Data",
        "trajectoryData": {"laneId": "curlingLane1Data", "tagId": tag_id, "time": source_time, "x": x, "y": y},
    }))
    if not isinstance(message, TrajectoryRawMessage):
        raise AssertionError(f"unexpected raw message: {message}")
    return message


def add_points(
    cache: PositionCache,
    adapter: TrajectoryPositionAdapter,
    tag_id: str,
    points: list[tuple[float, float]],
    *,
    received_at_ms: int | list[int] = NOW_MS,
    source_start: int = 1000,
) -> None:
    """把 fake type=3 消息经 PositionAdapter 写入 PositionCache。"""

    for index, (x, y) in enumerate(points):
        received = received_at_ms[index] if isinstance(received_at_ms, list) else received_at_ms
        for position in adapter.convert(raw_type3(tag_id, source_start + index, x, y)):
            cache.add(position, received_at_ms=received)


def register_match(match_id: str, director: DirectorService) -> None:
    """复用正式 DirectorService.start_sheet 初始化镜头，不根据未来方向预置 current_camera。"""

    available = {
        "medium_shot": ["sheet_01_me_A", "sheet_01_me_B"],
        "close_shot": ["sheet_01_cl_A", "sheet_01_cl_B"],
        "house_top": ["sheet_01_house_B"],
    }
    sheet = director.start_sheet(match_id, "sheet_01", available)
    runtime_manager.create_match(
        MatchRuntime(
            match_id=match_id,
            sheet_id="sheet_01",
            scene_type="competition",
            start_time="2026-08-26T10:00:00+08:00",
            sheets={"sheet_01": sheet},
        )
    )


def summarize_context(context) -> dict:
    """把方向上下文压缩成 Replay 输出。"""

    if context is None:
        return {"lock": "NO_LOCK"}
    return {
        "lock": "LOCKED",
        "event_type": context.event_type,
        "direction": context.direction,
        "source_end": context.source_end,
        "target_end": context.target_end,
        "candidate_tag_id": context.candidate_tag_id,
        "timestamp": context.timestamp,
    }


def run_lock_case(name: str, tag_id: str, points: list[tuple[float, float]], *, expected_install_end: str) -> dict:
    """执行一个会锁定方向并进入 Director 的场景。"""

    cache = PositionCache(max_size=20)
    manager = fake_manager()
    adapter = TrajectoryPositionAdapter(manager)
    direction = PreShotDirectionService(cache, manager, position_freshness_ms=1000, direction_confirm_count=3)
    add_points(cache, adapter, tag_id, points)
    context = direction.evaluate(name.lower(), "sheet_01", tag_id, now_ms=NOW_MS)
    director = DirectorService()
    register_match(name.lower(), director)
    decision = director.decide(context) if context is not None else None
    runtime_manager.remove_match(name.lower())
    return {
        "scenario": name,
        "context": summarize_context(context),
        "director": None if decision is None else {
            "camera_id": decision.camera_id,
            "camera_role": decision.camera_role,
            "install_end": decision.install_end,
            "reason": decision.reason,
        },
        "expected_install_end": expected_install_end,
    }


def run_no_lock_case(name: str, points: list[tuple[float, float]], *, received_at_ms: int | list[int] = NOW_MS) -> dict:
    """执行不应锁定方向的场景。"""

    cache = PositionCache(max_size=20)
    manager = fake_manager()
    adapter = TrajectoryPositionAdapter(manager)
    direction = PreShotDirectionService(cache, manager, position_freshness_ms=1000, direction_confirm_count=3)
    add_points(cache, adapter, "stone0", points, received_at_ms=received_at_ms)
    context = direction.evaluate(name.lower(), "sheet_01", "stone0", now_ms=NOW_MS)
    return {"scenario": name, "context": summarize_context(context)}


def run_lock_state_case() -> list[dict]:
    """验证 already locked、other tag cannot take over、reset next throw 三个状态场景。"""

    cache = PositionCache(max_size=20)
    manager = fake_manager()
    adapter = TrajectoryPositionAdapter(manager)
    direction = PreShotDirectionService(cache, manager, position_freshness_ms=1000, direction_confirm_count=3)
    match_id = "phase72_lock_state"

    add_points(cache, adapter, "stone0", A_POINTS)
    first = direction.evaluate(match_id, "sheet_01", "stone0", now_ms=NOW_MS)
    add_points(cache, adapter, "stone0", [(2.3, 2.3), (2.4, 2.4), (2.5, 2.5)], source_start=2000)
    repeated = direction.evaluate(match_id, "sheet_01", "stone0", now_ms=NOW_MS)
    add_points(cache, adapter, "stone5", B_POINTS, source_start=3000)
    other_tag = direction.evaluate(match_id, "sheet_01", "stone5", now_ms=NOW_MS)
    direction.reset(match_id, "sheet_01")
    reset_lock = direction.evaluate(match_id, "sheet_01", "stone5", now_ms=NOW_MS)
    return [
        {"scenario": "ALREADY_LOCKED", "first": summarize_context(first), "second": summarize_context(repeated)},
        {"scenario": "OTHER_TAG_CANNOT_TAKE_OVER", "context": summarize_context(other_tag)},
        {"scenario": "RESET_NEXT_THROW", "context": summarize_context(reset_lock)},
    ]


def main() -> None:
    """输出 Phase 7.2 八个核心 Replay 场景。"""

    runtime_manager.clear()
    rows = [
        run_lock_case("A_TO_B_LOCK", "stone0", A_POINTS, expected_install_end="B"),
        run_lock_case("B_TO_A_LOCK", "stone5", B_POINTS, expected_install_end="A"),
        run_no_lock_case("INSUFFICIENT_POINTS", A_POINTS[:2]),
        run_no_lock_case("STALE_POINTS", A_POINTS, received_at_ms=[NOW_MS, NOW_MS, NOW_MS - 2000]),
        run_no_lock_case("INCONSISTENT_POINTS", [A_POINTS[0], OUTSIDE_POINTS[0], A_POINTS[2]]),
    ]
    rows.extend(run_lock_state_case())
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))

    assert rows[0]["context"]["direction"] == "A_TO_B" and rows[0]["director"]["install_end"] == "B"
    assert rows[1]["context"]["direction"] == "B_TO_A" and rows[1]["director"]["install_end"] == "A"
    assert rows[2]["context"]["lock"] == "NO_LOCK"
    assert rows[3]["context"]["lock"] == "NO_LOCK"
    assert rows[4]["context"]["lock"] == "NO_LOCK"
    assert rows[5]["second"]["lock"] == "NO_LOCK"
    assert rows[6]["context"]["lock"] == "NO_LOCK"
    assert rows[7]["context"]["direction"] == "B_TO_A"


if __name__ == "__main__":
    main()
