"""赛后处理 Mock 服务。

Phase 4.6 后 stop 不再自动剪辑；只有 /api/v1/edit/control action=start 才会启动本服务。
真实剪辑、识别、拼接和上传协议后续都应在这里按服务边界接入。
"""

import asyncio
import json
import logging
from threading import Thread

from app.adapters.software.uploader import SoftwareUploader
from app.core.enums import EditStatus, ResultMode, ResultType, RuntimeStatus, SceneType
from app.core.runtime import MatchRuntime, SheetRuntime, runtime_manager
from app.services.integration_mock_service import IntegrationMockService
from app.storage.match_record_repository import MatchRecordRepository

logger = logging.getLogger(__name__)


class PostProcessService:
    """赛后处理总控服务。"""

    def __init__(
        self,
        uploader: SoftwareUploader | None = None,
        delay_seconds: float = 0.05,
        integration_mock: IntegrationMockService | None = None,
        record_repository: MatchRecordRepository | None = None,
    ) -> None:
        self._uploader = uploader or SoftwareUploader()
        self._delay_seconds = delay_seconds
        self._integration_mock = integration_mock or IntegrationMockService()
        self._records = record_repository or MatchRecordRepository()

    def start(self, match_id: str) -> MatchRuntime:
        """软件主动发起剪辑；重复 start 按当前状态幂等返回。"""

        match = self._get_or_restore_match(match_id)
        record = self._records.get(match_id)
        if record is None:
            raise KeyError(f"match history not found: {match_id}")
        if record["record_status"] != "completed" or match.status == RuntimeStatus.RUNNING.value:
            raise ValueError("record is not ready for edit")
        if match.edit_status == EditStatus.PROCESSING.value:
            return match
        if match.edit_status == EditStatus.COMPLETED.value:
            return match

        if self._integration_mock.enabled():
            self._start_integration_processing(match)
            self._records.update_edit_status(match.match_id, match.edit_status)
            return match
        match.edit_status = EditStatus.PROCESSING.value
        match.edit_progress = 10
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.PROCESSING.value
            sheet.edit_progress = 10
        self._records.update_edit_status(match.match_id, match.edit_status)
        Thread(target=lambda: asyncio.run(self.process(match)), daemon=True).start()
        return match

    def refresh(self, match: MatchRuntime) -> None:
        """刷新 Integration Mock 赛后状态。"""

        if not self._integration_mock.enabled():
            return
        if match.edit_status != EditStatus.PROCESSING.value or match.postprocess_started_at is None:
            return
        duration = match.postprocess_duration_seconds or self._integration_mock.config.postprocess.processing_duration_seconds
        elapsed = self._integration_mock.now() - match.postprocess_started_at
        progress = self._integration_mock.progress_for_elapsed(elapsed)
        if elapsed < duration:
            self._set_progress(match, progress)
            self._records.update_edit_status(match.match_id, match.edit_status)
            return
        self._complete_match(match)

    async def process(self, match: MatchRuntime) -> None:
        """执行开发环境 Mock 后处理状态流转。"""

        match.edit_status = EditStatus.PROCESSING.value
        match.edit_progress = 10
        self._records.update_edit_status(match.match_id, match.edit_status)
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.PROCESSING.value
            sheet.edit_progress = 10

        await asyncio.sleep(self._delay_seconds)
        self._complete_match(match)

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
        """完成 Mock 赛后处理并记录上传结果。"""

        if match.postprocess_uploaded and match.edit_status == EditStatus.COMPLETED.value:
            return
        uploaded_results: list[dict] = []
        for item in self._build_local_results(match):
            upload = self._uploader.upload(match.match_id, item["local_path"])
            if not upload.success or not upload.media_url:
                match.edit_status = EditStatus.FAILED.value
                self._records.update_edit_status(match.match_id, match.edit_status)
                for sheet in match.sheets.values():
                    sheet.edit_status = EditStatus.FAILED.value
                logger.error("mock upload failed for %s", item["local_path"])
                return
            result = {key: value for key, value in item.items() if key != "local_path"}
            result["media_url"] = upload.media_url
            uploaded_results.append(result)
        match.results = uploaded_results
        match.postprocess_uploaded = True
        match.edit_status = EditStatus.COMPLETED.value
        match.edit_progress = 100
        self._records.update_edit_status(match.match_id, match.edit_status)
        for sheet in match.sheets.values():
            sheet.edit_status = EditStatus.COMPLETED.value
            sheet.edit_progress = 100

    def _build_local_results(self, match: MatchRuntime) -> list[dict]:
        """按 scene_type 构造本地成品元数据。"""

        sheet_ids = list(match.sheets) or ([match.sheet_id] if match.sheet_id else [])
        if match.scene_type == SceneType.COMPETITION.value:
            if match.players or match.teams:
                match.result_mode = ResultMode.MATCHED_HIGHLIGHTS.value
                results: list[dict] = []
                for sheet_id in sheet_ids:
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
            return [
                {
                    "result_type": ResultType.LABELED_CLIP.value,
                    "sheet_id": sheet_id,
                    "clip_id": f"{sheet_id}_clip_0001",
                    "label": "person_001",
                    "local_path": f"data/clips/{match.match_id}/{sheet_id}/clip_0001.mp4",
                }
                for sheet_id in sheet_ids
            ]

        match.result_mode = ResultMode.PARTICIPANT_MEDIA.value
        first_player = match.players[0] if match.players else {}
        person_label = first_player.get("player_name") or "person_001"
        player_id = first_player.get("player_id")
        results = []
        for sheet_id in sheet_ids:
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
        return results

    def _load_json_list(self, value: str | None) -> list[dict]:
        """从 match_records 恢复 JSON 列；历史空值或损坏值按空列表处理。"""

        if not value:
            return []
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("invalid match record json ignored")
            return []
        return data if isinstance(data, list) else []
    def _get_or_restore_match(self, match_id: str) -> MatchRuntime:
        """优先读取 Runtime；重启后可从 match_records 恢复最小剪辑 Runtime。"""

        try:
            return runtime_manager.get_match(match_id)
        except KeyError:
            record = self._records.get(match_id)
            if record is None:
                raise
            sheet = SheetRuntime(
                sheet_id=record["sheet_id"],
                enabled=True,
                stream_type="smart_director",
                media_url=record.get("media_url"),
                status=RuntimeStatus.STOPPED.value,
                edit_status=record["edit_status"],
            )
            match = MatchRuntime(
                match_id=record["match_id"],
                sheet_id=record["sheet_id"],
                scene_type=record["scene_type"],
                start_time=record["start_time"],
                end_time=record.get("end_time"),
                media_url=record.get("media_url"),
                record_url=record.get("record_url"),
                status=RuntimeStatus.COMPLETED.value,
                edit_status=record["edit_status"],
                teams=self._load_json_list(record.get("teams_json")),
                players=self._load_json_list(record.get("players_json")),
                sheets={record["sheet_id"]: sheet},
            )
            runtime_manager.create_match(match)
            return match



