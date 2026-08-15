"""IF-03/IF-04 赛后处理查询接口。"""

from fastapi import APIRouter, HTTPException

from app.models.edit import EditControlRequest
from app.models.match import ApiResponse
from app.services.output_service import OutputService
from app.services.postprocess_service import PostProcessService

router = APIRouter(prefix="/api/v1/edit", tags=["edit"])


@router.post("/control", response_model=ApiResponse)
async def control_edit(request: EditControlRequest) -> ApiResponse:
    """软件方主动发起剪辑。"""

    try:
        if request.action != "start":
            raise ValueError("only action=start is supported")
        match = PostProcessService().start(request.match_id)
        return ApiResponse(data={"match_id": match.match_id, "status": match.edit_status, "progress": match.edit_progress})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": 404, "message": str(exc), "data": {}}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": 400, "message": str(exc), "data": {}}) from exc


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
