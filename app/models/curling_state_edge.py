"""冰壶 type=4 stoneState 协议边沿模型。

Phase 7.3 只描述 WebSocket 状态第一次进入的协议边沿，不等同于后续业务事件模型，
也不直接生成后续导播或投壶生命周期业务事件。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class StoneStateEdgeType(StrEnum):
    """type=4 stoneState 第一次进入时产生的协议边沿类型。"""

    START_ENTERED = "start_entered"
    HOGLINE1_ENTERED = "hogline1_entered"
    HOGLINE2_ENTERED = "hogline2_entered"
    END_ENTERED = "end_entered"


class StoneStateEdge(BaseModel):
    """一次 stoneState 状态转移产生的协议层 Edge。

    timing 字段保留接口原始值，只作为诊断和后续语义层输入；Phase 7.3 不做秒换算，
    也不根据 timing 反推绝对事件时间。
    """

    edge_type: StoneStateEdgeType
    lane_id: str
    moving_stone_tag_id: str
    previous_state: str | None = None
    current_state: str
    received_at_ms: int
    hog_line_1_timing: int | float | str | None = None
    hog_line_2_timing: int | float | str | None = None
    total_timing: int | float | str | None = None
