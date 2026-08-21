"""智能导播决策模型。

Phase 6 只产生算法内部 DirectorDecision，不修改对软件方暴露的实时输出接口。
"""

from pydantic import BaseModel


class DirectorDecision(BaseModel):
    """一次 Shot 事件对应的确定性导播决策。"""

    match_id: str
    sheet_id: str
    shot_id: str | None = None
    event_type: str
    timestamp: int
    direction: str | None = None
    source_end: str | None = None
    target_end: str | None = None
    camera_id: str | None = None
    camera_role: str | None = None
    install_end: str | None = None
    reason: str
    fallback_used: bool = False
    hold_previous: bool = False
