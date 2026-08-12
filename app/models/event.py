"""冰壶事件模型占位。"""

from typing import Literal

from pydantic import BaseModel


class CurlingEvent(BaseModel):
    """算法内部事件对象，后续由 StoneEventService 产生。"""

    match_id: str
    sheet_id: str
    event_type: str
    timestamp: str | None = None


TriggerEventType = Literal["touch", "departure", "magnetic_1", "alarm", "magnetic_2", "stop"]


class TriggerEvent(BaseModel):
    """标准化后的电子冰壶触发事件。

    一期投壶事件由 TriggerEvent 驱动；Position 不反推 touch/departure/stop 等事件。
    """

    sheet_id: str
    lane_id: str
    timestamp: int
    event_type: TriggerEventType
