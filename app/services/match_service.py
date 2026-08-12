"""导播任务生命周期编排服务。

API 层只负责接收请求；start/update_config/stop 的业务规则集中在本服务。
"""

from app.core.enums import OVERVIEW_SCENES, ControlAction, RuntimeStatus, SceneType
from app.core.config import ConfigManager, get_config_manager
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.models.match import CameraConfig, MatchControlRequest
from app.models.media import DirectorOutputData
from app.services.director_service import DirectorService
from app.services.output_service import OutputService
from app.services.overview_service import OverviewService
from app.services.postprocess_service import PostProcessService


class MatchService:
    """IF-01 控制动作的核心编排入口。"""

    def __init__(
        self,
        director_service: DirectorService | None = None,
        overview_service: OverviewService | None = None,
        output_service: OutputService | None = None,
        postprocess_service: PostProcessService | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        # 依赖都通过构造函数注入，便于后续替换为真实 provider 或在测试中 Mock。
        self._config_manager = config_manager or get_config_manager()
        self._director = director_service or DirectorService()
        self._overview = overview_service or OverviewService()
        self._output = output_service or OutputService()
        self._postprocess = postprocess_service or PostProcessService()

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
        """创建 MatchRuntime，并根据 scene_type 创建多条 SheetRuntime。"""

        self._validate_start(request)
        assert request.scene_type is not None
        assert request.start_time is not None
        assert request.camera_config is not None

        camera_config = request.camera_config.model_dump()
        # Runtime 中保存软件平台传入的完整有效配置，便于后续查询和覆盖更新。
        match = MatchRuntime(
            match_id=request.match_id,
            scene_type=request.scene_type,
            start_time=request.start_time,
            teams=[team.model_dump() for team in request.teams or []],
            players=[player.model_dump() for player in request.players or []],
            camera_config=camera_config,
            sheets=self._build_sheets(request.match_id, request.scene_type, request.camera_config),
        )
        runtime_manager.create_match(match)
        return self._output.get_director_output(request.match_id)

    def update_config(self, request: MatchControlRequest) -> DirectorOutputData:
        """用新的完整配置覆盖当前有效配置。"""

        if request.camera_config is None:
            raise ValueError("camera_config is required for update_config")
        self._validate_camera_config(request.camera_config)
        match = runtime_manager.get_match(request.match_id)
        if match.status != RuntimeStatus.RUNNING.value:
            raise ValueError("only running match can be updated")

        # Phase 3 当前允许重启服务生效配置；update_config 负责停止旧源并启动新源。
        if match.scene_type != SceneType.COMPETITION.value:
            self._overview.stop_match(match.match_id)
        new_sheets = self._build_sheets(match.match_id, match.scene_type, request.camera_config)
        runtime_manager.update_match_config(
            match_id=match.match_id,
            camera_config=request.camera_config.model_dump(),
            sheets=new_sheets,
            teams=[team.model_dump() for team in request.teams] if request.teams is not None else None,
            players=[player.model_dump() for player in request.players] if request.players is not None else None,
        )
        return self._output.get_director_output(match.match_id)

    def stop(self, request: MatchControlRequest) -> dict:
        """停止实时输出，并启动 Mock 赛后处理任务。"""

        match = runtime_manager.stop_match(request.match_id)
        if match.scene_type != SceneType.COMPETITION.value:
            self._overview.stop_match(match.match_id)
        self._postprocess.schedule(match)
        return {"match_id": match.match_id, "status": match.status}

    def _build_sheets(self, match_id: str, scene_type: str, camera_config: CameraConfig) -> dict[str, SheetRuntime]:
        """按场景创建赛道 Runtime：竞赛走智能导播，其他场景走全景输出。"""

        sheets: dict[str, SheetRuntime] = {}
        overview_camera_id = None
        if scene_type != SceneType.COMPETITION.value:
            overview_camera_id = self._config_manager.get_overview_camera_id(camera_config.overview_cameras)
        for sheet_config in camera_config.sheets:
            if scene_type == SceneType.COMPETITION.value:
                sheet = self._director.start_sheet(match_id, sheet_config.sheet_id, sheet_config.house_camera_ends)
            else:
                assert overview_camera_id is not None
                sheet = self._overview.start_sheet(
                    match_id,
                    sheet_config.sheet_id,
                    sheet_config.house_camera_ends,
                    overview_camera_id,
                )
            sheets[sheet.sheet_id] = sheet
        return sheets

    def _validate_start(self, request: MatchControlRequest) -> None:
        """校验 start 必填字段和场景约束。"""

        if not request.scene_type:
            raise ValueError("scene_type is required for start")
        try:
            scene_type = SceneType(request.scene_type)
        except ValueError as exc:
            raise ValueError(f"invalid scene_type: {request.scene_type}") from exc
        if not request.start_time:
            raise ValueError("start_time is required for start")
        if request.camera_config is None:
            raise ValueError("camera_config is required for start")
        self._validate_camera_config(request.camera_config)
        if scene_type == SceneType.COMPETITION:
            for sheet in request.camera_config.sheets:
                if not sheet.house_camera_ends:
                    raise ValueError("house_camera_ends is required for competition sheets")
        elif scene_type not in OVERVIEW_SCENES:
            raise ValueError(f"invalid scene_type: {request.scene_type}")

    def _validate_camera_config(self, camera_config: CameraConfig) -> None:
        """校验 camera_config 的基础结构，避免空赛道或重复赛道。"""

        if not camera_config.overview_cameras:
            raise ValueError("camera_config.overview_cameras must not be empty")
        if not camera_config.sheets:
            raise ValueError("camera_config.sheets must not be empty")
        seen: set[str] = set()
        for sheet in camera_config.sheets:
            if sheet.sheet_id in seen:
                raise ValueError(f"duplicate sheet_id: {sheet.sheet_id}")
            self._config_manager.validate_sheet_id(sheet.sheet_id)
            seen.add(sheet.sheet_id)
        for camera_id in camera_config.overview_cameras:
            self._config_manager.get_camera(camera_id)
