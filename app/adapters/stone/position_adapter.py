"""真实 type=3 轨迹消息到标准 StonePosition 的适配器。

本模块只做 laneId 映射和字段标准化，不判断方向，也不调用后续业务服务。
"""

from __future__ import annotations

import logging

from app.core.config import ConfigManager, get_config_manager
from app.models.curling_raw import RawCurlingMessage, TrajectoryRawMessage
from app.models.stone import StonePosition
from app.services.position_cache import PositionCache

logger = logging.getLogger(__name__)


class TrajectoryPositionAdapter:
    """把 Phase 7.0 Raw type=3 消息转换为内部标准 Position。"""

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager or get_config_manager()

    def convert(self, message: RawCurlingMessage) -> list[StonePosition]:
        """转换单条 Raw 消息；非 type=3 或无效点返回空列表。"""

        if not isinstance(message, TrajectoryRawMessage):
            return []

        positions: list[StonePosition] = []
        for point in message.trajectory_data:
            lane_id = self._effective_lane_id(message.lane_id, point.lane_id)
            if lane_id is None:
                continue
            if point.tag_id is None or point.time is None or point.x is None or point.y is None:
                logger.warning("malformed trajectory point ignored lane_id=%s", lane_id)
                continue
            try:
                sheet_id = self._config_manager.get_sheet_id_by_position_lane(lane_id)
            except KeyError:
                logger.warning("unknown position lane ignored lane_id=%s", lane_id)
                continue
            positions.append(
                StonePosition(
                    sheet_id=sheet_id,
                    lane_id=lane_id,
                    tag_id=point.tag_id,
                    # timestamp 保存设备原始 time，不做单位换算；received_at 由 PositionCache 单独维护。
                    timestamp=int(point.time),
                    x=float(point.x),
                    y=float(point.y),
                )
            )
        return positions

    def add_to_cache(self, message: RawCurlingMessage, cache: PositionCache) -> list[StonePosition]:
        """转换 type=3 消息并写入 PositionCache，返回实际转换出的标准 Position。"""

        positions = self.convert(message)
        for position in positions:
            cache.add(position)
        return positions

    def _effective_lane_id(self, outer_lane_id: str | None, inner_lane_id: str | None) -> str | None:
        """处理外层 laneId 与 trajectoryData 内层 laneId 的一致性。"""

        if outer_lane_id and inner_lane_id and outer_lane_id != inner_lane_id:
            logger.warning("position lane mismatch ignored outer_lane_id=%s inner_lane_id=%s", outer_lane_id, inner_lane_id)
            return None
        lane_id = outer_lane_id or inner_lane_id
        if not lane_id:
            logger.warning("position lane missing ignored")
            return None
        return lane_id
