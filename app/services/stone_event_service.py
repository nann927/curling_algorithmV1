"""电子冰壶触发事件编排服务。

一期投壶事件由 TriggerEvent 驱动；StonePosition 只交给 DirectionService 判断投壶方向。
"""

from app.core.runtime import SheetRuntime, runtime_manager
from app.models.event import TriggerEvent
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService, DirectionState


class StoneEventService:
    """处理 TriggerEvent 和 StonePosition 的轻量编排层。"""

    def __init__(self, direction_service: DirectionService | None = None) -> None:
        self._direction_service = direction_service or DirectionService()

    def process_trigger_event(self, event: TriggerEvent, match_id: str | None = None) -> DirectionState:
        """消费触发事件。

        touch 开启方向检测；departure 冻结方向；其他事件不由定位推断。
        """

        if event.event_type == "touch":
            state = self._direction_service.start_monitoring(event.sheet_id)
        elif event.event_type == "departure":
            state = self._direction_service.freeze_direction(event.sheet_id, event.timestamp)
        elif event.event_type == "stop":
            state = self._direction_service.get_direction(event.sheet_id)
        else:
            state = self._direction_service.get_direction(event.sheet_id)

        if match_id is not None:
            self._sync_runtime_direction(match_id, event.sheet_id, state)
        return state

    def process_position(self, position: StonePosition, match_id: str | None = None) -> DirectionState:
        """消费定位数据，只用于更新方向判断。"""

        state = self._direction_service.update_position(position)
        if match_id is not None:
            self._sync_runtime_direction(match_id, position.sheet_id, state)
        return state

    def reset_sheet(self, sheet_id: str, match_id: str | None = None) -> DirectionState:
        """手动重置赛道方向状态。"""

        state = self._direction_service.reset(sheet_id)
        if match_id is not None:
            self._sync_runtime_direction(match_id, sheet_id, state)
        return state

    def _sync_runtime_direction(self, match_id: str, sheet_id: str, state: DirectionState) -> None:
        """把方向摘要同步到 SheetRuntime。"""

        try:
            sheet = runtime_manager.get_match(match_id).sheets.get(sheet_id)
        except KeyError:
            return
        if sheet is None:
            return
        self.apply_direction_to_sheet(sheet, state)

    def apply_direction_to_sheet(self, sheet: SheetRuntime, state: DirectionState) -> None:
        """更新 SheetRuntime 中供 DirectorService 读取的方向字段。"""

        sheet.current_direction = state.direction
        sheet.source_end = state.source_end
        sheet.target_end = state.target_end
        sheet.direction_status = state.status
        sheet.direction_confirm_count = state.confirm_count
        sheet.last_position_time = state.last_update_time
