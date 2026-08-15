"""IF-01 导播任务控制接口。"""

from fastapi import APIRouter, HTTPException

from app.models.match import ApiResponse, MatchControlRequest
from app.services.match_service import MatchService
from app.storage.match_record_repository import MatchRecordRepository

router = APIRouter(prefix="/api/v1/match", tags=["match"])


@router.post("/control", response_model=ApiResponse)
async def control_match(request: MatchControlRequest) -> ApiResponse:
    """接收 start/update_config/stop，并把业务编排交给 MatchService。"""

    try:
        data = MatchService().control(request)
        return ApiResponse(data=data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": 404, "message": str(exc), "data": {}}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": 400, "message": str(exc), "data": {}}) from exc


@router.get("/history", response_model=ApiResponse)
async def get_match_history() -> ApiResponse:
    """返回算法服务器实际执行过的历史导播记录。"""

    return ApiResponse(data={"records": MatchRecordRepository().list_all()})
