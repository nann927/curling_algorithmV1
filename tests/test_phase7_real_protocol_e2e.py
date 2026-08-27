"""Phase 7.6 真实协议 Raw JSON 端到端编排测试。

本文件使用 fake Raw JSON 驱动真实 Parser/Adapter/Cache/Coordinator/Director 链路；
测试坐标和 lane_id 只服务单元测试，不代表现场标定。
"""

from __future__ import annotations

import json

from app.core.config import ConfigManager, Settings
from app.core.enums import RuntimeStatus, ShotQualityStatus, ThrowStatus
from app.core.runtime import MatchRuntime, runtime_manager
from app.models.shot_coordination import ShotDirectionAlignmentStatus
from app.services.curling_realtime_orchestrator import CurlingRealtimeOrchestrator
from app.services.direction_service import DirectionService
from app.services.director_service import DirectorService
from app.services.position_cache import PositionCache
from app.services.pre_shot_direction_service import PreShotDirectionService
from app.services.shot_direction_coordination_service import ShotDirectionCoordinationService
from app.services.stone_event_service import StoneEventService
from app.services.stone_state_edge_detector import StoneStateEdgeDetector
from app.services.stone_state_event_bridge import StoneStateEventBridge
from app.storage.shot_repository import ShotRepository

A_POINTS = [(1.0, 1.0), (1.2, 1.1), (1.1, 1.3)]
B_POINTS = [(9.0, 9.0), (8.8, 8.9), (8.9, 8.7)]
NOW_MS = 20_000


def _site_config() -> dict:
    """构造两条赛道的测试现场配置，覆盖 position/state lane 和 A/B 三类镜头。"""

    cameras = []
    for sheet_id in ("sheet_01", "sheet_02"):
        cameras.extend(
            [
                {"camera_id": f"{sheet_id}_me_A", "camera_role": "medium_shot", "sheet_id": sheet_id, "install_end": "A", "source_provider": "local_file", "source_config": {}},
                {"camera_id": f"{sheet_id}_me_B", "camera_role": "medium_shot", "sheet_id": sheet_id, "install_end": "B", "source_provider": "local_file", "source_config": {}},
                {"camera_id": f"{sheet_id}_cl_A", "camera_role": "close_shot", "sheet_id": sheet_id, "install_end": "A", "source_provider": "local_file", "source_config": {}},
                {"camera_id": f"{sheet_id}_cl_B", "camera_role": "close_shot", "sheet_id": sheet_id, "install_end": "B", "source_provider": "local_file", "source_config": {}},
                {"camera_id": f"{sheet_id}_house_A", "camera_role": "house_top", "sheet_id": sheet_id, "install_end": "A", "source_provider": "local_file", "source_config": {}},
                {"camera_id": f"{sheet_id}_house_B", "camera_role": "house_top", "sheet_id": sheet_id, "install_end": "B", "source_provider": "local_file", "source_config": {}},
            ]
        )
    return {
        "site_id": "phase76_test",
        "sheets": [
            {"sheet_id": "sheet_01", "sheet_name": "1号赛道", "enabled": True, "position_lane_id": "position_lane_01", "trigger_lane_id": "state_lane_01"},
            {"sheet_id": "sheet_02", "sheet_name": "2号赛道", "enabled": True, "position_lane_id": "position_lane_02", "trigger_lane_id": "state_lane_02"},
        ],
        "lane_mappings": [
            {"lane_id": "position_lane_01", "sheet_id": "sheet_01"},
            {"lane_id": "position_lane_02", "sheet_id": "sheet_02"},
        ],
        "cameras": cameras,
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
                },
                {
                    "sheet_id": "sheet_02",
                    "enabled": True,
                    "position_lane_id": "position_lane_02",
                    "lane_bounds": {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
                    "ready_zones": {
                        "A": {"x_min": 0.0, "x_max": 3.0, "y_min": 0.0, "y_max": 3.0},
                        "B": {"x_min": 7.0, "x_max": 10.0, "y_min": 7.0, "y_max": 10.0},
                    },
                    "hoglines": {"A": {"y": 3.5}, "B": {"y": 6.5}},
                },
            ]
        },
    }


def _manager() -> ConfigManager:
    """创建隔离 ConfigManager，避免依赖真实 site_config。"""

    return ConfigManager(Settings(site_config=_site_config(), position_cache_size=20, position_freshness_ms=1000, direction_confirm_count=3))


def _orchestrator() -> tuple[CurlingRealtimeOrchestrator, ConfigManager, DirectorService, PositionCache]:
    """创建一组共享服务实例，验证 Orchestrator 没有重复造状态。"""

    manager = _manager()
    cache = PositionCache(max_size=20)
    direction_service = DirectionService(config_manager=manager)
    stone_event_service = StoneEventService(direction_service=direction_service)
    pre_shot = PreShotDirectionService(cache, manager, position_freshness_ms=1000, direction_confirm_count=3)
    bridge = StoneStateEventBridge(manager, runtime_manager, stone_event_service)
    coordinator = ShotDirectionCoordinationService(
        pre_shot_direction_service=pre_shot,
        direction_service=direction_service,
        stone_event_service=stone_event_service,
        bridge=bridge,
    )
    director = DirectorService(manager)
    orchestrator = CurlingRealtimeOrchestrator(
        config_manager=manager,
        runtime_registry=runtime_manager,
        cache=cache,
        pre_shot_direction_service=pre_shot,
        direction_service=direction_service,
        stone_event_service=stone_event_service,
        bridge=bridge,
        coordinator=coordinator,
        edge_detector=StoneStateEdgeDetector(),
        director_service=director,
    )
    return orchestrator, manager, director, cache


def _register_match(match_id: str, manager: ConfigManager, director: DirectorService, sheet_id: str = "sheet_01") -> None:
    """复用正式 DirectorService.start_sheet 初始化当前赛道镜头。"""

    sheet = director.start_sheet(match_id, sheet_id, manager.get_sheet_camera_ids_by_role(sheet_id))
    runtime_manager.create_match(
        MatchRuntime(
            match_id=match_id,
            sheet_id=sheet_id,
            scene_type="competition",
            start_time="2026-08-27T10:00:00+08:00",
            status=RuntimeStatus.RUNNING.value,
            sheets={sheet_id: sheet},
        )
    )


def _raw_position(lane_id: str, tag_id: str, timestamp: int, x: float, y: float) -> str:
    """构造真实协议 type=3 fake Raw JSON。"""

    return json.dumps({"type": 3, "laneId": lane_id, "trajectoryData": {"laneId": lane_id, "tagId": tag_id, "time": timestamp, "x": x, "y": y}})


def _raw_state(lane_id: str, tag_id: str, state: str) -> str:
    """构造真实协议 type=4 fake Raw JSON。"""

    return json.dumps(
        {
            "type": 4,
            "laneId": lane_id,
            "movingStoneTagId": tag_id,
            "stoneState": state,
            "hogLine1Timing": 379,
            "hogLine2Timing": 21,
            "totalTiming": 400,
        }
    )


def _lock_from_positions(orchestrator: CurlingRealtimeOrchestrator, lane_id: str, tag_id: str, points: list[tuple[float, float]], *, start_time: int = 1000):
    """通过 Raw type=3 轨迹点锁定预投方向，并返回最后一次结果。"""

    result = None
    for index, (x, y) in enumerate(points):
        result = orchestrator.process_raw_text(_raw_position(lane_id, tag_id, start_time + index, x, y), received_at_ms=NOW_MS + index)[0]
    assert result is not None
    return result


def _state(orchestrator: CurlingRealtimeOrchestrator, lane_id: str, tag_id: str, state: str, received_at_ms: int):
    """处理一条 Raw type=4 状态消息并返回单条编排结果。"""

    return orchestrator.process_raw_text(_raw_state(lane_id, tag_id, state), received_at_ms=received_at_ms)[0]


def _full_state_chain(orchestrator: CurlingRealtimeOrchestrator, lane_id: str, tag_id: str, *, base_time: int = 3000):
    """跑完 start/hogline1/hogline2/end，返回四个状态结果。"""

    return [
        _state(orchestrator, lane_id, tag_id, "start", base_time),
        _state(orchestrator, lane_id, tag_id, "hogline1", base_time + 100),
        _state(orchestrator, lane_id, tag_id, "hogline2", base_time + 200),
        _state(orchestrator, lane_id, tag_id, "end", base_time + 300),
    ]


def _shot(shot_id: str):
    """读取已完成 Shot，缩短断言代码。"""

    shot = ShotRepository().get(shot_id)
    assert shot is not None
    return shot


def test_matched_a_to_b_full_raw_protocol_timeline() -> None:
    """A Ready Zone 锁定 A_TO_B 后，type=4 四事件完整驱动 Shot 与 Director。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_a_to_b", manager, director)
    assert runtime_manager.get_match("match_a_to_b").sheets["sheet_01"].current_camera_id == "sheet_01_house_A"

    locked = _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    assert locked.pre_shot_contexts[0].direction == "A_TO_B"
    assert locked.director_decisions[0].camera_id == "sheet_01_cl_B"

    results = _full_state_chain(orchestrator, "state_lane_01", "stone0")
    assert [item.shot_context.event_type for item in results] == ["departure", "magnetic_1", "magnetic_2", "stop"]  # type: ignore[union-attr]
    assert [item.director_decisions[0].camera_id for item in results] == ["sheet_01_cl_B", "sheet_01_me_B", "sheet_01_house_B", "sheet_01_cl_A"]
    assert results[0].coordination_result.alignment_status == ShotDirectionAlignmentStatus.MATCHED  # type: ignore[union-attr]

    shot = _shot("match_a_to_b_sheet_01_shot_0001")
    assert shot.direction == "A_TO_B"
    assert shot.source_end == "A"
    assert shot.target_end == "B"
    assert shot.touch_time is None
    assert shot.quality_status == ShotQualityStatus.COMPLETE.value
    assert shot.abnormal_reason is None


def test_matched_b_to_a_full_raw_protocol_timeline() -> None:
    """B Ready Zone 锁定 B_TO_A 后，Director 时间线按 source/target 镜像。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_b_to_a", manager, director)
    locked = _lock_from_positions(orchestrator, "position_lane_01", "stone5", B_POINTS)
    assert locked.pre_shot_contexts[0].direction == "B_TO_A"
    assert locked.director_decisions[0].camera_id == "sheet_01_cl_A"

    results = _full_state_chain(orchestrator, "state_lane_01", "stone5")
    assert [item.director_decisions[0].camera_id for item in results] == ["sheet_01_cl_A", "sheet_01_me_A", "sheet_01_house_A", "sheet_01_cl_B"]
    shot = _shot("match_b_to_a_sheet_01_shot_0001")
    assert shot.direction == "B_TO_A"
    assert shot.source_end == "B"
    assert shot.target_end == "A"
    assert shot.quality_status == ShotQualityStatus.COMPLETE.value


def test_no_pre_shot_lock_keeps_unknown_and_still_completes() -> None:
    """没有 type=3 预锁时，业务状态仍推进，方向保持 UNKNOWN 且生命周期 complete。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_no_lock_e2e", manager, director)
    results = _full_state_chain(orchestrator, "state_lane_01", "stone0")
    assert results[0].coordination_result.alignment_status == ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK  # type: ignore[union-attr]
    assert results[0].shot_context.direction == "UNKNOWN"  # type: ignore[union-attr]
    assert results[0].director_decisions[0].reason == "direction_unknown"

    shot = _shot("match_no_lock_e2e_sheet_01_shot_0001")
    assert shot.direction == "UNKNOWN"
    assert shot.source_end is None
    assert shot.target_end is None
    assert shot.touch_time is None
    assert shot.quality_status == ShotQualityStatus.COMPLETE.value


def test_candidate_mismatch_does_not_inherit_candidate_or_previous_direction() -> None:
    """candidate 与 movingStoneTagId 不一致时，不继承错误 candidate 方向。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_mismatch_e2e", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)

    results = _full_state_chain(orchestrator, "state_lane_01", "stone9")
    assert results[0].coordination_result.alignment_status == ShotDirectionAlignmentStatus.CANDIDATE_MISMATCH  # type: ignore[union-attr]
    assert results[0].coordination_result.candidate_tag_id == "stone0"  # type: ignore[union-attr]
    assert results[0].shot_context.direction == "UNKNOWN"  # type: ignore[union-attr]

    shot = _shot("match_mismatch_e2e_sheet_01_shot_0001")
    assert shot.direction == "UNKNOWN"
    assert shot.source_end is None
    assert shot.target_end is None
    assert shot.quality_status == ShotQualityStatus.COMPLETE.value


def test_duplicate_state_updates_emit_only_first_edge() -> None:
    """重复 state/timing 推送只由 EdgeDetector 产生第一次边沿，不重复驱动 Shot/Director。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_duplicate_e2e", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)

    states = ["start", "start", "hogline1", "hogline1", "hogline2", "hogline2", "end", "end"]
    results = [_state(orchestrator, "state_lane_01", "stone0", state, 4000 + index) for index, state in enumerate(states)]
    assert [item.shot_context.event_type for item in results if item.shot_context is not None] == ["departure", "magnetic_1", "magnetic_2", "stop"]
    assert [item.ignored_reason for item in results if item.ignored_reason == "no_state_edge"] == ["no_state_edge", "no_state_edge", "no_state_edge", "no_state_edge"]
    assert _shot("match_duplicate_e2e_sheet_01_shot_0001").status == ThrowStatus.FINISHED.value


def test_missing_hogline2_does_not_auto_house_decision() -> None:
    """缺 hogline2 时不得自动生成 house_top 决策。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_missing_h2", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)

    departure = _state(orchestrator, "state_lane_01", "stone0", "start", 5000)
    magnetic_1 = _state(orchestrator, "state_lane_01", "stone0", "hogline1", 5100)
    assert departure.director_decisions[0].camera_id == "sheet_01_cl_B"
    assert magnetic_1.director_decisions[0].camera_id == "sheet_01_me_B"
    assert all(decision.camera_role != "house_top" for result in (departure, magnetic_1) for decision in result.director_decisions)
    assert ShotRepository().list_by_match("match_missing_h2") == []


def test_missing_stop_does_not_finish_or_source_close() -> None:
    """缺 stop 时不自动 FINISHED，也不自动回 source close。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_missing_stop", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)

    results = [
        _state(orchestrator, "state_lane_01", "stone0", "start", 6000),
        _state(orchestrator, "state_lane_01", "stone0", "hogline1", 6100),
        _state(orchestrator, "state_lane_01", "stone0", "hogline2", 6200),
    ]
    assert [item.director_decisions[0].camera_id for item in results] == ["sheet_01_cl_B", "sheet_01_me_B", "sheet_01_house_B"]
    assert ShotRepository().list_by_match("match_missing_stop") == []
    current = orchestrator.stone_event_service.get_current_shot("match_missing_stop", "sheet_01")
    assert current is not None
    assert current.status == ThrowStatus.PASSED_MAGNETIC_2.value


def test_late_position_after_departure_is_cached_but_does_not_drive_current_shot() -> None:
    """departure 后 pre-shot 窗口关闭，晚到 type=3 只入缓存，不触发当前 Shot 预切镜。"""

    orchestrator, manager, director, cache = _orchestrator()
    _register_match("match_late_position", manager, director)
    start = _state(orchestrator, "state_lane_01", "stone0", "start", 7000)
    assert start.coordination_result.alignment_status == ShotDirectionAlignmentStatus.NO_PRE_SHOT_LOCK  # type: ignore[union-attr]

    late = _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS, start_time=7100)
    assert late.ignored_reason == "active_shot_pre_shot_window_closed"
    assert late.pre_shot_contexts == []
    assert late.director_decisions == []
    assert cache.get_latest("sheet_01", "stone0") is not None
    assert orchestrator.stone_event_service.get_current_shot("match_late_position", "sheet_01").direction == "UNKNOWN"  # type: ignore[union-attr]


def test_stop_reopens_pre_shot_window_for_next_throw() -> None:
    """stop 后释放锁和 active 状态，下一投可以重新通过 type=3 触发预投切镜。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_next_window", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    _full_state_chain(orchestrator, "state_lane_01", "stone0")

    next_lock = _lock_from_positions(orchestrator, "position_lane_01", "stone5", B_POINTS, start_time=8000)
    assert next_lock.pre_shot_contexts[0].direction == "B_TO_A"
    assert next_lock.director_decisions[0].camera_id == "sheet_01_cl_A"


def test_multi_sheet_isolation_with_shared_orchestrator() -> None:
    """同一 Orchestrator 内两条赛道共享服务实例，但 Runtime、锁和镜头相互隔离。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_sheet_01", manager, director, "sheet_01")
    _register_match("match_sheet_02", manager, director, "sheet_02")

    lock_01 = _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    lock_02 = _lock_from_positions(orchestrator, "position_lane_02", "stone5", B_POINTS)
    assert lock_01.pre_shot_contexts[0].direction == "A_TO_B"
    assert lock_02.pre_shot_contexts[0].direction == "B_TO_A"

    start_01 = _state(orchestrator, "state_lane_01", "stone0", "start", 9000)
    start_02 = _state(orchestrator, "state_lane_02", "stone5", "start", 9010)
    assert start_01.shot_context.match_id == "match_sheet_01"  # type: ignore[union-attr]
    assert start_02.shot_context.match_id == "match_sheet_02"  # type: ignore[union-attr]
    assert start_01.director_decisions[0].camera_id == "sheet_01_cl_B"
    assert start_02.director_decisions[0].camera_id == "sheet_02_cl_A"


def test_type12_type1_type2_unknown_and_malformed_are_ignored() -> None:
    """非业务 Raw 消息不得控制 Match 生命周期，也不得调用 Shot/Director。"""

    orchestrator, _, _, _ = _orchestrator()
    payloads = [
        json.dumps({"type": 12, "data": {}}),
        json.dumps({"type": 1, "laneId": "state_lane_01"}),
        json.dumps({"type": 2, "laneId": "state_lane_01"}),
        json.dumps({"type": 99, "laneId": "state_lane_01"}),
        "not-json",
    ]
    results = [orchestrator.process_raw_text(payload)[0] for payload in payloads]
    assert [item.ignored_reason for item in results[:4]] == ["type12_ignored", "type1_does_not_control_match", "type2_does_not_control_match", "unknown_type_ignored"]
    assert results[4].ignored_reason.startswith("malformed_json")  # type: ignore[union-attr]
    assert runtime_manager.list_matches() == []


def test_orchestrator_uses_the_same_shared_service_instances() -> None:
    """确认 Orchestrator 对 type=3/type=4 使用同一组 Direction/PreShot/Stone 服务。"""

    orchestrator, manager, director, _ = _orchestrator()
    _register_match("match_shared", manager, director)
    _lock_from_positions(orchestrator, "position_lane_01", "stone0", A_POINTS)
    assert orchestrator.pre_shot_direction_service.get_lock("match_shared", "sheet_01") is not None

    departure = _state(orchestrator, "state_lane_01", "stone0", "start", 10_000)
    assert departure.coordination_result.alignment_status == ShotDirectionAlignmentStatus.MATCHED  # type: ignore[union-attr]
    assert orchestrator.stone_event_service.get_current_shot("match_shared", "sheet_01").direction == "A_TO_B"  # type: ignore[union-attr]
    assert orchestrator.direction_service.get_direction("sheet_01", match_id="match_shared").direction == "A_TO_B"
