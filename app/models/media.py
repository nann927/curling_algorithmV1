"""实时输出模型。"""

from pydantic import BaseModel


class LiveOutput(BaseModel):
    """单条赛道暴露给软件平台的一路实时输出。"""

    sheet_id: str
    stream_type: str
    media_url: str


class DirectorOutputData(BaseModel):
    """IF-02 及 start/update_config 响应中的实时输出数据。"""

    match_id: str
    scene_type: str
    status: str
    outputs: list[LiveOutput]
