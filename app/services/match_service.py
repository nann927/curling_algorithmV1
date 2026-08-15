"""导播任务生命周期编排服务。

Phase 4.6：正式接口升级为 1 match_id = 1 sheet_id，stop 只结束直播并保存历史，不自动剪辑。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import ConfigManager, get_config_manager
from app.core.enums import OVERVIEW_SCENES, ControlAction, RuntimeStatus, SceneType
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.match import MatchControlRequest
from app.models.media import DirectorOutputData
from app.services.director_service import DirectorService
from app.services.integration_mock_service import IntegrationMockService
from app.services.output_service import OutputService
from app.services.overview_service import OverviewService
from app.storage.match_record_repository import MatchRecordRepository


class MatchService:
    """IF-01 控制动作的核心编排入口。"""

    def __init__(
        self,
        director_service: DirectorService | None = None,
        overview_service: OverviewService | None = None,
        output_service: OutputService | None = None,
        config_manager: ConfigManager | None = None,
        integration_mock: IntegrationMockService | None = None,
        record_repository: MatchRecordRepository | None = None,
    ) -> None:
        self._config_manager = config_manager or get_config_manager()
        self._director = director_service or DirectorService()
        self._overview = overview_service or OverviewService()
        self._output = output_service or OutputService()
        self._integration_mock = integration_mock or IntegrationMockService()
        self._records = record_repository or MatchRecordRepository()

    def control(self, request: MatchControlRequest) -> dict:
        """按 action 分发到具体生命周期方法。"""

        if request.action == ControlAction.START.value:
            return self.start(request).model_dump()
        if request.action == ControlAction.UPDATE_CONFIG.value:
            return self.update_config(request).model_dump()
        if request.action == ControlAction.STOP.value:
            return self.stop(request)
        raise ValueError(f"unsupported action: {request.action}")

    def start(self, request: MatchControlRequest) -> DirectorOutputData:
        """创建单赛道 MatchRuntime，并返回唯一 media_url。"""

        self._validate_start(request)
        assert request.scene_type is not None
        assert request.start_time is not None
        assert request.sheet_id is not None

        sheet = self._build_sheet(request.match_id, request.scene_type, request.sheet_id)
        match = MatchRuntime(
            match_id=request.match_id,
            sheet_id=request.sheet_id,
            scene_type=request.scene_type,
            start_time=request.start_time,
            teams=[team.model_dump() for team in request.teams or []],
            players=[player.model_dump() for player in request.players or []],
            camera_config=request.camera_config.model_dump() if request.camera_config else {},
            sheets={request.sheet_id: sheet},
            media_url=sheet.media_url,
        )
        runtime_manager.create_match(match)
        self._records.upsert_started(
            match_id=match.match_id,
            sheet_id=match.sheet_id or request.sheet_id,
            scene_type=match.scene_type,
            start_time=match.start_time,
            media_url=match.media_url,
            teams=match.teams,
            players=match.players,
        )
        return self._output.get_director_output(request.match_id)

    def update_config(self, request: MatchControlRequest) -> DirectorOutputData:
        """更新业务配置；V2 不允许切换 sheet_id。"""

        match = runtime_manager.get_match(request.match_id)
        if match.status != RuntimeStatus.RUNNING.value:
            raise ValueError("only running match can be updated")
        if request.sheet_id is not None and request.sheet_id != match.sheet_id:
            raise ValueError("sheet_id cannot be changed after start")
        runtime_manager.update_match_config(
            match_id=match.match_id,
            camera_config=request.camera_config.model_dump() if request.camera_config else match.camera_config,
            teams=[team.model_dump() for team in request.teams] if request.teams is not None else None,
            players=[player.model_dump() for player in request.players] if request.players is not None else None,
        )
        return self._output.get_director_output(match.match_id)

    def stop(self, request: MatchControlRequest) -> dict:
        """停止直播、保存录像引用并释放赛道；不启动剪辑。"""

        match = runtime_manager.get_match(request.match_id)
        sheet_id = match.sheet_id or next(iter(match.sheets))
        if match.scene_type != SceneType.COMPETITION.value:
            self._overview.stop_match(match.match_id)
        end_time = datetime.now(timezone.utc).isoformat()
        record_url = self._integration_mock.record_media_url(match.match_id, sheet_id) if self._integration_mock.enabled() else f"mock://{match.match_id}/{sheet_id}/record/program.mp4"
        runtime_manager.stop_match(request.match_id, end_time=end_time, record_url=record_url)
        self._records.mark_stopped(match_id=match.match_id, end_time=end_time, record_url=record_url)
        return {
            "match_id": match.match_id,
            "sheet_id": sheet_id,
            "status": match.status,
            "record_status": "completed",
            "edit_status": match.edit_status,
            "record_url": record_url,
        }

    def _build_sheet(self, match_id: str, scene_type: str, sheet_id: str) -> SheetRuntime:
        """按场景创建唯一 SheetRuntime。"""

        if scene_type == SceneType.COMPETITION.value:
            return self._director.start_sheet(match_id, sheet_id, ["A", "B"])
        overview_camera_id = self._select_overview_camera()
        return self._overview.start_sheet(match_id, sheet_id, [], overview_camera_id)

    def _select_overview_camera(self) -> str:
        """V2 中软件不再传 camera_id，算法从 site_config 自动选第一路全景。"""

        overview_ids = self._config_manager.get_overview_camera_ids()
        if not overview_ids:
            raise ValueError("overview camera is not configured")
        return overview_ids[0]

    def _validate_start(self, request: MatchControlRequest) -> None:
        """校验 start 必填字段和 V2 赛道占用规则。"""

        if not request.match_id.strip():
            raise ValueError("match_id is required")
        if self._records.get(request.match_id) is not None:
            # match_records 是跨重启的事实来源，历史中出现过的 match_id 不允许再次开播。
            raise ValueError(f"match_id already exists: {request.match_id}")
        if not request.sheet_id:
            raise ValueError("sheet_id is required for start")
        self._config_manager.validate_sheet_id(request.sheet_id)
        if runtime_manager.is_sheet_occupied(request.sheet_id):
            raise ValueError(f"sheet already occupied: {request.sheet_id}")
        if not request.scene_type:
            raise ValueError("scene_type is required for start")
        try:
            scene_type = SceneType(request.scene_type)
        except ValueError as exc:
            raise ValueError(f"invalid scene_type: {request.scene_type}") from exc
        if scene_type != SceneType.COMPETITION and scene_type not in OVERVIEW_SCENES:
            raise ValueError(f"invalid scene_type: {request.scene_type}")
        if not request.start_time:
            raise ValueError("start_time is required for start")

