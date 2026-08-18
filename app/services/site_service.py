"""赛道资源查询服务。

资源接口只负责主界面初始化：赛道名称、预览 URL、候选 camera_id、当前是否被直播占用。
"""

from __future__ import annotations

from app.core.config import ConfigManager, SiteCameraConfig, SiteSheetConfig, get_config_manager
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
            sheet_name = sheet.sheet_name or f"{index}号赛道"
            sheets.append(
                {
                    "sheet_id": sheet.sheet_id,
                    "sheet_name": sheet_name,
                    "live_status": "running" if running else "idle",
                    "match_id": running.match_id if running else None,
                    "preview_url": self._preview_url(sheet.sheet_id, sheet.preview_url),
                    "cameras": self._software_camera_summaries(sheet, sheet_name),
                }
            )
        return {"sheets": sheets}

    def _software_camera_summaries(self, sheet: SiteSheetConfig, sheet_name: str) -> list[dict]:
        """返回软件侧可选择的逻辑摄像头，不暴露算法内部 me/cl 细分镜头。"""

        cameras = []
        for overview_id in self._config_manager.get_overview_camera_ids():
            install_end = self._config_manager.get_overview_install_end(overview_id)
            cameras.append({"camera_id": overview_id, "description": f"{install_end}端阵列摄像头"})
        for camera in self._config_manager.get_sheet_cameras(sheet.sheet_id, camera_role="house_top"):
            cameras.append(self._house_camera_summary(camera, sheet_name))
        return cameras

    def _preview_url(self, sheet_id: str, configured_url: str | None) -> str | None:
        """优先使用配置中的真实 preview_url；Integration Mock 下动态生成公网 URL。"""

        if configured_url:
            return configured_url
        if self._integration_mock.enabled():
            return self._integration_mock.preview_media_url(sheet_id)
        return None

    def _house_camera_summary(self, camera: SiteCameraConfig, sheet_name: str) -> dict:
        """生成大本营俯拍摄像头说明。"""

        description = camera.description or f"{sheet_name}{camera.install_end or ''}端大本营俯拍摄像头"
        return {"camera_id": camera.camera_id, "description": description}
