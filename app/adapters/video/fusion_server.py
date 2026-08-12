"""融合服务器视频源 Provider 骨架。

依据《拙河视频融合服务接口文档-V1.14》：
- 视频流可通过标准 RTSP 拉取；
- 网页端也可通过私有 WebSocket 视频流拉取；
- HTTP 接口可查询状态和通道信息；
- 通道信息包含 resId、url、编码宽高、格式、码率、帧率等；
- 文档没有给出本项目现场 server_ip、channel_path、resId、鉴权信息或音频结论。

因此当前只保留边界和配置字段，不做真实连接。
"""

from app.adapters.video.base import VideoSourceHandle
from app.core.config import SiteCameraConfig


class FusionServerVideoProvider:
    """融合服务器 Provider 骨架，等待现场参数后补齐。"""

    provider_name = "fusion_server"

    def start(self, match_id: str, sheet_id: str, camera: SiteCameraConfig) -> VideoSourceHandle:
        """现场参数未给全时不启动真实融合服务器视频流。"""

        required = ("server_ip", "channel_path")
        missing = [key for key in required if not camera.source_config.get(key)]
        if missing:
            raise NotImplementedError(
                "fusion_server source_config is incomplete; missing "
                f"{missing}. TODO: wait for onsite fusion server parameters."
            )
        raise NotImplementedError("fusion_server realtime provider waits for onsite integration")

    def stop(self, handle: VideoSourceHandle) -> None:
        """融合服务器 Provider 当前没有已启动资源。"""

        return None
