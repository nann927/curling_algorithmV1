"""电子冰壶 Mock 数据源。"""

from app.models.event import TriggerEvent
from app.models.stone import StonePosition


class MockStoneSource:
    """当前不模拟复杂运动，仅保留可替换接口。"""

    def start(self) -> None:
        """启动 Mock 数据源。"""

        return None

    def stop(self) -> None:
        """停止 Mock 数据源。"""

        return None

    def read_position(self) -> dict | None:
        """读取一条 Mock 定位数据；Phase 2 暂不产生数据。"""

        return None

    def read_departure_event(self) -> dict | None:
        """读取一条 Mock 出发事件；Phase 2 暂不产生数据。"""

        return None


class MockPositionProvider:
    """开发阶段定位 Provider 占位。"""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def reset(self) -> None:
        return None

    def read_position(self) -> StonePosition | None:
        return None


class MockTriggerProvider:
    """开发阶段触发 Provider 占位。"""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def reset(self) -> None:
        return None

    def read_trigger(self) -> TriggerEvent | None:
        return None
