"""IF-01 控制接口请求模型。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class TeamInfo(BaseModel):
    """软件平台传入的队伍信息；当前阶段只做透传和保存。"""

    team_id: str | None = None
    team_name: str | None = None


class PlayerInfo(BaseModel):
    """软件平台传入的人员信息；赛后 Mock 结果优先使用这些业务 ID。"""

    player_id: str | None = None
    player_name: str | None = None
    team_id: str | None = None


class SheetCameraConfig(BaseModel):
    """单条赛道的摄像头启用配置。"""

    sheet_id: str
    # 竞赛场景必填；训练类场景可为空，因为实时阶段只使用全景。
    house_camera_ends: list[Literal["A", "B"]] = Field(default_factory=list)


class CameraConfig(BaseModel):
    """一次 match 当前完整有效的摄像头配置。"""

    overview_cameras: list[str]
    sheets: list[SheetCameraConfig]


class MatchControlRequest(BaseModel):
    """POST /api/v1/match/control 的统一请求体。"""

    action: Literal["start", "update_config", "stop"]
    match_id: str
    scene_type: str | None = None
    start_time: str | None = None
    teams: list[TeamInfo] | None = None
    players: list[PlayerInfo] | None = None
    camera_config: CameraConfig | None = None


class ApiResponse(BaseModel):
    """软件平台接口统一响应结构。"""

    code: int = 0
    message: str = "ok"
    data: dict[str, Any] = Field(default_factory=dict)
