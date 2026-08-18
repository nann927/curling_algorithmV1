"""竞赛智能导播服务边界。"""

from app.core.config import ConfigManager, get_config_manager
from app.core.enums import StreamType
from app.core.runtime import SheetRuntime
from app.services.integration_mock_service import IntegrationMockService


class DirectorService:
    """竞赛场景的实时输出服务。

    Phase 4.6.2 只修正候选摄像头来源：Director 只能使用软件本场允许的内部镜头集合，
    真实切镜规则仍留到后续阶段实现。
    """

    def __init__(self, config_manager: ConfigManager | None = None, integration_mock: IntegrationMockService | None = None) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._integration_mock = integration_mock or IntegrationMockService()

    def start_sheet(self, match_id: str, sheet_id: str, camera_ids_by_role: dict[str, list[str]]) -> SheetRuntime:
        """为单条赛道创建 smart_director 输出状态。"""

        current_camera_id = self._select_initial_camera(camera_ids_by_role)
        house_camera_ends = [
            camera.install_end
            for camera_id in camera_ids_by_role.get("house_top", [])
            for camera in [self._config_manager.get_camera(camera_id)]
            if camera.install_end
        ]
        return SheetRuntime(
            sheet_id=sheet_id,
            enabled=True,
            stream_type=StreamType.SMART_DIRECTOR.value,
            media_url=self._media_url(match_id, sheet_id),
            house_camera_ends=house_camera_ends,
            current_camera_id=current_camera_id,
            available_camera_ids=camera_ids_by_role,
        )

    def _media_url(self, match_id: str, sheet_id: str) -> str:
        """生成实时输出 URL；Integration 环境返回 HTTP URL，开发环境保持 mock URL。"""

        if self._integration_mock.enabled():
            return self._integration_mock.live_media_url(match_id, sheet_id, StreamType.SMART_DIRECTOR.value)
        return f"mock://{match_id}/{sheet_id}/smart_director"

    def _select_initial_camera(self, camera_ids_by_role: dict[str, list[str]]) -> str | None:
        """选择初始镜头 ID；只从本场已授权候选镜头里选择。"""

        for role in ("house_top", "medium_shot", "close_shot"):
            cameras = camera_ids_by_role.get(role, [])
            if cameras:
                return cameras[0]
        return None
