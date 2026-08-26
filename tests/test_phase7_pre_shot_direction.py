"""Phase 7.2 Ready Zone 预投方向锁定测试。

本文件中的坐标全部是 TEST ONLY fake calibration，不代表真实现场标定。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.stone.position_adapter import TrajectoryPositionAdapter
from app.core.config import ConfigManager, Settings
from app.core.runtime import MatchRuntime, runtime_manager
from app.models.curling_raw import FullDataRawMessage, StoneStateRawMessage, TrajectoryRawMessage, parse_raw_curling_message
from app.models.director import PreShotDirectorContext
from app.models.stone import StonePosition
from app.services.director_service import DirectorService
from app.services.position_cache import PositionCache
from app.services.pre_shot_direction_service import PreShotDirectionService


A_POINT = (2.0, 2.0)
B_POINT = (8.0, 8.0)
OUTSIDE_POINT = (5.5, 5.5)
NOW_MS = 10_000


def _site_config(*, enabled: bool = True, ready_zones: dict | None = None, sheet_ids: list[str] | None = None) -> dict:
    """构造 TEST ONLY 现场配置，Ready Zone 坐标只服务单元测试。"""

    sheet_ids = sheet_ids or ["sheet_01", "sheet_02"]
    ready_zones = ready_zones if ready_zones is not None else {
        "A": {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0, "y_max": 3.0},
        "B": {"x_min": 7.0, "x_max": 10.0, "y_min": 7.0, "y_max": 10.0},
    }
    return {
        "site_id": "phase72_test",
        "sheets": [
            {"sheet_id": sheet_id, "enabled": True, "position_lane_id": f"fake_lane_{index:02d}"}
            for index, sheet_id in enumerate(sheet_ids, start=1)
        ],
        "lane_mappings": [
            {"lane_id": f"fake_lane_{index:02d}", "sheet_id": sheet_id}
            for index, sheet_id in enumerate(sheet_ids, start=1)
        ],
        "cameras": [
            {"camera_id": "sheet_01_me_A", "camera_role": "medium_shot", "sheet_id": "sheet_01", "install_end": "A", "source_provider": "local_file", "source_config": {}},
            {"camera_id": "sheet_01_me_B", "camera_role": "medium_shot", "sheet_id": "sheet_01", "install_end": "B", "source_provider": "local_file", "source_config": {}},
            {"camera_id": "sheet_01_cl_A", "camera_role": "close_shot", "sheet_id": "sheet_01", "install_end": "A", "source_provider": "local_file", "source_config": {}},
            {"camera_id": "sheet_01_cl_B", "camera_role": "close_shot", "sheet_id": "sheet_01", "install_end": "B", "source_provider": "local_file", "source_config": {}},
            {"camera_id": "sheet_01_house_A", "camera_role": "house_top", "sheet_id": "sheet_01", "install_end": "A", "source_provider": "local_file", "source_config": {}},
            {"camera_id": "sheet_01_house_B", "camera_role": "house_top", "sheet_id": "sheet_01", "install_end": "B", "source_provider": "local_file", "source_config": {}},
        ],
        "calibration": {
            "position": [
                {
                    "sheet_id": sheet_id,
                    "enabled": enabled,
                    "position_lane_id": f"fake_lane_{index:02d}",
                    "lane_bounds": {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
                    "ready_zones": ready_zones,
                    "hoglines": {"A": {"y": 3.5}, "B": {"y": 6.5}},
                }
                for index, sheet_id in enumerate(sheet_ids, start=1)
            ]
        },
    }


def _manager(*, enabled: bool = True, ready_zones: dict | None = None, sheet_ids: list[str] | None = None) -> ConfigManager:
    """创建隔离 ConfigManager，避免依赖正式 site_config 的未标定坐标。"""

    return ConfigManager(Settings(site_config=_site_config(enabled=enabled, ready_zones=ready_zones, sheet_ids=sheet_ids)))


def _service(
    cache: PositionCache,
    *,
    enabled: bool = True,
    ready_zones: dict | None = None,
    confirm_count: int = 3,
    freshness_ms: int = 1000,
    sheet_ids: list[str] | None = None,
) -> PreShotDirectionService:
    """创建可控配置的 PreShotDirectionService。"""

    return PreShotDirectionService(
        cache,
        _manager(enabled=enabled, ready_zones=ready_zones, sheet_ids=sheet_ids),
        position_freshness_ms=freshness_ms,
        direction_confirm_count=confirm_count,
    )


def _add_points(
    cache: PositionCache,
    points: list[tuple[float, float]],
    *,
    sheet_id: str = "sheet_01",
    lane_id: str = "fake_lane_01",
    tag_id: str = "stone0",
    received_at_ms: int | list[int] = NOW_MS,
    source_start: int = 1000,
) -> None:
    """向 PositionCache 写入连续测试点，timestamp 和 received_at_ms 保持显式可控。"""

    for index, (x, y) in enumerate(points):
        if isinstance(received_at_ms, list):
            received = received_at_ms[index]
        else:
            received = received_at_ms
        cache.add(
            StonePosition(sheet_id=sheet_id, lane_id=lane_id, tag_id=tag_id, timestamp=source_start + index, x=x, y=y),
            received_at_ms=received,
        )


def _evaluate(points: list[tuple[float, float]], *, tag_id: str = "stone0", **kwargs) -> PreShotDirectorContext | None:
    """写入一组点后执行一次 evaluate，简化常规用例。"""

    cache = PositionCache(max_size=10)
    _add_points(cache, points, tag_id=tag_id, received_at_ms=kwargs.pop("received_at_ms", NOW_MS), source_start=kwargs.pop("source_start", 1000))
    service = _service(cache, **kwargs)
    return service.evaluate("match_phase72", "sheet_01", tag_id, now_ms=NOW_MS)


def test_calibration_disabled_returns_none() -> None:
    """未启用现场标定时不得猜测方向。"""

    assert _evaluate([A_POINT, A_POINT, A_POINT], enabled=False) is None


@pytest.mark.parametrize("zone_name", ["A", "B"])
def test_ready_zone_none_does_not_lock(zone_name: str) -> None:
    """A/B Ready Zone 为 None 时，该端不可用于方向判断。"""

    zones = {
        "A": None if zone_name == "A" else {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0, "y_max": 3.0},
        "B": None if zone_name == "B" else {"x_min": 7.0, "x_max": 10.0, "y_min": 7.0, "y_max": 10.0},
    }
    points = [A_POINT, A_POINT, A_POINT] if zone_name == "A" else [B_POINT, B_POINT, B_POINT]
    assert _evaluate(points, ready_zones=zones) is None


def test_incomplete_zone_fields_do_not_lock() -> None:
    """Ready Zone 缺少任意边界字段都不能被解释成无界范围。"""

    zones = {"A": {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0}, "B": None}
    assert _evaluate([A_POINT, A_POINT, A_POINT], ready_zones=zones) is None


def test_insufficient_points_return_none() -> None:
    """不足 confirm_count 个最近点时不锁定方向。"""

    assert _evaluate([A_POINT, A_POINT]) is None


def test_consecutive_fresh_a_points_lock_a_to_b() -> None:
    """连续 fresh A Ready Zone 点锁定 A_TO_B，并记录 source/target/candidate。"""

    context = _evaluate([A_POINT, (2.1, 2.1), (2.2, 2.2)], tag_id="stone_a")
    assert context is not None
    assert context.event_type == "direction_locked"
    assert context.direction == "A_TO_B"
    assert context.source_end == "A"
    assert context.target_end == "B"
    assert context.candidate_tag_id == "stone_a"


def test_consecutive_fresh_b_points_lock_b_to_a() -> None:
    """连续 fresh B Ready Zone 点锁定 B_TO_A，并记录 source/target。"""

    context = _evaluate([B_POINT, (8.1, 8.1), (8.2, 8.2)])
    assert context is not None
    assert context.direction == "B_TO_A"
    assert context.source_end == "B"
    assert context.target_end == "A"


@pytest.mark.parametrize(
    "points",
    [
        [A_POINT, A_POINT, OUTSIDE_POINT],
        [A_POINT, OUTSIDE_POINT, A_POINT],
        [B_POINT, B_POINT, OUTSIDE_POINT],
        [A_POINT, B_POINT, A_POINT],
    ],
)
def test_inconsistent_recent_window_does_not_lock(points: list[tuple[float, float]]) -> None:
    """最近窗口中存在 outside 或 A/B 混杂时不锁定。"""

    assert _evaluate(points) is None


def test_stale_point_prevents_lock() -> None:
    """最近 N 个点必须全部 fresh，任意 stale 都不锁定。"""

    context = _evaluate([A_POINT, (2.1, 2.1), (2.2, 2.2)], received_at_ms=[NOW_MS, NOW_MS, NOW_MS - 2000])
    assert context is None


def test_freshness_uses_received_at_not_source_time() -> None:
    """source_time 很旧但 received_at_ms 新鲜时仍可锁定，证明 freshness 不看 timestamp。"""

    context = _evaluate([A_POINT, (2.1, 2.1), (2.2, 2.2)], source_start=1)
    assert context is not None
    assert context.timestamp == 3


def test_context_timestamp_uses_latest_source_time() -> None:
    """PreShotDirectorContext.timestamp 使用最终锁定点的设备 source_time。"""

    context = _evaluate([A_POINT, (2.1, 2.1), (2.2, 2.2)], source_start=1786078169550)
    assert context is not None
    assert context.timestamp == 1786078169552


def test_zone_boundary_is_inclusive() -> None:
    """Ready Zone 边界采用 inclusive 规则。"""

    context = _evaluate([(0.0, 0.0), (3.0, 3.0), (0.0, 3.0)])
    assert context is not None
    assert context.direction == "A_TO_B"


def test_ambiguous_zone_does_not_guess() -> None:
    """错误配置导致 A/B Zone 重叠时，不得偏向任一方向。"""

    zones = {
        "A": {"x_min": 0.0, "x_max": 6.0, "y_min": 0.0, "y_max": 6.0},
        "B": {"x_min": 2.0, "x_max": 8.0, "y_min": 2.0, "y_max": 8.0},
    }
    assert _evaluate([(3.0, 3.0), (3.1, 3.1), (3.2, 3.2)], ready_zones=zones) is None


def test_lock_prevents_repeated_context_and_other_tag_takeover() -> None:
    """同一 match + sheet 锁定后不重复发 context，也不允许其他 tag 抢占。"""

    cache = PositionCache(max_size=10)
    service = _service(cache)
    _add_points(cache, [A_POINT, (2.1, 2.1), (2.2, 2.2)], tag_id="stone0")
    first = service.evaluate("match_lock", "sheet_01", "stone0", now_ms=NOW_MS)
    assert first is not None
    assert service.evaluate("match_lock", "sheet_01", "stone0", now_ms=NOW_MS) is None

    _add_points(cache, [B_POINT, (8.1, 8.1), (8.2, 8.2)], tag_id="stone5")
    assert service.evaluate("match_lock", "sheet_01", "stone5", now_ms=NOW_MS) is None
    assert service.get_lock("match_lock", "sheet_01").candidate_tag_id == "stone0"  # type: ignore[union-attr]


def test_reset_allows_next_throw_and_clear_apis_work() -> None:
    """显式 reset/clear_match/clear 能释放锁，且不会因离开 Ready Zone 自动 reset。"""

    cache = PositionCache(max_size=10)
    service = _service(cache)
    _add_points(cache, [A_POINT, (2.1, 2.1), (2.2, 2.2)], tag_id="stone0")
    assert service.evaluate("match_reset", "sheet_01", "stone0", now_ms=NOW_MS) is not None

    _add_points(cache, [OUTSIDE_POINT, (5.6, 5.6), (5.7, 5.7)], tag_id="stone0", source_start=2000)
    assert service.evaluate("match_reset", "sheet_01", "stone0", now_ms=NOW_MS) is None
    assert service.get_lock("match_reset", "sheet_01") is not None

    service.reset("match_reset", "sheet_01")
    _add_points(cache, [B_POINT, (8.1, 8.1), (8.2, 8.2)], tag_id="stone5")
    second = service.evaluate("match_reset", "sheet_01", "stone5", now_ms=NOW_MS)
    assert second is not None
    assert second.direction == "B_TO_A"

    service.clear_match("match_reset")
    assert service.get_lock("match_reset", "sheet_01") is None
    service.evaluate("match_reset", "sheet_01", "stone5", now_ms=NOW_MS)
    service.clear()
    assert service.get_lock("match_reset", "sheet_01") is None


def test_match_and_sheet_isolation() -> None:
    """锁定状态按 match_id + sheet_id 隔离，而不是只按 sheet 或 tag。"""

    cache = PositionCache(max_size=10)
    service = _service(cache, sheet_ids=["sheet_01", "sheet_02"])
    _add_points(cache, [A_POINT, (2.1, 2.1), (2.2, 2.2)], sheet_id="sheet_01", lane_id="fake_lane_01")
    assert service.evaluate("match_001", "sheet_01", "stone0", now_ms=NOW_MS) is not None
    assert service.evaluate("match_002", "sheet_01", "stone0", now_ms=NOW_MS) is not None

    _add_points(cache, [B_POINT, (8.1, 8.1), (8.2, 8.2)], sheet_id="sheet_02", lane_id="fake_lane_02", tag_id="stone0")
    context = service.evaluate("match_001", "sheet_02", "stone0", now_ms=NOW_MS)
    assert context is not None
    assert context.direction == "B_TO_A"


def test_confirm_count_one_locks_with_single_fresh_point() -> None:
    """confirm_count=1 时，一个 fresh Ready Zone 点即可锁定。"""

    context = _evaluate([B_POINT], confirm_count=1)
    assert context is not None
    assert context.direction == "B_TO_A"


def test_invalid_settings_and_service_validation() -> None:
    """配置 validation 拒绝非法 freshness 和 confirm_count。"""

    with pytest.raises(ValidationError):
        Settings(position_freshness_ms=0)
    with pytest.raises(ValidationError):
        Settings(direction_confirm_count=0)
    with pytest.raises(ValueError):
        PreShotDirectionService(PositionCache(), _manager(), position_freshness_ms=0)
    with pytest.raises(ValueError):
        PreShotDirectionService(PositionCache(), _manager(), direction_confirm_count=0)


def _raw_type3(lane_id: str, tag_id: str, source_time: int, x: float, y: float) -> TrajectoryRawMessage:
    """构造真实协议形态的 fake type=3 JSON。"""

    message = parse_raw_curling_message(json.dumps({
        "type": 3,
        "laneId": lane_id,
        "trajectoryData": {"laneId": lane_id, "tagId": tag_id, "time": source_time, "x": x, "y": y},
    }))
    assert isinstance(message, TrajectoryRawMessage)
    return message


def _register_director_match(match_id: str) -> DirectorService:
    """使用正式 DirectorService.start_sheet 初始化运行时镜头。"""

    director = DirectorService()
    available = {
        "medium_shot": ["sheet_01_me_A", "sheet_01_me_B"],
        "close_shot": ["sheet_01_cl_A", "sheet_01_cl_B"],
        "house_top": ["sheet_01_house_B"],
    }
    sheet = director.start_sheet(match_id, "sheet_01", available)
    runtime_manager.create_match(MatchRuntime(match_id=match_id, sheet_id="sheet_01", scene_type="competition", start_time="2026-08-26T10:00:00+08:00", sheets={"sheet_01": sheet}))
    return director


def test_e2e_a_to_b_raw_position_direction_to_director() -> None:
    """Raw type=3 -> Adapter -> Cache -> DirectionService -> Director，A Zone 应切 B 端近景。"""

    cache = PositionCache(max_size=10)
    adapter = TrajectoryPositionAdapter(_manager())
    service = _service(cache)
    for index, point in enumerate([A_POINT, (2.1, 2.1), (2.2, 2.2)]):
        for position in adapter.convert(_raw_type3("fake_lane_01", "stone0", 5000 + index, point[0], point[1])):
            cache.add(position, received_at_ms=NOW_MS)

    context = service.evaluate("match_e2e_a", "sheet_01", "stone0", now_ms=NOW_MS)
    assert context is not None
    assert context.direction == "A_TO_B"
    assert context.source_end == "A"
    assert context.target_end == "B"
    assert context.candidate_tag_id == "stone0"

    decision = _register_director_match("match_e2e_a").decide(context)
    assert decision.camera_role == "close_shot"
    assert decision.install_end == "B"
    assert decision.camera_id == "sheet_01_cl_B"


def test_e2e_b_to_a_raw_position_direction_to_director() -> None:
    """Raw type=3 -> Adapter -> Cache -> DirectionService -> Director，B Zone 应切 A 端近景。"""

    cache = PositionCache(max_size=10)
    adapter = TrajectoryPositionAdapter(_manager())
    service = _service(cache)
    for index, point in enumerate([B_POINT, (8.1, 8.1), (8.2, 8.2)]):
        for position in adapter.convert(_raw_type3("fake_lane_01", "stone5", 6000 + index, point[0], point[1])):
            cache.add(position, received_at_ms=NOW_MS)

    context = service.evaluate("match_e2e_b", "sheet_01", "stone5", now_ms=NOW_MS)
    assert context is not None
    assert context.direction == "B_TO_A"
    assert context.source_end == "B"
    assert context.target_end == "A"

    decision = _register_director_match("match_e2e_b").decide(context)
    assert decision.camera_role == "close_shot"
    assert decision.install_end == "A"
    assert decision.camera_id == "sheet_01_cl_A"


def test_phase72_boundaries_do_not_create_shot_trigger_or_call_director() -> None:
    """Direction Service 只生成 PreShotDirectorContext，不处理 type=4/type=12/Shot/Director。"""

    assert isinstance(parse_raw_curling_message(json.dumps({"type": 4, "laneId": "fake_lane_01", "stoneState": "start"})), StoneStateRawMessage)
    assert isinstance(parse_raw_curling_message(json.dumps({"type": 12, "data": {}})), FullDataRawMessage)

    source = Path("app/services/pre_shot_direction_service.py").read_text(encoding="utf-8")
    assert "from app.services.director" not in source
    assert "DirectorService(" not in source
    assert "ThrowStateMachine" not in source
    assert "TriggerEvent" not in source
    assert "ShotEventContext" not in source
    assert "StoneStateRawMessage" not in source
    assert "FullDataRawMessage" not in source
    assert "hogline" not in source.lower()
