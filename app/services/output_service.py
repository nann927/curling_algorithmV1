"""输出查询服务。

所有查询接口只读取 Runtime，不在查询时创建实时流或赛后结果。
"""

from app.core.runtime import MatchRuntime, runtime_manager
from app.models.edit import EditResultData, EditStatusData, MediaResult, SheetEditStatus
from app.models.media import DirectorOutputData, LiveOutput
from app.services.postprocess_service import PostProcessService


class OutputService:
    """IF-02/IF-03/IF-04 的数据组装层。"""

    def __init__(self, postprocess_service: PostProcessService | None = None) -> None:
        self._postprocess = postprocess_service or PostProcessService()

    def get_director_output(self, match_id: str) -> DirectorOutputData:
        """返回当前 match 下所有有效赛道的实时输出。"""

        match = runtime_manager.get_match(match_id)
        return self._director_data(match)

    def get_edit_status(self, match_id: str) -> EditStatusData:
        """返回 match 级和 sheet 级赛后进度。"""

        match = runtime_manager.get_match(match_id)
        self._postprocess.refresh(match)
        sheets = [
            SheetEditStatus(sheet_id=sheet.sheet_id, status=sheet.edit_status, progress=sheet.edit_progress)
            for sheet in match.sheets.values()
        ]
        return EditStatusData(
            match_id=match.match_id,
            status=match.edit_status,
            progress=match.edit_progress,
            sheets=sheets,
        )

    def get_edit_result(self, match_id: str) -> EditResultData:
        """返回已记录的赛后成品 URL。"""

        match = runtime_manager.get_match(match_id)
        self._postprocess.refresh(match)
        results = [MediaResult(**item) for item in match.results]
        return EditResultData(
            match_id=match.match_id,
            scene_type=match.scene_type,
            status=match.edit_status,
            result_mode=match.result_mode,
            results=results,
        )

    def _director_data(self, match: MatchRuntime) -> DirectorOutputData:
        """把 SheetRuntime 转换为软件平台需要的 outputs 数组。"""

        outputs = [
            LiveOutput(sheet_id=sheet.sheet_id, stream_type=sheet.stream_type, media_url=sheet.media_url or "")
            for sheet in match.sheets.values()
            if sheet.enabled and sheet.media_url
        ]
        return DirectorOutputData(
            match_id=match.match_id,
            scene_type=match.scene_type,
            status=match.status,
            outputs=outputs,
        )
