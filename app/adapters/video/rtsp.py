"""RTSP 视频源 Provider 预留。

只有融合服务器或现场明确提供 RTSP 地址时才正式实现；当前禁止配置虚假 RTSP。
"""

from app.adapters.video.base import VideoSourceHandle
from app.core.config import SiteCameraConfig


class RtspVideoProvider:
    """RTSP Provider 占位。"""

    provider_name = "rtsp"

    def start(self, match_id: str, sheet_id: str, camera: SiteCameraConfig) -> VideoSourceHandle:
        """当前阶段不实现真实 RTSP 拉流。"""

        raise NotImplementedError("rtsp provider is reserved until onsite RTSP parameters are confirmed")

    def stop(self, handle: VideoSourceHandle) -> None:
        """RTSP Provider 当前没有已启动资源。"""

        return None
