"""Phase 6.6 Director Rule 正式业务规则测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.director import DirectorDecision, PreShotDirectorContext
from app.models.shot import ShotEventContext
from app.services.director_rule_service import DirectorRuleService
from app.services.director_service import DirectorService


@dataclass
class _FakeCamera:
    """测试专用摄像头 metadata，证明规则只依赖结构字段而不是 camera_id 字符串。"""

    camera_id: str
    camera_role: str
    install_end: str


class _FakeConfigManager:
    """测试专用 ConfigManager，只实现 DirectorRuleService 需要的 get_camera。"""

    def __init__(self, cameras: dict[str, _FakeCamera]) -> None:
        self._cameras = cameras

    def get_camera(self, camera_id: str) -> _FakeCamera:
        """按测试 camera_id 返回结构化 metadata。"""

        if camera_id not in self._cameras:
            raise KeyError(camera_id)
        return self._cameras[camera_id]


def _context(
    event_type: str,
    *,
    match_id: str = "match_phase6",
    sheet_id: str = "sheet_01",
    direction: str = "A_TO_B",
    source_end: str | None = "A",
    target_end: str | None = "B",
    timestamp: int = 1000,
) -> ShotEventContext:
    """构造 Director Rule 消费的标准化 ShotEventContext。"""

    return ShotEventContext(
        match_id=match_id,
        sheet_id=sheet_id,
        shot_id=f"{match_id}_{sheet_id}_shot_0001",
        event_type=event_type,
        timestamp=timestamp,
        shot_status=None,
        direction=direction,
        source_end=source_end,
        target_end=target_end,
        quality_status=None,
    )


def _pre_context(
    *,
    match_id: str = "match_phase6",
    sheet_id: str = "sheet_01",
    direction: str = "A_TO_B",
    source_end: str = "A",
    target_end: str = "B",
    timestamp: int = 900,
) -> PreShotDirectorContext:
    """构造投壶前 direction_locked 导演上下文，不带 shot_id。"""

    return PreShotDirectorContext(
        match_id=match_id,
        sheet_id=sheet_id,
        event_type="direction_locked",
        timestamp=timestamp,
        direction=direction,
        source_end=source_end,
        target_end=target_end,
        candidate_tag_id="candidate_001",
    )


def _register_match(
    match_id: str = "match_phase6",
    sheet_id: str = "sheet_01",
    *,
    available: dict[str, list[str]] | None = None,
    current_camera_id: str | None = None,
) -> MatchRuntime:
    """创建带指定候选摄像头的运行时 Match。"""

    sheet = SheetRuntime(
        sheet_id=sheet_id,
        enabled=True,
        stream_type="smart_director",
        media_url="mock://director",
        available_camera_ids=available or {},
        current_camera_id=current_camera_id,
    )
    match = MatchRuntime(
        match_id=match_id,
        sheet_id=sheet_id,
        scene_type="competition",
        start_time="2026-08-21T10:00:00+08:00",
        sheets={sheet_id: sheet},
    )
    runtime_manager.create_match(match)
    return match


def _available_sheet_01(*, house_a: bool = False, house_b: bool = True, overview_a: bool = True, overview_b: bool = True) -> dict[str, list[str]]:
    """按 Phase 4.6.2 展开后的内部摄像头集合构造测试候选。"""

    available: dict[str, list[str]] = {"medium_shot": [], "close_shot": [], "house_top": []}
    if overview_a:
        available["medium_shot"].append("sheet_01_me_A")
        available["close_shot"].append("sheet_01_cl_A")
    if overview_b:
        available["medium_shot"].append("sheet_01_me_B")
        available["close_shot"].append("sheet_01_cl_B")
    if house_a:
        available["house_top"].append("sheet_01_house_A")
    if house_b:
        available["house_top"].append("sheet_01_house_B")
    return {role: values for role, values in available.items() if values}


def test_preshot_director_context_model() -> None:
    """direction_locked 是投壶前导演上下文，不属于 Shot 生命周期。"""

    context = _pre_context()
    assert context.event_type == "direction_locked"
    assert context.match_id == "match_phase6"
    assert context.sheet_id == "sheet_01"
    assert context.direction == "A_TO_B"
    assert context.source_end == "A"
    assert context.target_end == "B"
    assert context.candidate_tag_id == "candidate_001"
    assert "shot_id" not in context.model_dump()


def test_director_decision_model_fields_and_hold_duration() -> None:
    """DirectorDecision 模型应包含 Phase 6.6 需要的业务字段。"""

    decision = DirectorDecision(
        match_id="m1",
        sheet_id="sheet_01",
        shot_id=None,
        event_type="direction_locked",
        timestamp=900,
        direction="A_TO_B",
        source_end="A",
        target_end="B",
        camera_id="sheet_01_cl_B",
        camera_role="close_shot",
        install_end="B",
        reason="direction_locked_target_close",
    )
    data = decision.model_dump()
    assert {
        "match_id",
        "sheet_id",
        "shot_id",
        "event_type",
        "timestamp",
        "direction",
        "source_end",
        "target_end",
        "camera_id",
        "camera_role",
        "install_end",
        "reason",
        "fallback_used",
        "hold_previous",
        "hold_duration_ms",
    }.issubset(data)
    assert decision.shot_id is None
    assert decision.hold_duration_ms == 0


def test_direction_locked_targets_close_without_shot_id() -> None:
    """direction_locked 选择 target_end close_shot，并且不生成 fake shot_id。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id="sheet_01_house_B")
    decision = DirectorService().decide(_pre_context())
    assert decision.shot_id is None
    assert decision.camera_id == "sheet_01_cl_B"
    assert decision.camera_role == "close_shot"
    assert decision.install_end == "B"
    assert decision.reason == "direction_locked_target_close"
    assert decision.hold_duration_ms == 0
    assert not decision.hold_previous


def test_a_to_b_formal_timeline_uses_target_then_source() -> None:
    """A_TO_B 的投掷过程由 B 端负责，结束后回切 A 端近景。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id=None)
    service = DirectorService()

    locked = service.decide(_pre_context(timestamp=900))
    assert locked.camera_id == "sheet_01_cl_B"
    assert locked.reason == "direction_locked_target_close"

    departure = service.decide(_context("departure", timestamp=1400))
    assert departure.camera_id == "sheet_01_cl_B"
    assert departure.reason == "departure_target_close"
    assert departure.hold_previous

    magnetic_1 = service.decide(_context("magnetic_1", timestamp=1500))
    assert magnetic_1.camera_id == "sheet_01_me_B"
    assert magnetic_1.reason == "magnetic1_target_medium"
    assert not magnetic_1.hold_previous

    magnetic_2 = service.decide(_context("magnetic_2", timestamp=1600))
    assert magnetic_2.camera_id == "sheet_01_house_B"
    assert magnetic_2.reason == "magnetic2_target_house"

    stop = service.decide(_context("stop", timestamp=1700))
    assert stop.camera_id == "sheet_01_cl_A"
    assert stop.camera_role == "close_shot"
    assert stop.install_end == "A"
    assert stop.reason == "stop_source_close"
    assert stop.hold_duration_ms == 3000


def test_b_to_a_formal_timeline_is_mirrored_by_source_target() -> None:
    """B_TO_A 使用同一套 source_end/target_end 规则完成自然镜像。"""

    _register_match(available=_available_sheet_01(house_a=True, house_b=False), current_camera_id=None)
    service = DirectorService()
    common = {"direction": "B_TO_A", "source_end": "B", "target_end": "A"}

    assert service.decide(_pre_context(**common)).camera_id == "sheet_01_cl_A"
    departure = service.decide(_context("departure", **common))
    assert departure.camera_id == "sheet_01_cl_A"
    assert departure.hold_previous
    assert service.decide(_context("magnetic_1", **common)).camera_id == "sheet_01_me_A"
    assert service.decide(_context("magnetic_2", **common)).camera_id == "sheet_01_house_A"
    stop = service.decide(_context("stop", **common))
    assert stop.camera_id == "sheet_01_cl_B"
    assert stop.install_end == "B"
    assert stop.hold_duration_ms == 3000


def test_legacy_touch_known_direction_targets_close() -> None:
    """旧 Mock touch 如果方向已知，应按新规则切 target close。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id="sheet_01_house_B")
    decision = DirectorService().decide(_context("touch"))
    assert decision.camera_id == "sheet_01_cl_B"
    assert decision.reason == "touch_target_close"
    assert decision.hold_duration_ms == 0


def test_touch_unknown_holds_current_camera() -> None:
    """touch 阶段方向未知时不得猜方向，优先保持当前可用镜头。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id="sheet_01_house_B")
    decision = DirectorService().decide(_context("touch", direction="UNKNOWN", source_end=None, target_end=None))
    assert decision.camera_id == "sheet_01_house_B"
    assert decision.reason == "direction_unknown"
    assert decision.fallback_used
    assert decision.hold_previous
    assert decision.hold_duration_ms == 0


def test_alarm_holds_current_camera() -> None:
    """alarm 不主动切镜，已有当前镜头时保持当前 camera。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id="sheet_01_me_B")
    decision = DirectorService().decide(_context("alarm"))
    assert decision.camera_id == "sheet_01_me_B"
    assert decision.reason == "alarm_hold_current_camera"
    assert decision.hold_previous
    assert not decision.fallback_used
    assert decision.hold_duration_ms == 0


def test_house_not_enabled_falls_back_to_target_medium() -> None:
    """house_top 未显式启用时，magnetic_2 不得从 site_config 偷用 house camera。"""

    _register_match(available=_available_sheet_01(house_a=False, house_b=False), current_camera_id="sheet_01_me_B")
    decision = DirectorService().decide(_context("magnetic_2"))
    assert decision.camera_id == "sheet_01_me_B"
    assert decision.camera_role == "medium_shot"
    assert decision.install_end == "B"
    assert decision.fallback_used
    assert decision.reason == "preferred_camera_unavailable"
    assert decision.hold_previous


def test_target_close_missing_falls_back_to_same_end_medium() -> None:
    """target close 不可用时，优先在 target 端降级到 medium。"""

    available = {"medium_shot": ["sheet_01_me_A", "sheet_01_me_B"], "close_shot": ["sheet_01_cl_A"]}
    _register_match(available=available, current_camera_id="sheet_01_me_A")
    decision = DirectorService().decide(_pre_context())
    assert decision.camera_id == "sheet_01_me_B"
    assert decision.camera_role == "medium_shot"
    assert decision.install_end == "B"
    assert decision.reason == "preferred_camera_unavailable"
    assert decision.fallback_used


def test_stop_source_close_missing_falls_back_to_source_medium() -> None:
    """stop 首选 source close 缺失时，应回退到 source medium，而不是停留在 target house。"""

    available = {
        "medium_shot": ["sheet_01_me_A", "sheet_01_me_B"],
        "close_shot": ["sheet_01_cl_B"],
        "house_top": ["sheet_01_house_B"],
    }
    _register_match(available=available, current_camera_id="sheet_01_house_B")
    decision = DirectorService().decide(_context("stop"))
    assert decision.camera_id == "sheet_01_me_A"
    assert decision.camera_role == "medium_shot"
    assert decision.install_end == "A"
    assert decision.reason == "preferred_camera_unavailable"
    assert decision.fallback_used
    assert decision.hold_duration_ms == 3000


def test_unenabled_camera_is_never_selected() -> None:
    """软件未启用的 camera 永远不能被 Director Rule 选择。"""

    available = {"medium_shot": ["sheet_01_me_A"], "close_shot": ["sheet_01_cl_A"]}
    _register_match(available=available, current_camera_id="sheet_01_me_A")
    decision = DirectorService().decide(_context("magnetic_2"))
    assert decision.camera_id == "sheet_01_me_A"
    assert decision.camera_id != "sheet_01_house_B"
    assert decision.fallback_used
    assert decision.hold_previous


def test_unknown_direction_without_current_uses_stable_fallback() -> None:
    """UNKNOWN 且没有当前镜头时，应稳定选择一个已启用镜头。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id=None)
    decision = DirectorService().decide(_context("touch", direction="UNKNOWN", source_end=None, target_end=None))
    assert decision.camera_id == "sheet_01_cl_A"
    assert decision.reason == "direction_unknown"
    assert decision.fallback_used
    assert not decision.hold_previous


def test_no_available_camera_returns_empty_hold_decision() -> None:
    """没有任何可用 camera 时不能抛异常，应返回空镜头决策。"""

    _register_match(available={}, current_camera_id=None)
    decision = DirectorService().decide(_context("touch"))
    assert decision.camera_id is None
    assert decision.camera_role is None
    assert decision.install_end is None
    assert decision.reason == "no_available_camera"
    assert decision.fallback_used
    assert decision.hold_previous
    assert decision.hold_duration_ms == 0


def test_camera_metadata_does_not_depend_on_camera_id_text() -> None:
    """规则通过 metadata 判断角色和端位，不解析 camera_id 命名。"""

    config = _FakeConfigManager({"camera_without_end_name": _FakeCamera("camera_without_end_name", "close_shot", "B")})
    service = DirectorRuleService(config)
    decision = service.decide(
        _context("touch"),
        {"close_shot": ["camera_without_end_name"]},
        current_camera_id=None,
    )
    assert decision.camera_id == "camera_without_end_name"
    assert decision.camera_role == "close_shot"
    assert decision.install_end == "B"
    assert decision.reason == "touch_target_close"


def test_multi_match_sheet_camera_state_isolated() -> None:
    """多个 match/sheet 同时存在时，DirectorDecision 不应串改 current_camera_id。"""

    _register_match("match_a", "sheet_01", available=_available_sheet_01(house_b=True), current_camera_id=None)
    _register_match(
        "match_b",
        "sheet_02",
        available={
            "medium_shot": ["sheet_02_me_A", "sheet_02_me_B"],
            "close_shot": ["sheet_02_cl_A", "sheet_02_cl_B"],
            "house_top": ["sheet_02_house_A"],
        },
        current_camera_id=None,
    )
    service = DirectorService()
    a = service.decide(_pre_context(match_id="match_a", sheet_id="sheet_01"))
    b = service.decide(_pre_context(match_id="match_b", sheet_id="sheet_02", direction="B_TO_A", source_end="B", target_end="A"))
    assert a.camera_id == "sheet_01_cl_B"
    assert b.camera_id == "sheet_02_cl_A"
    assert runtime_manager.get_match("match_a").sheets["sheet_01"].current_camera_id == "sheet_01_cl_B"
    assert runtime_manager.get_match("match_b").sheets["sheet_02"].current_camera_id == "sheet_02_cl_A"


def test_context_sheet_mismatch_is_rejected() -> None:
    """context 指向非本 match 绑定赛道时必须拒绝，避免串台。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id=None)
    with pytest.raises(ValueError):
        DirectorService().decide(_context("touch", sheet_id="sheet_02"))


def test_real_touch_unknown_then_departure_a_to_b_uses_target_close() -> None:
    """真实 touch 阶段方向未知时保持初始镜头，departure 后切 target close。"""

    sheet = DirectorService().start_sheet("match_init_a", "sheet_01", _available_sheet_01(house_b=True))
    runtime_manager.create_match(
        MatchRuntime(
            match_id="match_init_a",
            sheet_id="sheet_01",
            scene_type="competition",
            start_time="2026-08-21T10:00:00+08:00",
            sheets={"sheet_01": sheet},
        )
    )
    assert sheet.current_camera_id == "sheet_01_house_B"

    service = DirectorService()
    touch = service.decide(_context("touch", match_id="match_init_a", direction="UNKNOWN", source_end=None, target_end=None))
    assert touch.camera_id == "sheet_01_house_B"
    assert touch.reason == "direction_unknown"
    assert touch.hold_previous

    departure = service.decide(_context("departure", match_id="match_init_a", direction="A_TO_B", source_end="A", target_end="B"))
    assert departure.camera_id == "sheet_01_cl_B"
    assert departure.reason == "departure_target_close"
    assert not departure.hold_previous


def test_real_touch_unknown_then_departure_b_to_a_uses_target_close() -> None:
    """B_TO_A 不在 touch 预知方向，departure 后切 A 端 target close。"""

    sheet = DirectorService().start_sheet("match_init_b", "sheet_01", _available_sheet_01(house_a=True, house_b=False))
    runtime_manager.create_match(
        MatchRuntime(
            match_id="match_init_b",
            sheet_id="sheet_01",
            scene_type="competition",
            start_time="2026-08-21T10:00:00+08:00",
            sheets={"sheet_01": sheet},
        )
    )
    assert sheet.current_camera_id == "sheet_01_house_A"

    service = DirectorService()
    touch = service.decide(_context("touch", match_id="match_init_b", direction="UNKNOWN", source_end=None, target_end=None))
    assert touch.camera_id == "sheet_01_house_A"
    assert touch.reason == "direction_unknown"
    assert touch.hold_previous

    departure = service.decide(_context("departure", match_id="match_init_b", direction="B_TO_A", source_end="B", target_end="A"))
    assert departure.camera_id == "sheet_01_cl_A"
    assert departure.reason == "departure_target_close"
    assert not departure.hold_previous


def test_hold_duration_ms_table_and_no_sleep_in_director_code() -> None:
    """hold_duration_ms 只是决策声明，不能通过 sleep/timer 执行。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id=None)
    service = DirectorService()
    assert service.decide(_pre_context()).hold_duration_ms == 0
    for event_type in ("touch", "departure", "magnetic_1", "alarm", "magnetic_2"):
        assert service.decide(_context(event_type)).hold_duration_ms == 0
    assert service.decide(_context("stop")).hold_duration_ms == 3000

    source = Path("app/services/director_service.py").read_text(encoding="utf-8") + Path("app/services/director_rule_service.py").read_text(encoding="utf-8")
    assert "sleep(3" not in source
    assert "sleep(3000" not in source
    assert "Timer(" not in source
    assert "asyncio.sleep" not in source


def test_initial_camera_behavior_is_unchanged() -> None:
    """start_sheet 初始镜头仍保持 house_top -> medium_shot -> close_shot 的优先级。"""

    director = DirectorService()
    assert director.start_sheet("m_house", "sheet_01", _available_sheet_01(house_b=True)).current_camera_id == "sheet_01_house_B"
    assert director.start_sheet("m_medium", "sheet_01", _available_sheet_01(house_b=False)).current_camera_id == "sheet_01_me_A"
    assert director.start_sheet("m_close", "sheet_01", {"close_shot": ["sheet_01_cl_A"]}).current_camera_id == "sheet_01_cl_A"


def test_replay_register_match_uses_formal_start_sheet_initial_camera() -> None:
    """Phase 6 Replay 注册 match 时复用 start_sheet，不根据未来方向预置 cl_A/cl_B。"""

    from scripts.phase6_director_replay import FULL_CAMERAS_HOUSE_A, FULL_CAMERAS_HOUSE_B, NO_HOUSE_CAMERAS, register_match

    director = DirectorService()
    register_match("replay_initial_a", FULL_CAMERAS_HOUSE_B, director)
    assert runtime_manager.get_match("replay_initial_a").sheets["sheet_01"].current_camera_id == "sheet_01_house_B"
    runtime_manager.remove_match("replay_initial_a")

    register_match("replay_initial_b", FULL_CAMERAS_HOUSE_A, director)
    assert runtime_manager.get_match("replay_initial_b").sheets["sheet_01"].current_camera_id == "sheet_01_house_A"
    runtime_manager.remove_match("replay_initial_b")

    register_match("replay_initial_no_house", NO_HOUSE_CAMERAS, director)
    assert runtime_manager.get_match("replay_initial_no_house").sheets["sheet_01"].current_camera_id == "sheet_01_me_A"


def test_replay_builds_synthetic_direction_locked_without_fake_touch() -> None:
    """Phase 6 Replay 单独构造 pre-shot direction_locked，不修改 Phase 5 事件。"""

    from scripts.phase6_director_replay import pre_shot_context

    context = pre_shot_context("m_replay", "A_TO_B", "A", "B")
    assert isinstance(context, PreShotDirectorContext)
    assert context.event_type == "direction_locked"
    assert "shot_id" not in context.model_dump()
