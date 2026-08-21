"""Director Rule V1 确定性镜头选择规则。

本服务只消费已经标准化的 ShotEventContext，不读取 WebSocket 原始数据，也不控制 FFmpeg。
"""

from __future__ import annotations

from app.core.config import ConfigManager, SiteCameraConfig, get_config_manager
from app.models.director import DirectorDecision
from app.models.shot import ShotEventContext


EVENT_PREFERENCES = {
    # V1 规则集中维护，后续现场调参只改这一处映射。
    "touch": ("close_shot", "source", "touch_source_close"),
    "departure": ("medium_shot", "source", "departure_source_medium"),
    "magnetic_1": ("medium_shot", "source", "magnetic1_source_medium"),
    "magnetic_2": ("medium_shot", "target", "magnetic2_target_medium"),
    "stop": ("house_top", "target", "stop_target_house"),
}

FALLBACK_BY_ROLE = {
    "house_top": ["house_top", "medium_shot", "close_shot"],
    "medium_shot": ["medium_shot", "close_shot", "house_top"],
    "close_shot": ["close_shot", "medium_shot", "house_top"],
}

STABLE_ANY_ROLE_ORDER = ["close_shot", "medium_shot", "house_top"]


class DirectorRuleService:
    """把 ShotEventContext 转换为 DirectorDecision 的纯规则服务。"""

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager or get_config_manager()

    def decide(
        self,
        context: ShotEventContext,
        available_camera_ids: dict[str, list[str]],
        current_camera_id: str | None = None,
    ) -> DirectorDecision:
        """根据当前 Shot 事件选择一个已启用的内部 camera_id。"""

        if not self._has_available_camera(available_camera_ids):
            return self._decision(context, None, "no_available_camera", fallback_used=True, hold_previous=True)

        if context.event_type == "alarm":
            return self._alarm_decision(context, available_camera_ids, current_camera_id)

        preference = EVENT_PREFERENCES.get(context.event_type)
        if preference is None:
            return self._fallback_any(context, available_camera_ids, current_camera_id, "unsupported_event", fallback_used=True)

        preferred_role, end_selector, reason = preference
        preferred_end = context.source_end if end_selector == "source" else context.target_end
        if not preferred_end or context.direction == "UNKNOWN":
            return self._direction_unknown_decision(context, available_camera_ids, current_camera_id)

        selected = self._select_by_role_and_end(available_camera_ids, preferred_role, preferred_end)
        if selected is not None:
            return self._decision_for_camera(context, selected, reason, current_camera_id=current_camera_id)

        fallback = self._fallback_same_end(available_camera_ids, preferred_role, preferred_end)
        if fallback is not None:
            return self._decision_for_camera(
                context,
                fallback,
                "preferred_camera_unavailable",
                current_camera_id=current_camera_id,
                fallback_used=True,
            )
        return self._fallback_any(context, available_camera_ids, current_camera_id, "preferred_camera_unavailable", fallback_used=True)

    def _alarm_decision(
        self,
        context: ShotEventContext,
        available_camera_ids: dict[str, list[str]],
        current_camera_id: str | None,
    ) -> DirectorDecision:
        """alarm 只保持当前镜头；没有当前镜头时再走稳定 fallback。"""

        current = self._camera_if_available(current_camera_id, available_camera_ids)
        if current is not None:
            return self._decision_for_camera(
                context,
                current,
                "alarm_hold_current_camera",
                current_camera_id=current_camera_id,
                hold_previous=True,
            )
        return self._fallback_any(context, available_camera_ids, current_camera_id, "alarm_hold_current_camera", fallback_used=True)

    def _direction_unknown_decision(
        self,
        context: ShotEventContext,
        available_camera_ids: dict[str, list[str]],
        current_camera_id: str | None,
    ) -> DirectorDecision:
        """方向未知时不抛异常，优先保持当前可用镜头。"""

        current = self._camera_if_available(current_camera_id, available_camera_ids)
        if current is not None:
            return self._decision_for_camera(
                context,
                current,
                "direction_unknown",
                current_camera_id=current_camera_id,
                fallback_used=True,
                hold_previous=True,
            )
        return self._fallback_any(context, available_camera_ids, current_camera_id, "direction_unknown", fallback_used=True)

    def _fallback_same_end(
        self,
        available_camera_ids: dict[str, list[str]],
        preferred_role: str,
        install_end: str,
    ) -> SiteCameraConfig | None:
        """首选镜头不可用时，在同一端位内按固定角色顺序降级。"""

        for role in FALLBACK_BY_ROLE.get(preferred_role, [preferred_role]):
            camera = self._select_by_role_and_end(available_camera_ids, role, install_end)
            if camera is not None:
                return camera
        return None

    def _fallback_any(
        self,
        context: ShotEventContext,
        available_camera_ids: dict[str, list[str]],
        current_camera_id: str | None,
        reason: str,
        *,
        fallback_used: bool,
    ) -> DirectorDecision:
        """同端不可用时，保持当前镜头或选择稳定的任意已启用镜头。"""

        current = self._camera_if_available(current_camera_id, available_camera_ids)
        if current is not None:
            return self._decision_for_camera(
                context,
                current,
                reason,
                current_camera_id=current_camera_id,
                fallback_used=fallback_used,
                hold_previous=True,
            )
        any_camera = self._select_any_stable(available_camera_ids)
        if any_camera is None:
            return self._decision(context, None, "no_available_camera", fallback_used=True, hold_previous=True)
        return self._decision_for_camera(context, any_camera, reason, current_camera_id=current_camera_id, fallback_used=fallback_used)

    def _select_by_role_and_end(
        self,
        available_camera_ids: dict[str, list[str]],
        camera_role: str,
        install_end: str,
    ) -> SiteCameraConfig | None:
        """只在当前可用候选中按结构化 metadata 查找镜头，不解析 camera_id 字符串。"""

        for camera_id in available_camera_ids.get(camera_role, []):
            camera = self._safe_camera(camera_id)
            if camera is not None and camera.camera_role == camera_role and camera.install_end == install_end:
                return camera
        return None

    def _select_any_stable(self, available_camera_ids: dict[str, list[str]]) -> SiteCameraConfig | None:
        """选择稳定的任意已启用镜头；不使用 random，也不依赖 set 顺序。"""

        ordered_roles = [role for role in STABLE_ANY_ROLE_ORDER if role in available_camera_ids]
        ordered_roles.extend(role for role in available_camera_ids if role not in ordered_roles)
        for role in ordered_roles:
            for camera_id in available_camera_ids.get(role, []):
                camera = self._safe_camera(camera_id)
                if camera is not None:
                    return camera
        return None

    def _camera_if_available(
        self,
        camera_id: str | None,
        available_camera_ids: dict[str, list[str]],
    ) -> SiteCameraConfig | None:
        """确认 current_camera_id 仍属于当前 Match 已启用候选。"""

        if not camera_id:
            return None
        for values in available_camera_ids.values():
            if camera_id in values:
                return self._safe_camera(camera_id)
        return None

    def _safe_camera(self, camera_id: str) -> SiteCameraConfig | None:
        """读取摄像头 metadata；配置缺失时忽略该候选，避免错误切到未知设备。"""

        try:
            return self._config_manager.get_camera(camera_id)
        except KeyError:
            return None

    def _has_available_camera(self, available_camera_ids: dict[str, list[str]]) -> bool:
        """判断当前 Match 是否至少启用了一个 camera_id。"""

        return any(bool(values) for values in available_camera_ids.values())

    def _decision_for_camera(
        self,
        context: ShotEventContext,
        camera: SiteCameraConfig,
        reason: str,
        *,
        current_camera_id: str | None,
        fallback_used: bool = False,
        hold_previous: bool | None = None,
    ) -> DirectorDecision:
        """把摄像头 metadata 转换成 DirectorDecision。"""

        hold = camera.camera_id == current_camera_id if hold_previous is None else hold_previous
        return self._decision(context, camera, reason, fallback_used=fallback_used, hold_previous=hold)

    def _decision(
        self,
        context: ShotEventContext,
        camera: SiteCameraConfig | None,
        reason: str,
        *,
        fallback_used: bool,
        hold_previous: bool,
    ) -> DirectorDecision:
        """统一组装 DirectorDecision，确保字段稳定。"""

        return DirectorDecision(
            match_id=context.match_id,
            sheet_id=context.sheet_id,
            shot_id=context.shot_id,
            event_type=context.event_type,
            timestamp=context.timestamp,
            direction=context.direction,
            source_end=context.source_end,
            target_end=context.target_end,
            camera_id=camera.camera_id if camera else None,
            camera_role=camera.camera_role if camera else None,
            install_end=camera.install_end if camera else None,
            reason=reason,
            fallback_used=fallback_used,
            hold_previous=hold_previous,
        )
