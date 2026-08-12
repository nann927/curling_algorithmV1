"""电子冰壶 Replay Provider。

Replay 只用于稳定复现 touch→position→departure 时序，不引入消息队列。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.models.event import TriggerEvent
from app.models.stone import StonePosition


ReplayKind = Literal["trigger", "position"]


@dataclass(frozen=True)
class ReplayRecord:
    """一条可回放数据。"""

    kind: ReplayKind
    timestamp: int
    payload: TriggerEvent | StonePosition


class JsonlReplaySource:
    """按 timestamp 顺序回放 JSONL 数据。"""

    def __init__(self, path: str, playback_speed: float = 1.0) -> None:
        self._path = Path(path)
        self._playback_speed = playback_speed
        self._records = self._load_records()
        self._index = 0
        self._running = False
        self._started_at: float | None = None
        self._first_timestamp = self._records[0].timestamp if self._records else 0

    def start(self) -> None:
        """启动回放。"""

        self._running = True
        self._started_at = time.monotonic()

    def stop(self) -> None:
        """停止回放。"""

        self._running = False

    def reset(self) -> None:
        """重置回放游标，保证重复运行结果一致。"""

        self._index = 0
        self._running = False
        self._started_at = None

    def read_next(self) -> ReplayRecord | None:
        """按 playback_speed 读取下一条数据。"""

        if not self._running or self._index >= len(self._records):
            return None
        record = self._records[self._index]
        if self._started_at is not None and self._playback_speed > 0:
            elapsed_ms = (time.monotonic() - self._started_at) * 1000 * self._playback_speed
            if record.timestamp - self._first_timestamp > elapsed_ms:
                return None
        self._index += 1
        return record

    def all_records(self) -> list[ReplayRecord]:
        """直接返回全部记录，用于确定性单元测试。"""

        return list(self._records)

    def _load_records(self) -> list[ReplayRecord]:
        """加载并按 timestamp 排序。"""

        records: list[ReplayRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            kind: ReplayKind = item["kind"]
            if kind == "trigger":
                payload = TriggerEvent.model_validate(item["payload"])
            elif kind == "position":
                payload = StonePosition.model_validate(item["payload"])
            else:
                raise ValueError(f"unsupported replay kind: {kind}")
            records.append(ReplayRecord(kind=kind, timestamp=payload.timestamp, payload=payload))
        return sorted(records, key=lambda record: record.timestamp)
