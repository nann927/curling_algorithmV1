"""FFmpeg 视频处理边界。

本模块只封装 FFmpeg/ffprobe 检测与进程生命周期，不承载业务规则。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.utils.process import ManagedProcess, ProcessManager


@dataclass
class FFmpegProcessInfo:
    """FFmpeg 进程运行信息。"""

    process_id: str
    pid: int
    command: list[str]
    output_path: str
    media_url: str


class FFmpegProcessManager:
    """FFmpeg 进程生命周期管理器。"""

    def __init__(self, process_manager: ProcessManager | None = None) -> None:
        self._settings = get_settings()
        self._process_manager = process_manager or ProcessManager()

    def check_binaries(self) -> dict[str, str]:
        """检测 ffmpeg 和 ffprobe 是否可执行。"""

        ffmpeg = shutil.which(self._settings.ffmpeg_path) or self._settings.ffmpeg_path
        ffprobe = shutil.which(self._settings.ffprobe_path) or self._settings.ffprobe_path
        self._run_version_check(ffmpeg)
        self._run_version_check(ffprobe)
        return {"ffmpeg": ffmpeg, "ffprobe": ffprobe}

    def start_local_file_hls(
        self,
        process_id: str,
        input_path: str,
        output_dir: str,
        *,
        loop: bool = True,
    ) -> FFmpegProcessInfo:
        """把本地 MP4 转为持续刷新的 HLS 测试输出。"""

        binaries = self.check_binaries()
        source = Path(input_path)
        if not source.exists():
            raise FileNotFoundError(f"local video file not found: {input_path}")

        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        playlist = output / "index.m3u8"

        command = [binaries["ffmpeg"], "-hide_banner", "-loglevel", "warning", "-y"]
        if loop:
            command.extend(["-stream_loop", "-1", "-re"])
        command.extend(
            [
                "-i",
                str(source),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-g",
                "25",
                "-sc_threshold",
                "0",
                "-force_key_frames",
                "expr:gte(t,n_forced*1)",
                "-f",
                "hls",
                "-hls_time",
                "1",
                "-hls_list_size",
                "4",
                "-hls_flags",
                "delete_segments+append_list",
                str(playlist),
            ]
        )
        managed = self._process_manager.start(process_id, command)
        return FFmpegProcessInfo(
            process_id=process_id,
            pid=managed.pid,
            command=command,
            output_path=str(playlist),
            media_url=playlist.as_posix(),
        )

    def get(self, process_id: str) -> ManagedProcess:
        """读取 FFmpeg 进程状态。"""

        return self._process_manager.get(process_id)

    def stop(self, process_id: str, timeout_seconds: float = 5.0) -> ManagedProcess | None:
        """停止 FFmpeg 进程。"""

        return self._process_manager.stop(process_id, timeout_seconds)

    def stop_all(self) -> None:
        """停止全部 FFmpeg 进程。"""

        self._process_manager.stop_all()

    def _run_version_check(self, executable: str) -> None:
        """通过 -version 检查可执行文件是否可用。"""

        subprocess.run([executable, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
