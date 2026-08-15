"""日志初始化模块。"""

import logging
from pathlib import Path

from app.core.config import get_settings


def configure_logging() -> None:
    """配置统一日志输出到控制台和 data/logs/app.log。"""

    settings = get_settings()
    log_path = Path(settings.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        # 部署或测试环境中日志文件可能被占用/权限受限，此时降级为控制台日志，不影响服务启动。
        handlers.insert(0, logging.FileHandler(log_path, encoding="utf-8"))
    except OSError as exc:
        logging.getLogger(__name__).warning("file logger disabled: %s", exc)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=False,
    )
