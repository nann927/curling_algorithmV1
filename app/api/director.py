"""IF-02 当前实时导播输出查询接口。"""

from fastapi import APIRouter, HTTPException

from app.models.match import ApiResponse
from app.services.output_service import OutputService

router = APIRouter(prefix="/api/v1/director", tags=["director"])


@router.get("/output", response_model=ApiResponse)
async def get_director_output(match_id: str) -> ApiResponse:
    """读取 Runtime 中已有输出，不临时创建或重启视频流。"""

    try:
        data = OutputService().get_director_output(match_id).model_dump()
        return ApiResponse(data=data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": 404, "message": str(exc), "data": {}}) from exc
