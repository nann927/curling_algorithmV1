"""Phase 6 Director Rule V1 测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.director import DirectorDecision
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


def test_director_decision_model_fields() -> None:
    """DirectorDecision 模型应包含 Phase 6 需要的业务字段。"""

    decision = DirectorDecision(
        match_id="m1",
        sheet_id="sheet_01",
        shot_id="shot_1",
        event_type="touch",
        timestamp=1000,
        direction="A_TO_B",
        source_end="A",
        target_end="B",
        camera_id="sheet_01_cl_A",
        camera_role="close_shot",
        install_end="A",
        reason="touch_source_close",
        fallback_used=False,
        hold_previous=False,
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
    }.issubset(data)
    assert decision.camera_id == "sheet_01_cl_A"


def test_a_to_b_happy_path_and_hold() -> None:
    """A_TO_B 应自然选择 A 端出手镜头、B 端目标镜头，并在相同镜头时 hold。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id=None)
    service = DirectorService()

    touch = service.decide(_context("touch", timestamp=1000))
    assert touch.camera_id == "sheet_01_cl_A"
    assert touch.camera_role == "close_shot"
    assert touch.install_end == "A"
    assert touch.reason == "touch_source_close"
    assert not touch.fallback_used
    assert not touch.hold_previous

    departure = service.decide(_context("departure", timestamp=1400))
    assert departure.camera_id == "sheet_01_me_A"
    assert departure.reason == "departure_source_medium"
    assert not departure.hold_previous

    magnetic_1 = service.decide(_context("magnetic_1", timestamp=1500))
    assert magnetic_1.camera_id == "sheet_01_me_A"
    assert magnetic_1.reason == "magnetic1_source_medium"
    assert magnetic_1.hold_previous

    magnetic_2 = service.decide(_context("magnetic_2", timestamp=1600))
    assert magnetic_2.camera_id == "sheet_01_me_B"
    assert not magnetic_2.hold_previous

    stop = service.decide(_context("stop", timestamp=1700))
    assert stop.camera_id == "sheet_01_house_B"
    assert stop.camera_role == "house_top"
    assert stop.install_end == "B"
    assert stop.reason == "stop_target_house"


def test_b_to_a_mirror_path() -> None:
    """B_TO_A 使用同一套 source_end/target_end 规则完成镜像。"""

    _register_match(available=_available_sheet_01(house_a=True, house_b=False), current_camera_id=None)
    service = DirectorService()
    common = {"direction": "B_TO_A", "source_end": "B", "target_end": "A"}

    assert service.decide(_context("touch", **common)).camera_id == "sheet_01_cl_B"
    assert service.decide(_context("departure", **common)).camera_id == "sheet_01_me_B"
    magnetic_1 = service.decide(_context("magnetic_1", **common))
    assert magnetic_1.camera_id == "sheet_01_me_B"
    assert magnetic_1.hold_previous
    assert service.decide(_context("magnetic_2", **common)).camera_id == "sheet_01_me_A"
    stop = service.decide(_context("stop", **common))
    assert stop.camera_id == "sheet_01_house_A"
    assert stop.install_end == "A"


def test_alarm_holds_current_camera() -> None:
    """alarm 不主动切镜，已有当前镜头时保持当前 camera。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id="sheet_01_me_A")
    decision = DirectorService().decide(_context("alarm"))
    assert decision.camera_id == "sheet_01_me_A"
    assert decision.reason == "alarm_hold_current_camera"
    assert decision.hold_previous
    assert not decision.fallback_used


def test_stop_falls_back_to_target_medium_when_house_not_enabled() -> None:
    """house_top 未显式启用时，stop 不得从 site_config 偷用 house camera。"""

    _register_match(available=_available_sheet_01(house_a=False, house_b=False), current_camera_id=None)
    decision = DirectorService().decide(_context("stop"))
    assert decision.camera_id == "sheet_01_me_B"
    assert decision.camera_role == "medium_shot"
    assert decision.install_end == "B"
    assert decision.fallback_used
    assert decision.reason == "preferred_camera_unavailable"


def test_unenabled_target_end_does_not_use_site_config_camera() -> None:
    """只启用 A 端阵列时，A_TO_B 后段不得直接使用未启用的 B 端镜头。"""

    _register_match(available=_available_sheet_01(house_a=False, house_b=False, overview_a=True, overview_b=False), current_camera_id="sheet_01_me_A")
    decision = DirectorService().decide(_context("magnetic_2"))
    assert decision.camera_id == "sheet_01_me_A"
    assert decision.install_end == "A"
    assert decision.fallback_used
    assert decision.hold_previous


def test_unknown_direction_is_safe_and_explainable() -> None:
    """UNKNOWN 方向不得异常，优先保持当前可用镜头。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id="sheet_01_cl_A")
    decision = DirectorService().decide(_context("touch", direction="UNKNOWN", source_end=None, target_end=None))
    assert decision.camera_id == "sheet_01_cl_A"
    assert decision.reason == "direction_unknown"
    assert decision.fallback_used
    assert decision.hold_previous


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


def test_camera_metadata_does_not_depend_on_camera_id_text() -> None:
    """规则通过 metadata 判断角色和端位，不解析 camera_id 命名。"""

    config = _FakeConfigManager({"camera_without_end_name": _FakeCamera("camera_without_end_name", "close_shot", "A")})
    service = DirectorRuleService(config)
    decision = service.decide(
        _context("touch"),
        {"close_shot": ["camera_without_end_name"]},
        current_camera_id=None,
    )
    assert decision.camera_id == "camera_without_end_name"
    assert decision.camera_role == "close_shot"
    assert decision.install_end == "A"
    assert decision.reason == "touch_source_close"


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
    a = service.decide(_context("touch", match_id="match_a", sheet_id="sheet_01"))
    b = service.decide(
        _context("touch", match_id="match_b", sheet_id="sheet_02", direction="B_TO_A", source_end="B", target_end="A")
    )
    assert a.camera_id == "sheet_01_cl_A"
    assert b.camera_id == "sheet_02_cl_B"
    assert runtime_manager.get_match("match_a").sheets["sheet_01"].current_camera_id == "sheet_01_cl_A"
    assert runtime_manager.get_match("match_b").sheets["sheet_02"].current_camera_id == "sheet_02_cl_B"


def test_context_sheet_mismatch_is_rejected() -> None:
    """context 指向非本 match 绑定赛道时必须拒绝，避免串台。"""

    _register_match(available=_available_sheet_01(house_b=True), current_camera_id=None)
    with pytest.raises(ValueError):
        DirectorService().decide(_context("touch", sheet_id="sheet_02"))




def test_real_touch_unknown_holds_initial_then_departure_a_to_b_switches_source_medium() -> None:
    """真实 touch 阶段方向未知时保持初始镜头，departure 冻结方向后再切 source medium。"""

    sheet = DirectorService().start_sheet("match_init_a", "sheet_01", _available_sheet_01(house_b=True))
    match = MatchRuntime(
        match_id="match_init_a",
        sheet_id="sheet_01",
        scene_type="competition",
        start_time="2026-08-21T10:00:00+08:00",
        sheets={"sheet_01": sheet},
    )
    runtime_manager.create_match(match)
    assert sheet.current_camera_id == "sheet_01_house_B"

    service = DirectorService()
    touch = service.decide(_context("touch", match_id="match_init_a", direction="UNKNOWN", source_end=None, target_end=None))
    assert touch.camera_id == "sheet_01_house_B"
    assert touch.reason == "direction_unknown"
    assert touch.fallback_used
    assert touch.hold_previous

    departure = service.decide(_context("departure", match_id="match_init_a", direction="A_TO_B", source_end="A", target_end="B"))
    assert departure.camera_id == "sheet_01_me_A"
    assert departure.reason == "departure_source_medium"
    assert not departure.hold_previous


def test_real_touch_unknown_holds_initial_then_departure_b_to_a_switches_source_medium() -> None:
    """B_TO_A 也不能在 touch 预知方向；departure 后通过 source_end 自然镜像。"""

    sheet = DirectorService().start_sheet("match_init_b", "sheet_01", _available_sheet_01(house_a=True, house_b=False))
    match = MatchRuntime(
        match_id="match_init_b",
        sheet_id="sheet_01",
        scene_type="competition",
        start_time="2026-08-21T10:00:00+08:00",
        sheets={"sheet_01": sheet},
    )
    runtime_manager.create_match(match)
    assert sheet.current_camera_id == "sheet_01_house_A"

    service = DirectorService()
    touch = service.decide(_context("touch", match_id="match_init_b", direction="UNKNOWN", source_end=None, target_end=None))
    assert touch.camera_id == "sheet_01_house_A"
    assert touch.reason == "direction_unknown"
    assert touch.hold_previous

    departure = service.decide(_context("departure", match_id="match_init_b", direction="B_TO_A", source_end="B", target_end="A"))
    assert departure.camera_id == "sheet_01_me_B"
    assert departure.reason == "departure_source_medium"
    assert not departure.hold_previous


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
