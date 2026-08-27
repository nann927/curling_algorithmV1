"""Phase 7.6 实时协议编排结果模型。

本模型只用于内存中的 Fake E2E、测试和后续真实 Consumer 观察，不持久化、不新增软件 API。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.curling_state_edge import StoneStateEdge
from app.models.director import DirectorDecision, PreShotDirectorContext
from app.models.shot import ShotEventContext
from app.models.shot_coordination import ShotCoordinationResult
from app.models.stone import StonePosition


class RealtimeOrchestrationResult(BaseModel):
    """单条 Raw 消息经过 Orchestrator 后产生的可观察结果。"""

    raw_type: int | None = None
    positions: list[StonePosition] = Field(default_factory=list)
    pre_shot_contexts: list[PreShotDirectorContext] = Field(default_factory=list)
    state_edge: StoneStateEdge | None = None
    coordination_result: ShotCoordinationResult | None = None
    shot_context: ShotEventContext | None = None
    director_decisions: list[DirectorDecision] = Field(default_factory=list)
    ignored_reason: str | None = None
