"""Phase 3 视频接入基础设施测试。"""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.video.ffmpeg import FFmpegProcessManager
from app.adapters.video.local_file import LocalFileVideoProvider
from app.core.config import get_config_manager
from app.core.runtime import runtime_manager
from app.main import create_app
from app.services.video_source_manager import video_source_manager
from app.utils.process import ProcessManager


def _client() -> TestClient:
    return TestClient(create_app())


def _training_payload(match_id: str) -> dict:
    """构造 V2 训练类全景视频请求。"""

    return {
        "action": "start",
        "match_id": match_id,
        "sheet_id": "sheet_01",
        "scene_type": "personal_training",
        "start_time": "2026-08-15T10:00:00+08:00",
    }


def _wait_for_file(path: Path, timeout: float = 3.0) -> None:
    """等待 FFmpeg 生成输出文件。"""

    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(0.05)
    raise AssertionError(f"file was not generated: {path}")


def test_config_manager_validates_and_reads_site_config() -> None:
    """配置管理器应能读取现场配置，并禁止业务层硬编码摄像头映射。"""

    manager = get_config_manager()
    camera = manager.get_camera("overview_A")
    assert camera.source_provider == "local_file"
    assert camera.source_config["path"] == "data/test/overview_A.mp4"


def test_ffmpeg_manager_detects_binaries_and_stops_local_provider() -> None:
    """LocalFileVideoProvider 应能启动 FFmpeg，并在 stop 后回收进程。"""

    process_manager = ProcessManager()
    ffmpeg_manager = FFmpegProcessManager(process_manager)
    provider = LocalFileVideoProvider(ffmpeg_manager)
    camera = get_config_manager().get_camera("overview_A")

    handle = provider.start("phase3_local", "sheet_01", camera)
    assert handle.process_id is not None
    playlist = Path(handle.media_url)
    _wait_for_file(playlist)

    managed = process_manager.get(handle.process_id)
    assert managed.running
    provider.stop(handle)
    assert managed.exit_code is not None


def test_overview_start_and_stop_local_video_source() -> None:
    """V2 start 应启动当前赛道唯一全景源，stop 应回收视频源。"""

    client = _client()
    response = client.post("/api/v1/match/control", json=_training_payload("phase3_update"))
    assert response.status_code == 200
    start_data = response.json()["data"]
    assert start_data["stream_type"] == "overview_live"
    assert "overview_A" in start_data["media_url"]

    match = runtime_manager.get_match("phase3_update")
    assert match.sheet_id == "sheet_01"
    assert match.sheets["sheet_01"].current_camera_id == "overview_A"
    handle = video_source_manager.get_handle("phase3_update", "sheet_01")
    assert handle is not None
    assert handle.process_id is not None

    response = client.post("/api/v1/match/control", json={"action": "stop", "match_id": "phase3_update"})
    assert response.status_code == 200
    assert video_source_manager.get_handle("phase3_update", "sheet_01") is None
