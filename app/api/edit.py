"""IF-03/IF-04 赛后处理查询接口。"""

from fastapi import APIRouter, HTTPException

from app.models.match import ApiResponse
from app.services.output_service import OutputService

router = APIRouter(prefix="/api/v1/edit", tags=["edit"])


@router.get("/status", response_model=ApiResponse)
async def get_edit_status(match_id: str) -> ApiResponse:
    """查询赛后处理状态和进度。"""

    try:
        data = OutputService().get_edit_status(match_id).model_dump()
        return ApiResponse(data=data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": 404, "message": str(exc), "data": {}}) from exc


@router.get("/result", response_model=ApiResponse)
async def get_edit_result(match_id: str) -> ApiResponse:
    """查询已上传完成的赛后成品地址。"""

    try:
        data = OutputService().get_edit_result(match_id).model_dump()
        return ApiResponse(data=data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": 404, "message": str(exc), "data": {}}) from exc
