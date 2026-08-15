"""赛道资源查询服务。

资源接口只负责主界面初始化：赛道名称、预览 URL、候选 camera_id、当前是否被直播占用。
"""

from __future__ import annotations

from app.core.config import ConfigManager, SiteCameraConfig, get_config_manager
from app.core.runtime import runtime_manager
from app.services.integration_mock_service import IntegrationMockService


class SiteService:
    """组装 /api/v1/site/resources 数据。"""

    def __init__(self, config_manager: ConfigManager | None = None, integration_mock: IntegrationMockService | None = None) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._integration_mock = integration_mock or IntegrationMockService()

    def get_resources(self) -> dict:
        """返回当前所有赛道资源状态。"""

        sheets = []
        for index, sheet in enumerate(self._config_manager.site_config.sheets, start=1):
            running = runtime_manager.get_running_match_by_sheet(sheet.sheet_id)
            sheets.append(
                {
                    "sheet_id": sheet.sheet_id,
                    "sheet_name": sheet.sheet_name or f"{index}号赛道",
                    "live_status": "running" if running else "idle",
                    "match_id": running.match_id if running else None,
                    "preview_url": self._preview_url(sheet.sheet_id, sheet.preview_url),
                    "cameras": [self._camera_summary(camera) for camera in self._config_manager.get_sheet_cameras(sheet.sheet_id)],
                }
            )
        return {"sheets": sheets}

    def _preview_url(self, sheet_id: str, configured_url: str | None) -> str | None:
        """优先使用配置中的真实 preview_url；Integration Mock 下动态生成公网 URL。"""

        if configured_url:
            return configured_url
        if self._integration_mock.enabled():
            return self._integration_mock.preview_media_url(sheet_id)
        return None

    def _camera_summary(self, camera: SiteCameraConfig) -> dict:
        """生成 camera_id 和说明，不要求软件用 camera_id 控制导播。"""

        return {"camera_id": camera.camera_id, "description": camera.description or self._default_description(camera)}

    def _default_description(self, camera: SiteCameraConfig) -> str:
        """根据配置字段生成简短镜头说明，减少重复配置。"""

        role_names = {"house_top": "大本营", "medium_shot": "中景", "close_shot": "特写", "overview": "全景"}
        role = role_names.get(camera.camera_role, camera.camera_role)
        end = f"{camera.install_end}端" if camera.install_end else ""
        return f"{camera.sheet_id or '全场'}{end}{role}摄像头"
