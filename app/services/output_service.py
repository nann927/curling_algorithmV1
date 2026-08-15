"""输出查询服务。

所有查询接口只读取 Runtime/History，不在查询时创建实时流或赛后结果。
"""

from app.core.enums import EditStatus
from app.core.runtime import MatchRuntime, runtime_manager
from app.models.edit import EditResultData, EditStatusData, MediaResult, SheetEditStatus
from app.models.media import DirectorOutputData
from app.services.postprocess_service import PostProcessService
from app.storage.match_record_repository import MatchRecordRepository


class OutputService:
    """IF-02/IF-03/IF-04 的数据组装层。"""

    def __init__(self, postprocess_service: PostProcessService | None = None, record_repository: MatchRecordRepository | None = None) -> None:
        self._postprocess = postprocess_service or PostProcessService()
        self._records = record_repository or MatchRecordRepository()

    def get_director_output(self, match_id: str) -> DirectorOutputData:
        """返回当前 match 的唯一实时输出。"""

        match = runtime_manager.get_match(match_id)
        return self._director_data(match)

    def get_edit_status(self, match_id: str) -> EditStatusData:
        """返回 match 级和 sheet 级赛后进度。"""

        try:
            match = runtime_manager.get_match(match_id)
        except KeyError:
            record = self._records.get(match_id)
            if record is None:
                raise
            return EditStatusData(
                match_id=match_id,
                status=record["edit_status"],
                progress=100 if record["edit_status"] == EditStatus.COMPLETED.value else 0,
                sheets=[SheetEditStatus(sheet_id=record["sheet_id"], status=record["edit_status"], progress=0)],
            )
        self._postprocess.refresh(match)
        sheets = [
            SheetEditStatus(sheet_id=sheet.sheet_id, status=sheet.edit_status, progress=sheet.edit_progress)
            for sheet in match.sheets.values()
        ]
        return EditStatusData(match_id=match.match_id, status=match.edit_status, progress=match.edit_progress, sheets=sheets)

    def get_edit_result(self, match_id: str) -> EditResultData:
        """返回已记录的赛后成品 URL；not_started/processing 阶段 results 为空。"""

        match = runtime_manager.get_match(match_id)
        self._postprocess.refresh(match)
        results = [MediaResult(**item) for item in match.results] if match.edit_status == EditStatus.COMPLETED.value else []
        return EditResultData(
            match_id=match.match_id,
            scene_type=match.scene_type,
            status=match.edit_status,
            result_mode=match.result_mode,
            results=results,
        )

    def _director_data(self, match: MatchRuntime) -> DirectorOutputData:
        """把唯一 SheetRuntime 转换为 V2 单输出结构。"""

        sheet_id = match.sheet_id or next(iter(match.sheets))
        sheet = match.sheets[sheet_id]
        return DirectorOutputData(
            match_id=match.match_id,
            sheet_id=sheet.sheet_id,
            scene_type=match.scene_type,
            status=match.status,
            media_url=sheet.media_url or match.media_url or "",
            stream_type=sheet.stream_type,
        )
