"""pytest 公共夹具。"""

import subprocess
from pathlib import Path

import pytest

from app.core.runtime import runtime_manager
from app.services.video_source_manager import video_source_manager


def _ensure_test_video(path: Path, color: str) -> None:
    """用 FFmpeg 生成极短本地 MP4，供 LocalFileVideoProvider 测试使用。"""

    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180:r=25",
            "-t",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


@pytest.fixture(autouse=True)
def clear_runtime() -> None:
    """每个测试前清空进程内 Runtime，避免 match_id 相互污染。"""

    _ensure_test_video(Path("data/test/overview_A.mp4"), "blue")
    _ensure_test_video(Path("data/test/overview_B.mp4"), "green")
    video_source_manager.stop_all()
    runtime_manager.clear()
    yield
    video_source_manager.stop_all()
    runtime_manager.clear()
