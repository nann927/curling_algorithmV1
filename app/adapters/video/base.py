"""视频源 Provider 抽象。"""

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import SiteCameraConfig


@dataclass
class VideoSourceHandle:
    """一路视频源启动后的句柄。"""

    camera_id: str
    provider: str
    media_url: str
    process_id: str | None = None
    metadata: dict = field(default_factory=dict)


class VideoSourceProvider(Protocol):
    """视频源 Provider 统一接口。"""

    provider_name: str

    def start(self, match_id: str, sheet_id: str, camera: SiteCameraConfig) -> VideoSourceHandle: ...

    def stop(self, handle: VideoSourceHandle) -> None: ...
