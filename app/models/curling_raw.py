"""真实冰壶 WebSocket 原始消息模型。

Phase 7.0 只解析外部协议原文，不把 stoneState/hogline 转成内部 TriggerEvent 或 Position。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RawTrajectoryPoint(BaseModel):
    """type=3 中 trajectoryData 的单个轨迹点。"""

    model_config = ConfigDict(extra="allow")

    lane_id: str | None = Field(default=None, alias="laneId")
    tag_id: str | None = Field(default=None, alias="tagId")
    time: int | float | str | None = None
    x: float | int | None = None
    y: float | int | None = None


class BaseRawCurlingMessage(BaseModel):
    """所有冰壶原始消息的公共字段。"""

    model_config = ConfigDict(extra="allow")

    type: int
    raw: dict[str, Any] = Field(default_factory=dict)


class MatchStartRawMessage(BaseRawCurlingMessage):
    """type=1 原始消息；Phase 7.0 只解析保存，不启动 Match。"""

    type: Literal[1]
    lane_id: str | None = Field(default=None, alias="laneId")


class MatchStopRawMessage(BaseRawCurlingMessage):
    """type=2 原始消息；Phase 7.0 只解析保存，不停止 Match。"""

    type: Literal[2]
    lane_id: str | None = Field(default=None, alias="laneId")


class TrajectoryRawMessage(BaseRawCurlingMessage):
    """type=3 轨迹原始消息，只保留 laneId 和 trajectoryData。"""

    type: Literal[3]
    lane_id: str | None = Field(default=None, alias="laneId")
    trajectory_data: list[RawTrajectoryPoint] = Field(default_factory=list, alias="trajectoryData")


class StoneStateRawMessage(BaseRawCurlingMessage):
    """type=4 石头状态原始消息；不做 stoneState 到内部事件的业务映射。"""

    type: Literal[4]
    lane_id: str | None = Field(default=None, alias="laneId")
    moving_stone_tag_id: str | None = Field(default=None, alias="movingStoneTagId")
    stone_state: str | None = Field(default=None, alias="stoneState")
    hog_line_1_timing: int | float | str | None = Field(default=None, alias="hogLine1Timing")
    hog_line_2_timing: int | float | str | None = Field(default=None, alias="hogLine2Timing")
    total_timing: int | float | str | None = Field(default=None, alias="totalTiming")


class HeartbeatRawMessage(BaseRawCurlingMessage):
    """type=12 原始消息，通常用于连接心跳或状态通知。"""

    type: Literal[12]


class GenericRawMessage(BaseRawCurlingMessage):
    """未知 type 原始消息；不得导致 WebSocket 连接退出。"""

    type: int


class MalformedRawMessage(BaseModel):
    """无法解析 JSON 或结构明显错误的消息。"""

    error: str
    raw_text: str


RawCurlingMessage = (
    MatchStartRawMessage
    | MatchStopRawMessage
    | TrajectoryRawMessage
    | StoneStateRawMessage
    | HeartbeatRawMessage
    | GenericRawMessage
    | MalformedRawMessage
)


def parse_raw_curling_message(raw_text: str) -> RawCurlingMessage:
    """把 WebSocket 文本解析为 RawCurlingMessage；错误消息以模型返回，不抛到业务层。"""

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return MalformedRawMessage(error=f"malformed_json: {exc.msg}", raw_text=raw_text)
    if not isinstance(payload, dict):
        return MalformedRawMessage(error="message_must_be_object", raw_text=raw_text)
    message_type = payload.get("type")
    base_payload = {**payload, "raw": payload}
    try:
        if message_type == 1:
            return MatchStartRawMessage.model_validate(base_payload)
        if message_type == 2:
            return MatchStopRawMessage.model_validate(base_payload)
        if message_type == 3:
            return TrajectoryRawMessage.model_validate(base_payload)
        if message_type == 4:
            return StoneStateRawMessage.model_validate(base_payload)
        if message_type == 12:
            return HeartbeatRawMessage.model_validate(base_payload)
        if isinstance(message_type, int):
            return GenericRawMessage.model_validate(base_payload)
        return MalformedRawMessage(error="type_is_required", raw_text=raw_text)
    except Exception as exc:  # noqa: BLE001 - Phase 7.0 传输层需要把坏消息收敛为可观测模型。
        return MalformedRawMessage(error=f"invalid_message: {exc}", raw_text=raw_text)
