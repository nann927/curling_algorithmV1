"""运行时状态中心。

当前阶段采用进程内 RuntimeManager，集中管理 match 和 sheet 状态。
Phase 4.6 将正式业务收敛为 1 match = 1 sheet，但为了最小改动继续保留 sheets dict。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from app.core.enums import DirectionStatus, EditStatus, RuntimeStatus


@dataclass
class SheetRuntime:
    """单条赛道的运行时状态。

    V2 中一个 MatchRuntime 只持有一个 SheetRuntime；Phase 5 的 Shot/Direction 字段继续保留。
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
    # Phase 5：运行中的 Shot 只保存在进程内，FINISHED 后再持久化到 SQLite。
    current_shot: dict[str, Any] | None = None
    current_shot_id: str | None = None
    shot_sequence: int = 0
    shot_history: list[str] = field(default_factory=list)
    current_camera_id: str | None = None
    current_microphone_id: str | None = None
    available_camera_ids: dict[str, list[str]] = field(default_factory=dict)
    status: str = RuntimeStatus.RUNNING.value
    edit_status: str = EditStatus.NOT_STARTED.value
    edit_progress: int = 0


@dataclass
class MatchRuntime:
    """一个 match_id 的顶层运行状态。

    sheet_id 是 V2 的明确业务字段；sheets dict 仅作为兼容现有 Service 的容器，必须最多一个元素。
    """

    match_id: str
    scene_type: str
    start_time: str
    match_name: str = ""
    description: str = ""
    sheet_id: str | None = None
    end_time: str | None = None
    media_url: str | None = None
    record_url: str | None = None
    status: str = RuntimeStatus.RUNNING.value
    teams: list[dict[str, Any]] = field(default_factory=list)
    players: list[dict[str, Any]] = field(default_factory=list)
    camera_config: dict[str, Any] = field(default_factory=dict)
    sheets: dict[str, SheetRuntime] = field(default_factory=dict)
    edit_status: str = EditStatus.NOT_STARTED.value
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
        """创建 match；重复 start 或同赛道占用通过这里统一拦截。"""

        with self._lock:
            if match.match_id in self._matches:
                raise ValueError(f"match_id already exists: {match.match_id}")
            if match.sheet_id and self.is_sheet_occupied(match.sheet_id):
                raise ValueError(f"sheet already occupied: {match.sheet_id}")
            if len(match.sheets) > 1:
                raise ValueError("V2 match can only contain one sheet")
            self._matches[match.match_id] = match
            return match

    def get_match(self, match_id: str) -> MatchRuntime:
        """按 match_id 读取运行时；不存在时抛 KeyError 给 API 层转 404。"""

        with self._lock:
            match = self._matches.get(match_id)
            if match is None:
                raise KeyError(f"match_id not found: {match_id}")
            return match

    def list_matches(self) -> list[MatchRuntime]:
        """返回当前进程内所有 match。"""

        with self._lock:
            return list(self._matches.values())

    def get_running_match_by_sheet(self, sheet_id: str) -> MatchRuntime | None:
        """查询某条赛道当前是否被 running match 占用。"""

        with self._lock:
            for match in self._matches.values():
                if match.sheet_id == sheet_id and match.status == RuntimeStatus.RUNNING.value:
                    return match
        return None

    def is_sheet_occupied(self, sheet_id: str) -> bool:
        """判断赛道是否已有运行中的直播任务。"""

        return self.get_running_match_by_sheet(sheet_id) is not None

    def update_match_config(
        self,
        match_id: str,
        camera_config: dict[str, Any] | None = None,
        sheets: dict[str, SheetRuntime] | None = None,
        teams: list[dict[str, Any]] | None = None,
        players: list[dict[str, Any]] | None = None,
        match_name: str | None = None,
        description: str | None = None,
    ) -> MatchRuntime:
        """更新当前 match 的业务配置；V2 不允许通过 update_config 换赛道。"""

        with self._lock:
            match = self.get_match(match_id)
            if sheets is not None:
                if len(sheets) > 1:
                    raise ValueError("V2 match can only contain one sheet")
                new_sheet_id = next(iter(sheets), None)
                if new_sheet_id is not None and match.sheet_id is not None and new_sheet_id != match.sheet_id:
                    raise ValueError("sheet_id cannot be changed after start")
                match.sheets = sheets
            if camera_config is not None:
                match.camera_config = camera_config
            if teams is not None:
                match.teams = teams
            if players is not None:
                match.players = players
            if match_name is not None:
                match.match_name = match_name
            if description is not None:
                match.description = description
            return match

    def stop_match(self, match_id: str, end_time: str | None = None, record_url: str | None = None) -> MatchRuntime:
        """停止直播阶段；V2 stop 不再自动进入剪辑。"""

        with self._lock:
            match = self.get_match(match_id)
            if match.status != RuntimeStatus.RUNNING.value:
                raise ValueError(f"match is not running: {match_id}")
            match.status = RuntimeStatus.COMPLETED.value
            match.end_time = end_time
            match.record_url = record_url
            match.edit_status = EditStatus.NOT_STARTED.value
            match.edit_progress = 0
            for sheet in match.sheets.values():
                sheet.status = RuntimeStatus.STOPPED.value
                sheet.edit_status = EditStatus.NOT_STARTED.value
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
