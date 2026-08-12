"""本地 MP4 视频源 Provider。"""

from pathlib import Path

from app.adapters.video.base import VideoSourceHandle
from app.adapters.video.ffmpeg import FFmpegProcessManager
from app.core.config import SiteCameraConfig


class LocalFileVideoProvider:
    """使用本地 MP4 验证 Python -> Video Adapter -> FFmpeg -> ProcessManager 链路。"""

    provider_name = "local_file"

    def __init__(self, ffmpeg_manager: FFmpegProcessManager | None = None) -> None:
        self._ffmpeg_manager = ffmpeg_manager or FFmpegProcessManager()

    def start(self, match_id: str, sheet_id: str, camera: SiteCameraConfig) -> VideoSourceHandle:
        """启动本地 MP4 到 HLS 的 FFmpeg 测试链路。"""

        path = camera.source_config.get("path")
        if not path:
            raise ValueError(f"local_file camera missing source_config.path: {camera.camera_id}")
        process_id = f"{match_id}:{sheet_id}:{camera.camera_id}"
        output_dir = Path("data/runtime/live") / match_id / sheet_id / camera.camera_id
        info = self._ffmpeg_manager.start_local_file_hls(process_id, path, str(output_dir))
        return VideoSourceHandle(
            camera_id=camera.camera_id,
            provider=self.provider_name,
            media_url=info.media_url,
            process_id=info.process_id,
            metadata={"pid": info.pid, "output_path": info.output_path},
        )

    def stop(self, handle: VideoSourceHandle) -> None:
        """停止本地视频源 FFmpeg 进程。"""

        if handle.process_id:
            self._ffmpeg_manager.stop(handle.process_id)
