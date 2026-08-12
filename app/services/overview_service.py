"""训练类全景输出服务边界。"""

from app.core.enums import StreamType
from app.core.runtime import SheetRuntime
from app.services.integration_mock_service import IntegrationMockService
from app.services.video_source_manager import VideoSourceManager, video_source_manager


class OverviewService:
    """非竞赛场景的实时全景输出服务。"""

    def __init__(self, source_manager: VideoSourceManager | None = None, integration_mock: IntegrationMockService | None = None) -> None:
        self._source_manager = source_manager or video_source_manager
        self._integration_mock = integration_mock or IntegrationMockService()

    def start_sheet(
        self,
        match_id: str,
        sheet_id: str,
        house_camera_ends: list[str],
        camera_id: str,
    ) -> SheetRuntime:
        """为单条赛道创建 overview_live 输出状态。"""

        if self._integration_mock.enabled():
            media_url = self._integration_mock.live_media_url(match_id, sheet_id, StreamType.OVERVIEW_LIVE.value)
        else:
            handle = self._source_manager.start(match_id, sheet_id, camera_id)
            media_url = handle.media_url

        return SheetRuntime(
            sheet_id=sheet_id,
            enabled=True,
            stream_type=StreamType.OVERVIEW_LIVE.value,
            media_url=media_url,
            house_camera_ends=house_camera_ends,
            current_camera_id=camera_id,
        )

    def stop_match(self, match_id: str) -> None:
        """停止一个 match 下的全景视频源。"""

        self._source_manager.stop_match(match_id)
