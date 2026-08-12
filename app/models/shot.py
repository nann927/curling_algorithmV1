"""投壶片段模型占位。"""

from pydantic import BaseModel


class Shot(BaseModel):
    """一次投壶的最小状态，后续会绑定识别结果和剪辑路径。"""

    shot_id: str
    match_id: str
    sheet_id: str
    player_id: str | None = None
    recognition_status: str | None = None
