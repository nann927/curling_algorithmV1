"""type=4 State Edge 到 Phase 5 业务事件之间的语义事件模型。

该模型保存 movingStoneTagId 与 timing raw snapshot，便于后续 Phase 7.5 做 candidate tag 对齐；
它不是 ShotEventContext，也不直接表达导播决策。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.models.curling_state_edge import StoneStateEdgeType

StoneStateBusinessEventType = Literal["departure", "magnetic_1", "magnetic_2", "stop"]


class StoneStateSemanticEvent(BaseModel):
    """Phase 7.4 语义层事件，承接协议 Edge 与 Phase 5 TriggerEvent。"""

    match_id: str
    sheet_id: str
    lane_id: str
    moving_stone_tag_id: str
    edge_type: StoneStateEdgeType
    event_type: StoneStateBusinessEventType
    timestamp: int
    received_at_ms: int
    hog_line_1_timing: int | float | str | None = None
    hog_line_2_timing: int | float | str | None = None
    total_timing: int | float | str | None = None
