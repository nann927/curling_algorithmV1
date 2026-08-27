"""Phase 7.5 Shot 方向协调结果模型。

本模型只描述实时协调结果，不落 SQLite，也不扩展 Shot 表；用于测试、Replay 和后续
WebSocket Consumer 接入时观察 tag 对齐状态。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.models.shot import ShotEventContext
from app.models.stone_state_semantic import StoneStateSemanticEvent


class ShotDirectionAlignmentStatus(StrEnum):
    """candidate tag 与 movingStoneTagId 的对齐结果。"""

    MATCHED = "MATCHED"
    NO_PRE_SHOT_LOCK = "NO_PRE_SHOT_LOCK"
    CANDIDATE_MISMATCH = "CANDIDATE_MISMATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ShotCoordinationResult(BaseModel):
    """一次 State Edge 经方向协调和 Phase 5 派发后的可观察结果。"""

    semantic_event: StoneStateSemanticEvent
    shot_context: ShotEventContext | None = None
    alignment_status: ShotDirectionAlignmentStatus = ShotDirectionAlignmentStatus.NOT_APPLICABLE
    candidate_tag_id: str | None = None
    moving_stone_tag_id: str
    resolved_direction: str = "UNKNOWN"
    resolved_source_end: str | None = None
    resolved_target_end: str | None = None
