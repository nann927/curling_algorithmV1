"""日志初始化模块。"""

import logging
from pathlib import Path

from app.core.config import get_settings


def configure_logging() -> None:
    """配置统一日志输出到控制台和 data/logs/app.log。"""

    settings = get_settings()
    log_path = Path(settings.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=False,
    )
