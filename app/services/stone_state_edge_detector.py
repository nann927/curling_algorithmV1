"""type=4 stoneState 协议边沿检测器。

Detector 只把持续重复推送的 StoneStateRawMessage 收敛为状态进入 Edge；本模块不做
lane->sheet 映射，不连接 WebSocket，不调用 Director/Shot/PreShot 等业务服务。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import time_ns

from app.models.curling_raw import RawCurlingMessage, StoneStateRawMessage
from app.models.curling_state_edge import StoneStateEdge, StoneStateEdgeType

logger = logging.getLogger(__name__)

# 协议允许的 stoneState 及其正常顺序。只允许 end -> start 作为下一轮自动循环。
STATE_ORDER = {"start": 0, "hogline1": 1, "hogline2": 2, "end": 3}
EDGE_TYPE_BY_STATE = {
    "start": StoneStateEdgeType.START_ENTERED,
    "hogline1": StoneStateEdgeType.HOGLINE1_ENTERED,
    "hogline2": StoneStateEdgeType.HOGLINE2_ENTERED,
    "end": StoneStateEdgeType.END_ENTERED,
}


@dataclass(frozen=True)
class _TrackedStoneState:
    """单个 lane_id + movingStoneTagId 当前观察到的最新合法状态。"""

    current_state: str


class StoneStateEdgeDetector:
    """检测 type=4 stoneState 的第一次进入边沿。"""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], _TrackedStoneState] = {}

    def detect(
        self,
        message: RawCurlingMessage,
        *,
        received_at_ms: int | None = None,
    ) -> StoneStateEdge | None:
        """把 StoneStateRawMessage 转换为 StoneStateEdge；非 type=4 安全返回 None。"""

        if not isinstance(message, StoneStateRawMessage):
            return None

        lane_id = self._clean_required_value(message.lane_id)
        if lane_id is None:
            logger.warning("stone state ignored because laneId is missing")
            return None
        tag_id = self._clean_required_value(message.moving_stone_tag_id)
        if tag_id is None:
            logger.warning("stone state ignored because movingStoneTagId is missing lane_id=%s", lane_id)
            return None

        current_state = self._canonical_state(message.stone_state)
        if current_state is None:
            logger.warning("stone state ignored because state is unknown lane_id=%s tag_id=%s state=%s", lane_id, tag_id, message.stone_state)
            return None

        key = (lane_id, tag_id)
        previous = self._states.get(key)
        previous_state = previous.current_state if previous is not None else None
        if not self._should_emit(previous_state, current_state):
            return None

        self._states[key] = _TrackedStoneState(current_state=current_state)
        edge = StoneStateEdge(
            edge_type=EDGE_TYPE_BY_STATE[current_state],
            lane_id=lane_id,
            moving_stone_tag_id=tag_id,
            previous_state=previous_state,
            current_state=current_state,
            received_at_ms=received_at_ms if received_at_ms is not None else self._wall_clock_ms(),
            hog_line_1_timing=message.hog_line_1_timing,
            hog_line_2_timing=message.hog_line_2_timing,
            total_timing=message.total_timing,
        )
        logger.debug(
            "stone state edge lane_id=%s tag_id=%s previous_state=%s current_state=%s edge_type=%s",
            lane_id,
            tag_id,
            previous_state,
            current_state,
            edge.edge_type.value,
        )
        return edge

    def reset(self, lane_id: str, moving_stone_tag_id: str) -> None:
        """显式清理单个 lane + tag 的状态跟踪。"""

        self._states.pop((lane_id, moving_stone_tag_id), None)

    def clear_lane(self, lane_id: str) -> None:
        """清理某条 lane 下全部石头状态，不影响其他 lane。"""

        for key in list(self._states):
            if key[0] == lane_id:
                self._states.pop(key, None)

    def clear(self) -> None:
        """清空全部状态跟踪，主要用于测试、重连或人工恢复。"""

        self._states.clear()

    def get_state(self, lane_id: str, moving_stone_tag_id: str) -> str | None:
        """读取当前内部状态；仅用于测试和诊断，不作为业务接口。"""

        state = self._states.get((lane_id, moving_stone_tag_id))
        return state.current_state if state is not None else None

    def _should_emit(self, previous_state: str | None, current_state: str) -> bool:
        """判断当前状态转移是否应产生 Edge，并避免 backward 回退内部状态。"""

        if previous_state is None:
            return True
        if previous_state == current_state:
            logger.debug("duplicate stone state ignored state=%s", current_state)
            return False
        if previous_state == "end" and current_state == "start":
            return True
        if STATE_ORDER[current_state] > STATE_ORDER[previous_state]:
            return True
        logger.debug("backward stone state ignored previous_state=%s current_state=%s", previous_state, current_state)
        return False

    def _canonical_state(self, value: str | None) -> str | None:
        """把协议 state 规整为小写 canonical 值，只接受文档列出的四种状态。"""

        if value is None:
            return None
        state = value.strip().lower()
        if state not in STATE_ORDER:
            return None
        return state

    def _clean_required_value(self, value: str | None) -> str | None:
        """laneId 和 movingStoneTagId 不能为空，避免多个坏数据共享模糊 key。"""

        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _wall_clock_ms(self) -> int:
        """使用 wall-clock epoch milliseconds 记录接收时间，不混用 Phase 7.2 monotonic freshness。"""

        return time_ns() // 1_000_000
