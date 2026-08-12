"""电子冰壶数据模型占位。"""

from pydantic import BaseModel, Field


class StonePosition(BaseModel):
    """标准化后的冰壶定位数据。

    一期定位数据只用于 touch→departure 窗口内判断 A/B 发球端，不用于运动、停止、入营或碰撞判断。
    """

    sheet_id: str
    lane_id: str
    tag_id: str
    timestamp: int
    x: float
    y: float


class RawStonePosition(BaseModel):
    """供应商定位原始 JSON 的最小字段模型。

    Provider 负责把该模型转换为内部 StonePosition，业务 Service 不直接消费它。
    """

    laneId: str = Field(alias="laneId")
    tagId: str = Field(alias="tagId")
    time: int
    x: float
    y: float
