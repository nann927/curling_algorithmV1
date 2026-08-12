"""软件平台上传适配器。

真实上传 URL、鉴权、字段名和响应格式尚未确认；本阶段使用 Mock 上传结果。
"""

from pydantic import BaseModel

from app.services.integration_mock_service import IntegrationMockService


class UploadResult(BaseModel):
    """上传适配器统一返回结构。"""

    success: bool
    media_url: str | None = None


class SoftwareUploader:
    """软件平台上传边界。"""

    def __init__(self, integration_mock: IntegrationMockService | None = None) -> None:
        self._integration_mock = integration_mock or IntegrationMockService()

    def upload(self, match_id: str, local_path: str) -> UploadResult:
        """模拟上传成功，并返回软件服务器上的 mock media_url。"""

        filename = local_path.replace("\\", "/").rstrip("/").split("/")[-1]
        if self._integration_mock.enabled():
            return UploadResult(success=True, media_url=self._integration_mock.result_media_url(match_id, filename))
        return UploadResult(success=True, media_url=f"http://software-server/mock/{match_id}/{filename}")
