"""视频源管理服务。

业务层只传 camera_id；provider 选择、source_config 和 FFmpeg 生命周期都封装在这里。
"""

from app.adapters.video.base import VideoSourceHandle, VideoSourceProvider
from app.adapters.video.fusion_server import FusionServerVideoProvider
from app.adapters.video.local_file import LocalFileVideoProvider
from app.adapters.video.rtsp import RtspVideoProvider
from app.core.config import ConfigManager, get_config_manager


class VideoSourceManager:
    """根据 camera_id 启停视频源。"""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        providers: dict[str, VideoSourceProvider] | None = None,
    ) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._providers = providers or {
            "local_file": LocalFileVideoProvider(),
            "fusion_server": FusionServerVideoProvider(),
            "rtsp": RtspVideoProvider(),
        }
        self._handles: dict[str, VideoSourceHandle] = {}

    def start(self, match_id: str, sheet_id: str, camera_id: str) -> VideoSourceHandle:
        """启动 camera_id 对应的视频源。"""

        key = self._key(match_id, sheet_id)
        self.stop(match_id, sheet_id)
        camera = self._config_manager.get_camera(camera_id)
        provider = self._providers.get(camera.source_provider)
        if provider is None:
            raise ValueError(f"unsupported source_provider: {camera.source_provider}")
        handle = provider.start(match_id, sheet_id, camera)
        self._handles[key] = handle
        return handle

    def stop(self, match_id: str, sheet_id: str) -> None:
        """停止指定 match/sheet 的视频源。"""

        key = self._key(match_id, sheet_id)
        handle = self._handles.pop(key, None)
        if handle is None:
            return
        provider = self._providers.get(handle.provider)
        if provider is not None:
            provider.stop(handle)

    def stop_match(self, match_id: str) -> None:
        """停止一个 match 下的全部视频源。"""

        for key in list(self._handles):
            if key.startswith(f"{match_id}:"):
                _, sheet_id = key.split(":", 1)
                self.stop(match_id, sheet_id)

    def stop_all(self) -> None:
        """停止全部视频源，测试清理和服务退出时使用。"""

        for key in list(self._handles):
            match_id, sheet_id = key.split(":", 1)
            self.stop(match_id, sheet_id)

    def get_handle(self, match_id: str, sheet_id: str) -> VideoSourceHandle | None:
        """读取指定 match/sheet 当前视频源句柄。"""

        return self._handles.get(self._key(match_id, sheet_id))

    def _key(self, match_id: str, sheet_id: str) -> str:
        """生成内部句柄 key。"""

        return f"{match_id}:{sheet_id}"


video_source_manager = VideoSourceManager()
