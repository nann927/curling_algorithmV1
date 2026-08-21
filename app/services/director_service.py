"""竞赛智能导播服务边界。"""

import logging

from app.core.config import ConfigManager, get_config_manager
from app.core.enums import StreamType
from app.core.runtime import SheetRuntime, runtime_manager
from app.models.director import DirectorDecision
from app.models.shot import ShotEventContext
from app.services.director_rule_service import DirectorRuleService
from app.services.integration_mock_service import IntegrationMockService

logger = logging.getLogger(__name__)


class DirectorService:
    """竞赛场景的实时输出服务。

    Phase 6 新增内部 decide(context) 能力：只更新 Runtime 当前镜头，不真正切流，也不改变软件 API。
    """

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        integration_mock: IntegrationMockService | None = None,
        rule_service: DirectorRuleService | None = None,
    ) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._integration_mock = integration_mock or IntegrationMockService()
        self._rule_service = rule_service or DirectorRuleService(self._config_manager)

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

    def decide(self, context: ShotEventContext) -> DirectorDecision:
        """根据 ShotEventContext 产生内部导播决策，并只更新 Runtime 当前镜头。"""

        match = runtime_manager.get_match(context.match_id)
        if match.sheet_id is not None and match.sheet_id != context.sheet_id:
            raise ValueError("context sheet_id does not match current match")
        if context.sheet_id not in match.sheets:
            raise ValueError("sheet runtime not found for context")
        sheet = match.sheets[context.sheet_id]
        decision = self._rule_service.decide(
            context,
            sheet.available_camera_ids,
            current_camera_id=sheet.current_camera_id,
        )
        if decision.camera_id is not None and not decision.hold_previous:
            sheet.current_camera_id = decision.camera_id
        logger.info(
            "director decision match_id=%s sheet_id=%s shot_id=%s event_type=%s camera_id=%s camera_role=%s fallback=%s hold=%s",
            decision.match_id,
            decision.sheet_id,
            decision.shot_id,
            decision.event_type,
            decision.camera_id,
            decision.camera_role,
            decision.fallback_used,
            decision.hold_previous,
        )
        return decision

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
