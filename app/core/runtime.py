"""运行时状态中心。

当前阶段采用进程内 RuntimeManager，集中管理 match 和 sheet 状态。
后续如需要持久化恢复或跨进程共享，应在本模块边界内扩展，而不是在业务模块散落全局字典。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from app.core.enums import DirectionStatus, EditStatus, RuntimeStatus


@dataclass
class SheetRuntime:
    """单条赛道的运行时状态。

    赛道之间必须互相隔离，单赛道异常不应默认拖垮整个 match。
    """

    sheet_id: str
    enabled: bool
    stream_type: str
    media_url: str | None
    house_camera_ends: list[str] = field(default_factory=list)
    current_direction: str | None = None
    # 方向字段由算法内部维护，软件平台不传入、不依赖。
    source_end: str | None = None
    target_end: str | None = None
    direction_status: str = DirectionStatus.UNKNOWN.value
    direction_confirm_count: int = 0
    last_position_time: int | None = None
    current_event: str | None = None
    current_shot_id: str | None = None
    current_camera_id: str | None = None
    current_microphone_id: str | None = None
    available_camera_ids: dict[str, list[str]] = field(default_factory=dict)
    status: str = RuntimeStatus.RUNNING.value
    edit_status: str = EditStatus.WAITING.value
    edit_progress: int = 0


@dataclass
class MatchRuntime:
    """一个 match_id 的顶层运行状态，内部可包含多条 SheetRuntime。"""

    match_id: str
    scene_type: str
    start_time: str
    status: str = RuntimeStatus.RUNNING.value
    teams: list[dict[str, Any]] = field(default_factory=list)
    players: list[dict[str, Any]] = field(default_factory=list)
    camera_config: dict[str, Any] = field(default_factory=dict)
    sheets: dict[str, SheetRuntime] = field(default_factory=dict)
    edit_status: str = EditStatus.WAITING.value
    edit_progress: int = 0
    result_mode: str | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    postprocess_started_at: float | None = None
    postprocess_duration_seconds: float | None = None
    postprocess_uploaded: bool = False


class RuntimeManager:
    """进程内 Runtime 注册表，负责创建、查询、更新、停止和清理。"""

    def __init__(self) -> None:
        self._matches: dict[str, MatchRuntime] = {}
        self._lock = RLock()

    def create_match(self, match: MatchRuntime) -> MatchRuntime:
        """创建 match；重复 start 通过这里统一拦截。"""

        with self._lock:
            if match.match_id in self._matches:
                raise ValueError(f"match_id already exists: {match.match_id}")
            self._matches[match.match_id] = match
            return match

    def get_match(self, match_id: str) -> MatchRuntime:
        """按 match_id 读取运行时；不存在时抛 KeyError 给 API 层转 404。"""

        with self._lock:
            match = self._matches.get(match_id)
            if match is None:
                raise KeyError(f"match_id not found: {match_id}")
            return match

    def update_match_config(
        self,
        match_id: str,
        camera_config: dict[str, Any],
        sheets: dict[str, SheetRuntime],
        teams: list[dict[str, Any]] | None = None,
        players: list[dict[str, Any]] | None = None,
    ) -> MatchRuntime:
        """按完整 camera_config 覆盖当前有效赛道配置。"""

        with self._lock:
            match = self.get_match(match_id)
            match.camera_config = camera_config
            match.sheets = sheets
            if teams is not None:
                match.teams = teams
            if players is not None:
                match.players = players
            return match

    def stop_match(self, match_id: str) -> MatchRuntime:
        """停止实时阶段，并把 match 推进到赛后处理中。"""

        with self._lock:
            match = self.get_match(match_id)
            if match.status != RuntimeStatus.RUNNING.value:
                raise ValueError(f"match is not running: {match_id}")
            match.status = RuntimeStatus.POST_PROCESSING.value
            match.edit_status = EditStatus.PROCESSING.value
            match.edit_progress = 0
            for sheet in match.sheets.values():
                sheet.status = RuntimeStatus.STOPPED.value
                sheet.edit_status = EditStatus.PROCESSING.value
                sheet.edit_progress = 0
            return match

    def remove_match(self, match_id: str) -> None:
        """生命周期清理入口，后续可在这里挂载资源释放逻辑。"""

        with self._lock:
            self._matches.pop(match_id, None)

    def clear(self) -> None:
        """测试专用清理入口，避免用例之间共享运行时状态。"""

        with self._lock:
            self._matches.clear()


runtime_manager = RuntimeManager()
# 统一的进程内单例；业务模块只引用这个对象，不再自行声明全局 dict。
