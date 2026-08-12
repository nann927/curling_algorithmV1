"""投壶方向判断服务。

Phase 4 一期规则：
- TriggerEvent 负责 touch/departure/stop 等投壶事件；
- StonePosition 只在 touch→departure 窗口内用于判断 A/B 发球区；
- 不根据 Position 推断运动、入营、停止、碰撞或速度。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import ConfigManager, get_config_manager, get_settings
from app.core.enums import DirectionStatus
from app.models.stone import StonePosition


UNKNOWN_DIRECTION = "UNKNOWN"


@dataclass
class DirectionState:
    """单条赛道的方向检测状态。

    DirectionService 自己维护临时状态，Runtime 只保存对外有用的摘要字段。
    """

    sheet_id: str
    status: str = DirectionStatus.UNKNOWN.value
    candidate_source_end: str | None = None
    source_end: str | None = None
    target_end: str | None = None
    direction: str = UNKNOWN_DIRECTION
    last_position: StonePosition | None = None
    confirm_count: int = 0
    last_update_time: int | None = None


class DirectionService:
    """touch→departure 方向预判服务。"""

    def __init__(
        self,
        *,
        confirm_count: int | None = None,
        max_position_age_ms: int | None = None,
        direction_zones_by_sheet: dict[str, dict[str, Any]] | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self._settings = get_settings()
        direction_config = self._settings.system_config.get("direction_detection", {})
        self._confirm_count = confirm_count or int(direction_config.get("confirm_count", 3))
        self._max_position_age_ms = max_position_age_ms or int(direction_config.get("max_position_age_ms", 1000))
        self._direction_zones_by_sheet = direction_zones_by_sheet or {}
        self._config_manager = config_manager or get_config_manager()
        self._states: dict[str, DirectionState] = {}

    def start_monitoring(self, sheet_id: str) -> DirectionState:
        """touch 到达后开启方向检测窗口。"""

        state = DirectionState(sheet_id=sheet_id, status=DirectionStatus.DETECTING.value)
        self._states[sheet_id] = state
        return state

    def update_position(self, position: StonePosition) -> DirectionState:
        """持续接收定位数据并做轻量稳定确认。

        UNKNOWN 抖动不会清空已有候选方向；LOCKED/FROZEN 后不会被后续定位随意改写。
        """

        state = self._states.get(position.sheet_id)
        if state is None:
            state = DirectionState(sheet_id=position.sheet_id)
            self._states[position.sheet_id] = state
        if state.status in (DirectionStatus.LOCKED.value, DirectionStatus.FROZEN.value):
            state.last_position = position
            state.last_update_time = position.timestamp
            return state
        if state.status != DirectionStatus.DETECTING.value:
            return state

        state.last_position = position
        state.last_update_time = position.timestamp
        source_end = self._classify_source_end(position)
        if source_end is None:
            return state

        if state.candidate_source_end == source_end:
            state.confirm_count += 1
        else:
            state.candidate_source_end = source_end
            state.confirm_count = 1

        if state.confirm_count >= self._confirm_count:
            self._lock_state(state, source_end)
        return state

    def get_direction(self, sheet_id: str) -> DirectionState:
        """读取指定赛道当前方向状态。"""

        return self._states.get(sheet_id) or DirectionState(sheet_id=sheet_id)

    def freeze_direction(self, sheet_id: str, timestamp: int | None = None) -> DirectionState:
        """departure 到达时冻结本次投壶方向。"""

        state = self._states.get(sheet_id) or DirectionState(sheet_id=sheet_id)
        self._states[sheet_id] = state
        if state.status == DirectionStatus.LOCKED.value:
            state.status = DirectionStatus.FROZEN.value
            return state

        source_end = self._classify_last_position_for_departure(state, timestamp)
        if source_end is not None:
            self._lock_state(state, source_end)
        else:
            state.source_end = None
            state.target_end = None
            state.direction = UNKNOWN_DIRECTION
        state.status = DirectionStatus.FROZEN.value
        return state

    def reset(self, sheet_id: str) -> DirectionState:
        """显式重置赛道方向状态。"""

        state = DirectionState(sheet_id=sheet_id)
        self._states[sheet_id] = state
        return state

    def _lock_state(self, state: DirectionState, source_end: str) -> None:
        """锁定 A_TO_B 或 B_TO_A。"""

        target_end = "B" if source_end == "A" else "A"
        state.source_end = source_end
        state.target_end = target_end
        state.direction = f"{source_end}_TO_{target_end}"
        state.status = DirectionStatus.LOCKED.value

    def _classify_last_position_for_departure(self, state: DirectionState, timestamp: int | None) -> str | None:
        """departure 时未 LOCKED 的降级判断。"""

        if state.last_position is None:
            return None
        if timestamp is not None and timestamp - state.last_position.timestamp > self._max_position_age_ms:
            return None
        return self._classify_source_end(state.last_position)

    def _classify_source_end(self, position: StonePosition) -> str | None:
        """判断当前定位是否落在 A/B 发球区。"""

        zones = self._get_direction_zones(position.sheet_id)
        for end in ("A", "B"):
            zone = zones.get(end)
            if self._position_in_zone(position, zone):
                return end
        return None

    def _get_direction_zones(self, sheet_id: str) -> dict[str, Any]:
        """读取方向区域；测试可注入，现场默认来自 site_config。"""

        if sheet_id in self._direction_zones_by_sheet:
            return self._direction_zones_by_sheet[sheet_id]
        return self._config_manager.get_direction_zones(sheet_id)

    def _position_in_zone(self, position: StonePosition, zone: dict[str, Any] | None) -> bool:
        """判断点是否在矩形区域内；区域为 null 时返回 UNKNOWN。"""

        if not zone:
            return False
        bounds = ("x_min", "x_max", "y_min", "y_max")
        if any(zone.get(key) is None for key in bounds):
            return False
        return (
            float(zone["x_min"]) <= position.x <= float(zone["x_max"])
            and float(zone["y_min"]) <= position.y <= float(zone["y_max"])
        )
