"""pytest 公共夹具。"""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

# 测试统一使用临时 SQLite，避免本地历史库只读或被运行服务占用。
os.environ["CURLING_SQLITE_PATH"] = str(Path(tempfile.gettempdir()) / "curling_algorithm_tests_bootstrap.sqlite")
os.environ.setdefault("CURLING_LOG_PATH", str(Path(tempfile.gettempdir()) / "curling_algorithm_tests.log"))

from app.core.config import get_config_manager, get_settings
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
    """每个测试前清空进程内 Runtime，并为该测试分配独立 SQLite。"""

    _ensure_test_video(Path("data/test/overview_A.mp4"), "blue")
    _ensure_test_video(Path("data/test/overview_B.mp4"), "green")
    video_source_manager.stop_all()
    runtime_manager.clear()
    os.environ["CURLING_SQLITE_PATH"] = str(Path(tempfile.gettempdir()) / f"curling_algorithm_tests_{uuid.uuid4().hex}.sqlite")
    get_settings.cache_clear()
    get_config_manager.cache_clear()
    yield
    video_source_manager.stop_all()
    runtime_manager.clear()
    get_settings.cache_clear()
    get_config_manager.cache_clear()
