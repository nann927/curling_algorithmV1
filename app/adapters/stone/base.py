"""电子冰壶数据源抽象。"""

from typing import Protocol

from app.models.event import TriggerEvent
from app.models.stone import StonePosition


class StoneSource(Protocol):
    """冰壶方定位/出发数据的统一读取接口。"""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    # 当前返回 dict 是为了等待正式协议确认，后续可收敛为 Pydantic 模型。
    def read_position(self) -> dict | None: ...

    def read_departure_event(self) -> dict | None: ...


class PositionProvider(Protocol):
    """定位数据 Provider 抽象。"""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def reset(self) -> None: ...

    def read_position(self) -> StonePosition | None: ...


class TriggerProvider(Protocol):
    """触发数据 Provider 抽象。"""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def reset(self) -> None: ...

    def read_trigger(self) -> TriggerEvent | None: ...
