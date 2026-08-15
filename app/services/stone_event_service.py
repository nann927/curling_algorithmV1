"""电子冰壶触发事件编排服务。

一期投壶事件由 TriggerEvent 驱动；StonePosition 只交给 DirectionService 判断投壶方向。
Phase 5 在此统一编排 TriggerEvent -> ThrowStateMachine -> ShotEventContext。
"""

from __future__ import annotations

from app.core.enums import ThrowStatus
from app.core.runtime import SheetRuntime, runtime_manager
from app.models.event import TriggerEvent
from app.models.shot import Shot, ShotEventContext
from app.models.stone import StonePosition
from app.services.direction_service import DirectionService, DirectionState
from app.services.throw_state_machine import ThrowStateMachine
from app.storage.shot_repository import ShotRepository


class StoneEventService:
    """处理 TriggerEvent 和 StonePosition 的轻量编排层。"""

    def __init__(
        self,
        direction_service: DirectionService | None = None,
        state_machine: ThrowStateMachine | None = None,
        shot_repository: ShotRepository | None = None,
    ) -> None:
        self._direction_service = direction_service or DirectionService()
        self._state_machine = state_machine or ThrowStateMachine()
        self._shot_repository = shot_repository or ShotRepository()

    def process_trigger_event(
        self,
        event: TriggerEvent,
        match_id: str | None = None,
    ) -> DirectionState | ShotEventContext | None:
        """消费触发事件。

        兼容 Phase 4：不传 match_id 时继续返回 DirectionState；传 match_id 时返回 ShotEventContext。
        """

        if match_id is None:
            return self._process_trigger_for_direction_only(event)

        direction_state: DirectionState | None = None
        if event.event_type == "touch":
            direction_state = self._direction_service.start_monitoring(event.sheet_id, match_id=match_id)
        elif event.event_type == "departure":
            direction_state = self._direction_service.freeze_direction(event.sheet_id, event.timestamp, match_id=match_id)

        context = self._state_machine.handle_trigger(match_id, event, direction_state)
        if context is None:
            return None

        current_shot = self._state_machine.get_current_shot(match_id, event.sheet_id)
        finished_shot = self._state_machine.get_finished_shot(context.shot_id)
        self._sync_runtime_shot(match_id, event.sheet_id, current_shot, finished_shot, direction_state)

        if context.shot_status == ThrowStatus.FINISHED.value and finished_shot is not None:
            self._shot_repository.save(finished_shot)
            self._direction_service.reset(event.sheet_id, match_id=match_id)
        return context

    def process_position(self, position: StonePosition, match_id: str | None = None) -> DirectionState:
        """消费定位数据，只用于更新方向判断。"""

        state = self._direction_service.update_position(position, match_id=match_id)
        if match_id is not None:
            self._sync_runtime_direction(match_id, position.sheet_id, state)
        return state

    def reset_sheet(self, sheet_id: str, match_id: str | None = None) -> DirectionState:
        """手动重置赛道方向状态。"""

        state = self._direction_service.reset(sheet_id, match_id=match_id)
        if match_id is not None:
            self._sync_runtime_direction(match_id, sheet_id, state)
        return state

    def get_current_shot(self, match_id: str, sheet_id: str) -> Shot | None:
        """读取当前运行中的 Shot。"""

        return self._state_machine.get_current_shot(match_id, sheet_id)

    def _process_trigger_for_direction_only(self, event: TriggerEvent) -> DirectionState:
        """Phase 4 兼容路径：只推进方向状态，不创建 Shot。"""

        if event.event_type == "touch":
            return self._direction_service.start_monitoring(event.sheet_id)
        if event.event_type == "departure":
            return self._direction_service.freeze_direction(event.sheet_id, event.timestamp)
        if event.event_type == "stop":
            return self._direction_service.get_direction(event.sheet_id)
        return self._direction_service.get_direction(event.sheet_id)

    def _sync_runtime_direction(self, match_id: str, sheet_id: str, state: DirectionState) -> None:
        """把方向摘要同步到 SheetRuntime。"""

        try:
            sheet = runtime_manager.get_match(match_id).sheets.get(sheet_id)
        except KeyError:
            return
        if sheet is None:
            return
        self.apply_direction_to_sheet(sheet, state)

    def _sync_runtime_shot(
        self,
        match_id: str,
        sheet_id: str,
        current_shot: Shot | None,
        finished_shot: Shot | None,
        direction_state: DirectionState | None,
    ) -> None:
        """把 Shot 生命周期同步到 SheetRuntime，供后续 DirectorService 使用。"""

        try:
            sheet = runtime_manager.get_match(match_id).sheets.get(sheet_id)
        except KeyError:
            return
        if sheet is None:
            return
        if direction_state is not None:
            self.apply_direction_to_sheet(sheet, direction_state)
        if current_shot is not None:
            sheet.current_shot = current_shot.model_dump()
            sheet.current_shot_id = current_shot.shot_id
            sheet.current_event = current_shot.status
            return
        if finished_shot is not None:
            sheet.current_shot = None
            sheet.current_shot_id = None
            sheet.current_event = finished_shot.status
            sheet.shot_history.append(finished_shot.shot_id)
            sheet.current_direction = finished_shot.direction
            sheet.source_end = finished_shot.source_end
            sheet.target_end = finished_shot.target_end

    def apply_direction_to_sheet(self, sheet: SheetRuntime, state: DirectionState) -> None:
        """更新 SheetRuntime 中供 DirectorService 读取的方向字段。"""

        sheet.current_direction = state.direction
        sheet.source_end = state.source_end
        sheet.target_end = state.target_end
        sheet.direction_status = state.status
        sheet.direction_confirm_count = state.confirm_count
        sheet.last_position_time = state.last_update_time

