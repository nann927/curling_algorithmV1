"""预投壶方向锁定服务。

Phase 7.2 只消费 Phase 7.1 PositionCache 中的定位点，结合现场 Ready Zone 标定生成
PreShotDirectorContext；本服务不调用 DirectorService、不处理 type=4，也不创建 Shot。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic_ns

from app.core.config import ConfigManager, CoordinateBoundsConfig, get_config_manager, get_settings
from app.models.director import PreShotDirectorContext
from app.models.stone import StonePosition
from app.services.position_cache import CachedPosition, PositionCache, position_cache

logger = logging.getLogger(__name__)

# Ready Zone 到正式投掷方向的唯一映射点，避免业务规则散落在多个文件中。
READY_ZONE_DIRECTION_MAP = {
    "A": {"direction": "A_TO_B", "source_end": "A", "target_end": "B"},
    "B": {"direction": "B_TO_A", "source_end": "B", "target_end": "A"},
}


@dataclass(frozen=True)
class PreShotDirectionLock:
    """单个 match_id + sheet_id 的预投方向锁定状态。"""

    match_id: str
    sheet_id: str
    candidate_tag_id: str
    direction: str
    source_end: str
    target_end: str
    locked_at: int


class PreShotDirectionService:
    """根据最近连续定位点判断待投冰壶方向。

    该服务只返回 PreShotDirectorContext 或 None；未来由 WebSocket Consumer / Coordinator
    决定是否把 context 交给 DirectorService.decide()。
    """

    def __init__(
        self,
        cache: PositionCache | None = None,
        config_manager: ConfigManager | None = None,
        *,
        position_freshness_ms: int | None = None,
        direction_confirm_count: int | None = None,
    ) -> None:
        settings = get_settings()
        self._cache = cache or position_cache
        self._config_manager = config_manager or get_config_manager()
        self.position_freshness_ms = int(position_freshness_ms if position_freshness_ms is not None else settings.position_freshness_ms)
        self.direction_confirm_count = int(direction_confirm_count if direction_confirm_count is not None else settings.direction_confirm_count)
        if self.position_freshness_ms <= 0:
            raise ValueError("position_freshness_ms must be greater than 0")
        if self.direction_confirm_count < 1:
            raise ValueError("direction_confirm_count must be greater than or equal to 1")
        self._locks: dict[tuple[str, str], PreShotDirectionLock] = {}

    def evaluate(
        self,
        match_id: str,
        sheet_id: str,
        tag_id: str,
        *,
        now_ms: int | None = None,
    ) -> PreShotDirectorContext | None:
        """检查某颗冰壶最近连续定位点，满足 Ready Zone 条件时生成 direction_locked。"""

        lock_key = self._lock_key(match_id, sheet_id)
        if lock_key in self._locks:
            return None

        calibration = self._config_manager.get_position_calibration(sheet_id)
        if not calibration.enabled:
            return None

        recent = self._cache.get_recent(sheet_id, tag_id, limit=self.direction_confirm_count)
        if len(recent) < self.direction_confirm_count:
            return None

        effective_now_ms = now_ms if now_ms is not None else self._now_ms()
        if any(not self._is_fresh(item, effective_now_ms) for item in recent):
            return None

        zone_name = self._confirmed_zone([item.position for item in recent], calibration.ready_zones)
        if zone_name is None:
            return None

        rule = READY_ZONE_DIRECTION_MAP[zone_name]
        latest_position = recent[-1].position
        lock = PreShotDirectionLock(
            match_id=match_id,
            sheet_id=sheet_id,
            candidate_tag_id=tag_id,
            direction=rule["direction"],
            source_end=rule["source_end"],
            target_end=rule["target_end"],
            locked_at=effective_now_ms,
        )
        self._locks[lock_key] = lock
        logger.info(
            "pre-shot direction locked match_id=%s sheet_id=%s candidate_tag_id=%s direction=%s source_end=%s target_end=%s",
            match_id,
            sheet_id,
            tag_id,
            lock.direction,
            lock.source_end,
            lock.target_end,
        )
        return PreShotDirectorContext(
            match_id=match_id,
            sheet_id=sheet_id,
            event_type="direction_locked",
            timestamp=latest_position.timestamp,
            direction=lock.direction,
            source_end=lock.source_end,
            target_end=lock.target_end,
            candidate_tag_id=tag_id,
        )

    def reset(self, match_id: str, sheet_id: str) -> None:
        """显式释放一次 match + sheet 的预投方向锁，供未来一次 Shot 结束后调用。"""

        self._locks.pop(self._lock_key(match_id, sheet_id), None)

    def clear_match(self, match_id: str) -> None:
        """清理某个 match_id 下的全部预投方向锁。"""

        for key in list(self._locks):
            if key[0] == match_id:
                self._locks.pop(key, None)

    def clear(self) -> None:
        """清理全部预投方向锁，主要用于测试和 Replay。"""

        self._locks.clear()

    def get_lock(self, match_id: str, sheet_id: str) -> PreShotDirectionLock | None:
        """读取当前锁状态；只用于测试和诊断，不驱动业务分支。"""

        return self._locks.get(self._lock_key(match_id, sheet_id))

    def _confirmed_zone(self, positions: list[StonePosition], ready_zones: dict[str, CoordinateBoundsConfig | None]) -> str | None:
        """判断最近 N 个点是否全部落在同一个完整 Ready Zone。"""

        matched_zones: list[str] = []
        for position in positions:
            zones = [zone_name for zone_name in ("A", "B") if self._contains(ready_zones.get(zone_name), position)]
            if len(zones) != 1:
                if len(zones) > 1:
                    logger.debug("ambiguous ready zone ignored sheet_id=%s tag_id=%s", position.sheet_id, position.tag_id)
                return None
            matched_zones.append(zones[0])
        first = matched_zones[0]
        if all(zone == first for zone in matched_zones):
            return first
        return None

    def _contains(self, zone: CoordinateBoundsConfig | None, position: StonePosition) -> bool:
        """使用 inclusive 矩形边界判断点是否属于 Ready Zone；不完整配置一律不可用。"""

        if zone is None:
            return False
        if zone.x_min is None or zone.x_max is None or zone.y_min is None or zone.y_max is None:
            return False
        return zone.x_min <= position.x <= zone.x_max and zone.y_min <= position.y <= zone.y_max

    def _is_fresh(self, item: CachedPosition, now_ms: int) -> bool:
        """freshness 只使用服务端 received_at_ms，不使用设备 source_time。"""

        return now_ms - item.received_at_ms <= self.position_freshness_ms

    def _lock_key(self, match_id: str, sheet_id: str) -> tuple[str, str]:
        """预投方向锁按 match_id + sheet_id 隔离。"""

        return (match_id, sheet_id)

    def _now_ms(self) -> int:
        """使用与 PositionCache 一致的 monotonic 时钟体系。"""

        return monotonic_ns() // 1_000_000
