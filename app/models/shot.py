"""投壶 Shot 模型。

Phase 5 中 Shot 是 TriggerEvent 和 DirectionService 的归并结果，不保存全量 Position、
速度、轨迹、碰撞或视频大对象。
"""

from pydantic import BaseModel

from app.core.enums import ShotQualityStatus, ThrowStatus


class Shot(BaseModel):
    """一次投壶的完整生命周期记录。"""

    shot_id: str
    match_id: str
    sheet_id: str
    touch_time: int | None = None
    departure_time: int | None = None
    first_magnetic_time: int | None = None
    alarm_time: int | None = None
    second_magnetic_time: int | None = None
    stop_time: int | None = None
    direction: str = "UNKNOWN"
    source_end: str | None = None
    target_end: str | None = None
    status: str = ThrowStatus.IDLE.value
    quality_status: str = ShotQualityStatus.INCOMPLETE.value
    player_id: str | None = None
    team_id: str | None = None
    clip_id: str | None = None
    recognition_status: str | None = None
    abnormal_reason: str | None = None


class ShotEventContext(BaseModel):
    """状态机输出给后续 DirectorService 的统一业务上下文。"""

    match_id: str
    sheet_id: str
    shot_id: str | None
    event_type: str
    timestamp: int
    shot_status: str | None
    direction: str = "UNKNOWN"
    source_end: str | None = None
    target_end: str | None = None
    quality_status: str | None = None
