"""投壶 Throw State Machine。

状态机只消费 TriggerEvent，不从 Position 推断事件；Position 的唯一职责是在 departure
同步点提供 DirectionService 已冻结的方向摘要。
"""

from __future__ import annotations

import logging

from app.core.enums import ShotQualityStatus, ThrowStatus
from app.models.event import TriggerEvent
from app.models.shot import Shot, ShotEventContext
from app.services.direction_service import DirectionState

logger = logging.getLogger(__name__)


class ThrowStateMachine:
    """按 match_id + sheet_id 隔离的 Shot 状态机。"""

    def __init__(self) -> None:
        self._current_shots: dict[tuple[str, str], Shot] = {}
        self._sequences: dict[tuple[str, str], int] = {}
        self._finished_shots: dict[str, Shot] = {}

    def handle_trigger(
        self,
        match_id: str,
        event: TriggerEvent,
        direction_state: DirectionState | None = None,
    ) -> ShotEventContext | None:
        """处理 TriggerEvent，返回 ShotEventContext；无当前 Shot 的无效事件返回 None。"""

        key = (match_id, event.sheet_id)
        old_state = self._current_shots[key].status if key in self._current_shots else None
        if event.event_type == "touch":
            shot = self._touch(match_id, event)
        elif event.event_type == "departure":
            shot = self._departure(match_id, event, direction_state)
        elif event.event_type == "magnetic_1":
            shot = self._magnetic_1(match_id, event)
        elif event.event_type == "alarm":
            shot = self._alarm(match_id, event)
        elif event.event_type == "magnetic_2":
            shot = self._magnetic_2(match_id, event)
        elif event.event_type == "stop":
            shot = self._stop(match_id, event)
        else:
            shot = None

        if shot is None:
            logger.warning(
                "shot event ignored match_id=%s sheet_id=%s event_type=%s",
                match_id,
                event.sheet_id,
                event.event_type,
            )
            return None

        logger.info(
            "shot transition match_id=%s sheet_id=%s shot_id=%s event_type=%s old_state=%s new_state=%s direction=%s quality_status=%s",
            match_id,
            event.sheet_id,
            shot.shot_id,
            event.event_type,
            old_state,
            shot.status,
            shot.direction,
            shot.quality_status,
        )
        return self._context(shot, event)

    def get_current_shot(self, match_id: str, sheet_id: str) -> Shot | None:
        """读取当前进行中的 Shot。"""

        return self._current_shots.get((match_id, sheet_id))

    def get_finished_shot(self, shot_id: str | None) -> Shot | None:
        """读取刚完成的 Shot。"""

        if shot_id is None:
            return None
        return self._finished_shots.get(shot_id)

    def _touch(self, match_id: str, event: TriggerEvent) -> Shot:
        """touch 创建 Shot；重复 touch 保持幂等。"""

        key = (match_id, event.sheet_id)
        current = self._current_shots.get(key)
        if current is not None:
            logger.warning("duplicate touch ignored match_id=%s sheet_id=%s shot_id=%s", match_id, event.sheet_id, current.shot_id)
            return current
        sequence = self._sequences.get(key, 0) + 1
        self._sequences[key] = sequence
        shot = Shot(
            shot_id=f"{match_id}_{event.sheet_id}_shot_{sequence:04d}",
            match_id=match_id,
            sheet_id=event.sheet_id,
            touch_time=event.timestamp,
            status=ThrowStatus.TOUCHED.value,
        )
        self._current_shots[key] = shot
        return shot

    def _departure(self, match_id: str, event: TriggerEvent, direction_state: DirectionState | None) -> Shot:
        """departure 记录离手时间并冻结方向；真实 type=4 协议没有 touch 时也可直接创建 Shot。"""

        key = (match_id, event.sheet_id)
        shot = self._current_shots.get(key)
        if shot is None:
            sequence = self._sequences.get(key, 0) + 1
            self._sequences[key] = sequence
            shot = Shot(
                shot_id=f"{match_id}_{event.sheet_id}_shot_{sequence:04d}",
                match_id=match_id,
                sheet_id=event.sheet_id,
            )
            self._current_shots[key] = shot
        if shot.departure_time is not None:
            logger.warning("duplicate departure ignored match_id=%s sheet_id=%s shot_id=%s", match_id, event.sheet_id, shot.shot_id)
            return shot
        shot.departure_time = event.timestamp
        shot.status = ThrowStatus.RELEASED.value
        if direction_state is not None:
            shot.direction = direction_state.direction
            shot.source_end = direction_state.source_end
            shot.target_end = direction_state.target_end
        return shot

    def _magnetic_1(self, match_id: str, event: TriggerEvent) -> Shot | None:
        """记录第一磁钉；重复事件不覆盖首次时间。"""

        shot = self._current_shots.get((match_id, event.sheet_id))
        if shot is None:
            return None
        if shot.first_magnetic_time is not None:
            logger.warning("duplicate magnetic_1 ignored match_id=%s sheet_id=%s shot_id=%s", match_id, event.sheet_id, shot.shot_id)
            return shot
        shot.first_magnetic_time = event.timestamp
        if shot.departure_time is None:
            shot.quality_status = ShotQualityStatus.ABNORMAL.value
            shot.abnormal_reason = "magnetic_1_before_departure"
        shot.status = ThrowStatus.PASSED_MAGNETIC_1.value
        return shot

    def _alarm(self, match_id: str, event: TriggerEvent) -> Shot | None:
        """alarm 只记录时间，不改变主状态。"""

        shot = self._current_shots.get((match_id, event.sheet_id))
        if shot is None:
            return None
        if shot.alarm_time is None:
            shot.alarm_time = event.timestamp
        else:
            logger.warning("duplicate alarm ignored match_id=%s sheet_id=%s shot_id=%s", match_id, event.sheet_id, shot.shot_id)
        return shot

    def _magnetic_2(self, match_id: str, event: TriggerEvent) -> Shot | None:
        """记录第二磁钉；缺第一磁钉时标记 abnormal。"""

        shot = self._current_shots.get((match_id, event.sheet_id))
        if shot is None:
            return None
        if shot.second_magnetic_time is not None:
            logger.warning("duplicate magnetic_2 ignored match_id=%s sheet_id=%s shot_id=%s", match_id, event.sheet_id, shot.shot_id)
            return shot
        shot.second_magnetic_time = event.timestamp
        if shot.first_magnetic_time is None:
            shot.quality_status = ShotQualityStatus.ABNORMAL.value
            shot.abnormal_reason = "magnetic_2_before_magnetic_1"
        shot.status = ThrowStatus.PASSED_MAGNETIC_2.value
        return shot

    def _stop(self, match_id: str, event: TriggerEvent) -> Shot | None:
        """stop 完成 Shot，并从 current_shot 移入完成缓存。"""

        key = (match_id, event.sheet_id)
        shot = self._current_shots.get(key)
        if shot is None:
            return None
        if shot.stop_time is None:
            shot.stop_time = event.timestamp
        shot.status = ThrowStatus.FINISHED.value
        shot.quality_status = self._quality(shot)
        self._finished_shots[shot.shot_id] = shot
        self._current_shots.pop(key, None)
        return shot

    def _quality(self, shot: Shot) -> str:
        """计算 Shot 数据质量，alarm 不参与 complete 判定。"""

        if shot.quality_status == ShotQualityStatus.ABNORMAL.value:
            return ShotQualityStatus.ABNORMAL.value
        # 真实冰壶 type=4 协议没有 touch；完整 Shot 只要求业务状态事件齐全。
        required = [
            shot.departure_time,
            shot.first_magnetic_time,
            shot.second_magnetic_time,
            shot.stop_time,
        ]
        if all(value is not None for value in required):
            return ShotQualityStatus.COMPLETE.value
        return ShotQualityStatus.INCOMPLETE.value

    def _context(self, shot: Shot, event: TriggerEvent) -> ShotEventContext:
        """生成后续 DirectorService 可直接消费的上下文。"""

        return ShotEventContext(
            match_id=shot.match_id,
            sheet_id=shot.sheet_id,
            shot_id=shot.shot_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            shot_status=shot.status,
            direction=shot.direction,
            source_end=shot.source_end,
            target_end=shot.target_end,
            quality_status=shot.quality_status,
        )
