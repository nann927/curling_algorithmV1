"""赛后状态与结果查询模型。"""

from pydantic import BaseModel


class SheetEditStatus(BaseModel):
    """单条赛道的赛后处理进度。"""

    sheet_id: str
    status: str
    progress: int


class EditStatusData(BaseModel):
    """IF-03 剪辑状态响应数据。"""

    match_id: str
    status: str
    progress: int
    sheets: list[SheetEditStatus]


class EditControlRequest(BaseModel):
    """POST /api/v1/edit/control 的请求体。"""

    action: str
    match_id: str


class MediaResult(BaseModel):
    """IF-04 返回的单个成品元数据。"""

    result_type: str
    sheet_id: str
    media_url: str
    player_id: str | None = None
    team_id: str | None = None
    person_label: str | None = None
    content_category: str | None = None
    label: str | None = None
    clip_id: str | None = None


class EditResultData(BaseModel):
    """IF-04 剪辑结果响应数据。"""

    match_id: str
    status: str
    result_mode: str | None
    results: list[MediaResult]
    scene_type: str | None = None
