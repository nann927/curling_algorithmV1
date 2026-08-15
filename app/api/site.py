"""赛道资源查询接口。"""

from fastapi import APIRouter

from app.models.match import ApiResponse
from app.services.site_service import SiteService

router = APIRouter(prefix="/api/v1/site", tags=["site"])


@router.get("/resources", response_model=ApiResponse)
async def get_site_resources() -> ApiResponse:
    """返回 6 条赛道资源、预览地址和直播占用状态。"""

    return ApiResponse(data=SiteService().get_resources())
