"""电子冰壶定位点内存缓存。

PositionCache 只保存每个 sheet_id + tag_id 最近有限个定位点，不做方向判断，也不写数据库。
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic_ns

from app.core.config import get_settings
from app.models.stone import StonePosition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedPosition:
    """缓存中的定位点，分离设备 source_time 与服务端 received_at_ms。"""

    position: StonePosition
    received_at_ms: int


class PositionCache:
    """按 sheet_id + tag_id 隔离的有限内存定位缓存。"""

    def __init__(self, max_size: int | None = None) -> None:
        configured_size = max_size if max_size is not None else get_settings().position_cache_size
        self.max_size = max(1, int(configured_size))
        self._items: dict[tuple[str, str], deque[CachedPosition]] = defaultdict(lambda: deque(maxlen=self.max_size))

    def add(self, position: StonePosition, *, received_at_ms: int | None = None) -> bool:
        """写入定位点；连续完全重复的点会被忽略。"""

        key = self._key(position.sheet_id, position.tag_id)
        bucket = self._items[key]
        if bucket and self._same_position(bucket[-1].position, position):
            return False
        if bucket and position.timestamp < bucket[-1].position.timestamp:
            logger.warning(
                "out-of-order position accepted sheet_id=%s tag_id=%s previous_source_time=%s source_time=%s",
                position.sheet_id,
                position.tag_id,
                bucket[-1].position.timestamp,
                position.timestamp,
            )
        bucket.append(CachedPosition(position=position, received_at_ms=received_at_ms or self._now_ms()))
        return True

    def get_latest(self, sheet_id: str, tag_id: str) -> CachedPosition | None:
        """返回最新收到的有效定位点。"""

        bucket = self._items.get(self._key(sheet_id, tag_id))
        if not bucket:
            return None
        return bucket[-1]

    def get_recent(self, sheet_id: str, tag_id: str, limit: int | None = None) -> list[CachedPosition]:
        """返回最近若干个定位点；latest 的定义是最近收到，不按 source_time 重排。"""

        bucket = self._items.get(self._key(sheet_id, tag_id))
        if not bucket:
            return []
        items = list(bucket)
        if limit is None:
            return items
        return items[-max(0, limit):]

    def clear_tag(self, sheet_id: str, tag_id: str) -> None:
        """清理单颗冰壶的定位缓存。"""

        self._items.pop(self._key(sheet_id, tag_id), None)

    def clear_sheet(self, sheet_id: str) -> None:
        """清理某条赛道下所有冰壶定位缓存。"""

        for key in list(self._items):
            if key[0] == sheet_id:
                self._items.pop(key, None)

    def clear(self) -> None:
        """清理全部定位缓存，主要用于测试和重放脚本。"""

        self._items.clear()

    def _key(self, sheet_id: str, tag_id: str) -> tuple[str, str]:
        """统一缓存 key，避免跨赛道同 tag 污染。"""

        return (sheet_id, tag_id)

    def _same_position(self, left: StonePosition, right: StonePosition) -> bool:
        """判断连续点是否完全重复。"""

        return (
            left.sheet_id == right.sheet_id
            and left.lane_id == right.lane_id
            and left.tag_id == right.tag_id
            and left.timestamp == right.timestamp
            and left.x == right.x
            and left.y == right.y
        )

    def _now_ms(self) -> int:
        """使用单调时钟记录服务端收到时间，避免混用设备 source_time。"""

        return monotonic_ns() // 1_000_000


position_cache = PositionCache()
# 进程内默认缓存实例；真实自动消费尚未接入，测试和 Replay 可按需直接实例化。
