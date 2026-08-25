"""智能导播决策模型。

Phase 6 只产生算法内部 DirectorDecision，不修改对软件方暴露的实时输出接口。
"""

from typing import Literal

from pydantic import BaseModel


class PreShotDirectorContext(BaseModel):
    """投壶正式开始前的导演事件上下文。

    direction_locked 发生在 Shot 生命周期之前，只用于提前把镜头切到目标端近景；
    因此这里不携带 shot_id，也不伪造 Shot。
    """

    match_id: str
    sheet_id: str
    event_type: Literal["direction_locked"]
    timestamp: int
    direction: str
    source_end: str
    target_end: str
    candidate_tag_id: str | None = None


class DirectorDecision(BaseModel):
    """一次导演事件对应的确定性导播决策。"""

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
    # 只声明建议保持时长，不在 DirectorService 内 sleep 或启动定时器。
    hold_duration_ms: int = 0
