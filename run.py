"""服务启动入口。

生产或联调部署时可以直接执行 `python run.py` 启动 Uvicorn。
"""

import uvicorn

from app.core.config import get_settings


if __name__ == "__main__":
    # host/port 通过环境变量控制，公网联调只需修改 HOST/PORT，不写死公网 IP。
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
