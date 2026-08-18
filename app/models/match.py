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
    """兼容旧字段的单赛道配置。V2 正式业务不再使用多 sheets。"""

    sheet_id: str
    house_camera_ends: list[Literal["A", "B"]] = Field(default_factory=list)


class CameraConfig(BaseModel):
    """软件侧摄像头选择。

    overview_cameras 只接收 overview_A/overview_B 这类阵列逻辑 ID；house_cameras 单独接收
    各赛道的大本营俯拍 camera_id。算法内部再把阵列逻辑 ID 展开为 me/cl 等细分镜头。
    """

    overview_cameras: list[str] = Field(default_factory=list)
    house_cameras: list[str] = Field(default_factory=list)
    sheets: list[SheetCameraConfig] = Field(default_factory=list)


class MatchControlRequest(BaseModel):
    """POST /api/v1/match/control 的统一请求体。"""

    action: Literal["start", "update_config", "stop"]
    match_id: str
    match_name: str | None = None
    description: str | None = None
    sheet_id: str | None = None
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
