"""FastAPI 应用装配入口。

本文件只负责应用初始化、通用异常响应、健康检查和路由注册。
业务编排下沉到 services，避免 API 层和核心逻辑耦合。
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.responses import JSONResponse

from app.api import director, edit, match, site
from app.core.config import get_settings
from app.core.logger import configure_logging
from app.storage.database import init_db


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例，并完成基础设施初始化。"""

    configure_logging()
    settings = get_settings()
    init_db(settings.sqlite_path)

    app = FastAPI(title="Curling Smart Director Algorithm Service", version="0.1.0")
    if settings.cors_origins:
        # CORS 默认关闭；只有显式配置 Origin 时才启用，避免公网联调服务无条件开放。
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
        # 保持接口统一响应结构，便于软件平台按 code/message/data 处理。
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "validation error", "data": {"errors": exc.errors()}},
        )

    @app.get("/health")
    async def health() -> dict:
        # 健康检查不触发任何外部设备或后台任务。
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "ok",
                "environment": settings.app_env,
                "mock_mode": settings.mock_mode,
            },
        }

    @app.get("/integration/media/{media_path:path}")
    async def integration_media(media_path: str) -> PlainTextResponse:
        """Integration Mock 辅助媒体路由。

        该路由只用于公网联调验证 URL 可访问，不替代 IF-01～IF-04。
        """

        if not (settings.app_env == "integration" and settings.mock_mode):
            return PlainTextResponse("integration media disabled", status_code=404)
        if media_path.endswith(".m3u8"):
            body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\nsegment_000.ts\n"
            return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl")
        return PlainTextResponse("integration mock media", media_type="text/plain")

    app.include_router(site.router)
    app.include_router(match.router)
    app.include_router(director.router)
    app.include_router(edit.router)
    return app


app = create_app()


