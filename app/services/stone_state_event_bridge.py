"""StoneStateEdge 到 Phase 5 Shot 生命周期的桥接服务。

本服务只消费 Phase 7.3 StoneStateEdge：解析 State/Trigger lane、查找当前 running match，
再把一条 Edge 映射为一条 Phase 5 TriggerEvent。它不读取 Phase 7.2 方向锁，不比较 tag，
不调用 Director，也不连接真实 WebSocket。
"""

from __future__ import annotations

import logging

from app.core.config import ConfigManager, get_config_manager
from app.core.enums import RuntimeStatus
from app.core.runtime import RuntimeManager, runtime_manager
from app.models.curling_state_edge import StoneStateEdge, StoneStateEdgeType
from app.models.event import TriggerEvent
from app.models.shot import ShotEventContext
from app.models.stone_state_semantic import StoneStateSemanticEvent, StoneStateBusinessEventType
from app.services.stone_event_service import StoneEventService

logger = logging.getLogger(__name__)

# Phase 7.4 唯一 Edge -> Business Event 映射表；禁止在其他地方重复写分支。
EDGE_TO_BUSINESS_EVENT: dict[StoneStateEdgeType, StoneStateBusinessEventType] = {
    StoneStateEdgeType.START_ENTERED: "departure",
    StoneStateEdgeType.HOGLINE1_ENTERED: "magnetic_1",
    StoneStateEdgeType.HOGLINE2_ENTERED: "magnetic_2",
    StoneStateEdgeType.END_ENTERED: "stop",
}


class StoneStateEventBridge:
    """把 type=4 状态边沿转成 Phase 5 可消费的业务事件。"""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        runtime_registry: RuntimeManager | None = None,
        stone_event_service: StoneEventService | None = None,
    ) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._runtime_registry = runtime_registry or runtime_manager
        self._stone_event_service = stone_event_service or StoneEventService()

    def convert(self, edge: StoneStateEdge) -> StoneStateSemanticEvent | None:
        """解析 lane 与 running match，生成保留 tag/timing 的语义事件。"""

        event_type = EDGE_TO_BUSINESS_EVENT.get(edge.edge_type)
        if event_type is None:
            logger.warning("stone state edge ignored because edge_type is unsupported edge_type=%s", edge.edge_type)
            return None
        try:
            # type=4 laneId 属于 State/Trigger 业务 lane，绝不使用 position lane helper。
            sheet_id = self._config_manager.get_sheet_id_by_trigger_lane(edge.lane_id)
        except KeyError:
            logger.warning("stone state edge ignored because state lane is unknown lane_id=%s", edge.lane_id)
            return None

        match_id = self._resolve_running_match_id(sheet_id)
        if match_id is None:
            return None

        semantic = StoneStateSemanticEvent(
            match_id=match_id,
            sheet_id=sheet_id,
            lane_id=edge.lane_id,
            moving_stone_tag_id=edge.moving_stone_tag_id,
            edge_type=edge.edge_type,
            event_type=event_type,
            timestamp=edge.received_at_ms,
            received_at_ms=edge.received_at_ms,
            hog_line_1_timing=edge.hog_line_1_timing,
            hog_line_2_timing=edge.hog_line_2_timing,
            total_timing=edge.total_timing,
        )
        logger.debug(
            "stone state semantic event match_id=%s sheet_id=%s lane_id=%s tag_id=%s edge_type=%s event_type=%s",
            semantic.match_id,
            semantic.sheet_id,
            semantic.lane_id,
            semantic.moving_stone_tag_id,
            semantic.edge_type.value,
            semantic.event_type,
        )
        return semantic

    def dispatch(self, event: StoneStateSemanticEvent) -> ShotEventContext | None:
        """把语义事件转成现有 Phase 5 TriggerEvent，并交给 StoneEventService。"""

        trigger = TriggerEvent(
            sheet_id=event.sheet_id,
            lane_id=event.lane_id,
            timestamp=event.timestamp,
            event_type=event.event_type,
        )
        try:
            context = self._stone_event_service.process_trigger_event(trigger, match_id=event.match_id)
        except Exception:  # noqa: BLE001 - 桥接层需要把 Phase 5 dispatch 异常记录清楚后继续向上抛。
            logger.exception("stone state semantic dispatch failed match_id=%s sheet_id=%s event_type=%s", event.match_id, event.sheet_id, event.event_type)
            raise
        if isinstance(context, ShotEventContext):
            return context
        return None

    def process(self, edge: StoneStateEdge) -> ShotEventContext | None:
        """一步完成 Edge -> Semantic Event -> Phase 5 dispatch。"""

        semantic = self.convert(edge)
        if semantic is None:
            return None
        return self.dispatch(semantic)

    def _resolve_running_match_id(self, sheet_id: str) -> str | None:
        """只从 RuntimeManager 查找当前 running match，不查历史数据库、不使用 type=1/2。"""

        matches = [
            match
            for match in self._runtime_registry.list_matches()
            if match.sheet_id == sheet_id and match.status == RuntimeStatus.RUNNING.value
        ]
        if not matches:
            logger.debug("stone state edge ignored because no running match sheet_id=%s", sheet_id)
            return None
        if len(matches) > 1:
            logger.error("stone state edge ignored because multiple running matches sheet_id=%s match_ids=%s", sheet_id, [match.match_id for match in matches])
            return None
        return matches[0].match_id
