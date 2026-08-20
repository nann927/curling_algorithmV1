"""Integration/Mock 联调辅助服务。

该服务只在 APP_ENV=integration 且 MOCK_MODE=true 时生效，用于生成稳定公网 Mock URL 和赛后进度。
它不替代正式接口，只作为内部 Provider/Service 的 Mock 实现。
"""

from __future__ import annotations

import time
from typing import Callable

from app.core.config import IntegrationMockConfig, get_config_manager, get_settings


DEFAULT_RESULT_DURATIONS = {
    # 当前 Integration Mock 不真正生成视频文件，因此为各视频型 result_type 提供稳定测试时长。
    "player_highlight": 45.0,
    "team_highlight": 90.0,
    "labeled_clip": 30.0,
    "participant_video": 60.0,
}


class IntegrationMockService:
    """Integration Mock 配置与 URL 生成工具。"""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._settings = get_settings()
        self._config = get_config_manager().integration_mock_config
        self._clock = clock or time.monotonic

    @property
    def config(self) -> IntegrationMockConfig:
        """返回 integration_mock.json 解析后的配置。"""

        return self._config

    def enabled(self) -> bool:
        """判断当前是否启用 Integration Mock。"""

        return self._settings.app_env == "integration" and self._settings.mock_mode and self._config.enabled

    def now(self) -> float:
        """返回当前单调时间，测试可注入 clock。"""

        return self._clock()

    def preview_media_url(self, sheet_id: str) -> str:
        """生成 PC 六宫格预览地址；有 RTSP 配置时原样返回，否则走 PUBLIC_BASE_URL fallback。"""

        configured_url = self._sheet_preview_url(sheet_id)
        if configured_url:
            return configured_url
        fmt = self._config.mock_media.get("stream_format", "m3u8")
        return self._join_public_url(f"/integration/media/site/{sheet_id}/preview/program.{fmt}")

    def live_media_url(self, match_id: str, sheet_id: str, stream_type: str) -> str:
        """生成正式导播流地址；有 RTSP 配置时原样返回，否则走 PUBLIC_BASE_URL fallback。"""

        configured_url = self._sheet_live_url(sheet_id)
        if configured_url:
            return configured_url
        fmt = self._config.mock_media.get("stream_format", "m3u8")
        return self._join_public_url(f"/integration/media/{match_id}/{sheet_id}/{stream_type}/program.{fmt}")

    def record_media_url(self, match_id: str, sheet_id: str) -> str:
        """生成停止直播后的 Mock 导播录像地址。"""

        return self._join_public_url(f"/integration/media/{match_id}/{sheet_id}/record/program.mp4")

    def result_media_url(self, match_id: str, filename: str) -> str:
        """生成 PC 联调用赛后结果 Mock URL。"""

        return self._join_public_url(f"/integration/media/{match_id}/results/{filename}")

    def result_duration_seconds(self, result_type: str) -> float:
        """返回视频结果的稳定 Mock 时长，单位秒。"""

        key = f"{result_type}_duration_seconds"
        value = self._config.mock_media.get(key, DEFAULT_RESULT_DURATIONS.get(result_type, 1.0))
        return float(value)

    def progress_for_elapsed(self, elapsed_seconds: float) -> int:
        """按 integration_mock.json 的 progress_points 计算进度。"""

        points = sorted(self._config.postprocess.progress_points, key=lambda item: float(item["seconds"]))
        progress = 0
        for point in points:
            if elapsed_seconds >= float(point["seconds"]):
                progress = int(point["progress"])
        return min(progress, 100)

    def _sheet_preview_url(self, sheet_id: str) -> str | None:
        """读取单赛道 preview_url；Python 不内置任何 RTSP 字符串。"""

        media = self._config.sheet_media.get(sheet_id)
        return media.preview_url if media else None

    def _sheet_live_url(self, sheet_id: str) -> str | None:
        """读取单赛道 media_url；Python 不内置任何 RTSP 字符串。"""

        media = self._config.sheet_media.get(sheet_id)
        return media.media_url if media else None

    def _join_public_url(self, path: str) -> str:
        """拼接 PUBLIC_BASE_URL 和路径，避免硬编码公网 host。"""

        return self._settings.public_base_url.rstrip("/") + path

