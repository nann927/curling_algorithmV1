"""赛后处理 Mock 服务。

当前只实现 Phase 2 闭环：生成本地结果元数据、调用 Mock 上传、上传成功后置 completed。
真实剪辑、识别、拼接和上传协议后续都应在这里按服务边界接入。
"""

import asyncio
import logging
from threading import Thread

from app.adapters.software.uploader import SoftwareUploader
from app.core.enums import EditStatus, ResultMode, ResultType, SceneType
from app.core.runtime import MatchRuntime
from app.services.integration_mock_service import IntegrationMockService

logger = logging.getLogger(__name__)


class PostProcessService:
    """赛后处理总控服务。"""

    def __init__(
        self,
        uploader: SoftwareUploader | None = None,
        delay_seconds: float = 0.05,
        integration_mock: IntegrationMockService | None = None,
    ) -> None:
        # uploader 可注入，方便后续替换真实软件上传接口或测试失败分支。
        self._uploader = uploader or SoftwareUploader()
        self._delay_seconds = delay_seconds
        self._integration_mock = integration_mock or IntegrationMockService()

    def schedule(self, match: MatchRuntime) -> None:
        """异步启动 Mock 赛后处理，API 不等待剪辑完成。"""

        if self._integration_mock.enabled():
            self._start_integration_processing(match)
            return
        # 使用后台线程避免依赖请求级事件循环生命周期，便于 TestClient 和本地运行保持一致。
        Thread(target=lambda: asyncio.run(self.process(match)), daemon=True).start()

    def refresh(self, match: MatchRuntime) -> None:
        """刷新 Integration Mock 赛后状态。

        GET edit/status 和 edit/result 只读取状态；这里根据启动时间推进已存在的 Mock 任务，不在 GET 中
        临时创建新的赛后任务。
        """

        if not self._integration_mock.enabled():
            return
        if match.edit_status != EditStatus.PROCESSING.value or match.postprocess_started_at is None:
            return
        duration = match.postprocess_duration_seconds or self._integration_mock.config.postprocess.processing_duration_seconds
        elapsed = self._integration_mock.now() - match.postprocess_started_at
        progress = self._integration_mock.progress_for_elapsed(elapsed)
        if elapsed < duration:
            self._set_progress(match, progress)
            return
        self._complete_match(match)

    async def process(self, match: MatchRuntime) -> None:
        """执行 Mock 后处理状态流转。"""

        match.edit_status = EditStatus.PROCESSING.value
        match.edit_progress = 10
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.PROCESSING.value
            sheet.edit_progress = 10

        await asyncio.sleep(self._delay_seconds)

        local_results = self._build_local_results(match)
        uploaded_results: list[dict] = []
        for item in local_results:
            # completed 的前置条件是上传成功并拿到 media_url。
            upload = self._uploader.upload(match.match_id, item["local_path"])
            if not upload.success or not upload.media_url:
                match.edit_status = EditStatus.FAILED.value
                for sheet in match.sheets.values():
                    sheet.edit_status = EditStatus.FAILED.value
                logger.error("mock upload failed for %s", item["local_path"])
                return
            result = {key: value for key, value in item.items() if key != "local_path"}
            result["media_url"] = upload.media_url
            uploaded_results.append(result)

        match.results = uploaded_results
        # 严格在全部结果上传成功之后，才允许整体状态变为 completed。
        match.edit_status = EditStatus.COMPLETED.value
        match.edit_progress = 100
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.COMPLETED.value
            sheet.edit_progress = 100

    def _start_integration_processing(self, match: MatchRuntime) -> None:
        """启动 Integration Mock 赛后处理，但不立即 completed。"""

        match.postprocess_started_at = self._integration_mock.now()
        match.postprocess_duration_seconds = self._integration_mock.config.postprocess.processing_duration_seconds
        match.postprocess_uploaded = False
        match.edit_status = EditStatus.PROCESSING.value
        self._set_progress(match, self._integration_mock.progress_for_elapsed(0))

    def _set_progress(self, match: MatchRuntime, progress: int) -> None:
        """同步 match 和 sheet 的赛后进度。"""

        match.edit_progress = progress
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.PROCESSING.value
            sheet.edit_progress = progress

    def _complete_match(self, match: MatchRuntime) -> None:
        """完成 Integration Mock 赛后处理并记录上传结果。"""

        if match.postprocess_uploaded:
            match.edit_status = EditStatus.COMPLETED.value
            match.edit_progress = 100
            return
        local_results = self._build_local_results(match)
        uploaded_results: list[dict] = []
        for item in local_results:
            upload = self._uploader.upload(match.match_id, item["local_path"])
            if not upload.success or not upload.media_url:
                match.edit_status = EditStatus.FAILED.value
                for sheet in match.sheets.values():
                    sheet.edit_status = EditStatus.FAILED.value
                return
            result = {key: value for key, value in item.items() if key != "local_path"}
            result["media_url"] = upload.media_url
            uploaded_results.append(result)
        match.results = uploaded_results
        match.postprocess_uploaded = True
        match.edit_status = EditStatus.COMPLETED.value
        match.edit_progress = 100
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.COMPLETED.value
            sheet.edit_progress = 100

    def _build_local_results(self, match: MatchRuntime) -> list[dict]:
        """按 scene_type 构造本地成品元数据。

        这里只构造 Mock 元数据，不做真实视频文件生成。
        """

        if match.scene_type == SceneType.COMPETITION.value:
            if match.players or match.teams:
                # 竞赛且存在业务人员/队伍时，返回匹配后的个人/团队集锦。
                match.result_mode = ResultMode.MATCHED_HIGHLIGHTS.value
                results: list[dict] = []
                for sheet_id in match.sheets:
                    if match.players:
                        player = match.players[0]
                        results.append(
                            {
                                "result_type": ResultType.PLAYER_HIGHLIGHT.value,
                                "sheet_id": sheet_id,
                                "player_id": player.get("player_id"),
                                "team_id": player.get("team_id"),
                                "label": player.get("player_name") or player.get("player_id"),
                                "local_path": f"data/highlights_temp/{match.match_id}/{sheet_id}_player_highlight.mp4",
                            }
                        )
                    if match.teams:
                        team = match.teams[0]
                        results.append(
                            {
                                "result_type": ResultType.TEAM_HIGHLIGHT.value,
                                "sheet_id": sheet_id,
                                "team_id": team.get("team_id"),
                                "label": team.get("team_name") or team.get("team_id"),
                                "local_path": f"data/highlights_temp/{match.match_id}/{sheet_id}_team_highlight.mp4",
                            }
                        )
                return results

            match.result_mode = ResultMode.LABELED_CLIPS.value
            # 竞赛但缺少人员/队伍信息时，只返回带临时标签的独立片段。
            return [
                {
                    "result_type": ResultType.LABELED_CLIP.value,
                    "sheet_id": sheet_id,
                    "clip_id": f"{sheet_id}_clip_0001",
                    "label": "person_001",
                    "local_path": f"data/clips/{match.match_id}/{sheet_id}/clip_0001.mp4",
                }
                for sheet_id in match.sheets
            ]

        match.result_mode = ResultMode.PARTICIPANT_MEDIA.value
        # 非竞赛场景保留参与人员视频和训练照片的结果结构。
        results = []
        first_player = match.players[0] if match.players else {}
        person_label = first_player.get("player_name") or "person_001"
        player_id = first_player.get("player_id")
        for sheet_id in match.sheets:
            results.append(
                {
                    "result_type": ResultType.PARTICIPANT_VIDEO.value,
                    "sheet_id": sheet_id,
                    "player_id": player_id,
                    "person_label": person_label,
                    "content_category": "training",
                    "label": f"{person_label}-training",
                    "local_path": f"data/participant_media_temp/{match.match_id}/{sheet_id}_participant_video.mp4",
                }
            )
            results.append(
                {
                    "result_type": ResultType.TRAINING_PHOTO.value,
                    "sheet_id": sheet_id,
                    "player_id": player_id,
                    "person_label": person_label,
                    "label": f"{person_label}-training-photo",
                    "local_path": f"data/photos/{match.match_id}/{sheet_id}_photo_001.jpg",
                }
            )
        return results
