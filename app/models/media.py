"""实时输出模型。"""

from pydantic import BaseModel


class LiveOutput(BaseModel):
    """兼容内部使用的一路实时输出。"""

    sheet_id: str
    stream_type: str
    media_url: str


class DirectorOutputData(BaseModel):
    """V2 的单赛道实时输出数据。"""

    match_id: str
    sheet_id: str
    scene_type: str
    status: str
    media_url: str
    stream_type: str | None = None
