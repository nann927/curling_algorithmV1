"""摄像头配置模型。"""

from pydantic import BaseModel


class CameraDevice(BaseModel):
    """算法侧固定维护的逻辑摄像头到真实设备映射。"""

    camera_id: str
    camera_role: str
    sheet_id: str | None = None
    install_end: str | None = None
    source_provider: str
    source_config: dict = {}
