"""Shot SQLite 仓储。

运行中的 Shot 保存在 Runtime/状态机内存中；FINISHED 后通过本仓储写入 SQLite。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import get_settings
from app.models.shot import Shot
from app.storage.database import init_db


class ShotRepository:
    """负责 Shot 的持久化读写。"""

    def __init__(self, sqlite_path: str | None = None) -> None:
        self._sqlite_path = sqlite_path or get_settings().sqlite_path
        init_db(self._sqlite_path)

    def save(self, shot: Shot) -> None:
        """保存完成 Shot；重复保存同一个 shot_id 时覆盖同一条记录。"""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO shots (
                    shot_id, match_id, sheet_id, touch_time, departure_time,
                    first_magnetic_time, alarm_time, second_magnetic_time, stop_time,
                    direction, source_end, target_end, status, quality_status,
                    player_id, team_id, clip_id, recognition_status, abnormal_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shot.shot_id,
                    shot.match_id,
                    shot.sheet_id,
                    shot.touch_time,
                    shot.departure_time,
                    shot.first_magnetic_time,
                    shot.alarm_time,
                    shot.second_magnetic_time,
                    shot.stop_time,
                    shot.direction,
                    shot.source_end,
                    shot.target_end,
                    shot.status,
                    shot.quality_status,
                    shot.player_id,
                    shot.team_id,
                    shot.clip_id,
                    shot.recognition_status,
                    shot.abnormal_reason,
                ),
            )
            conn.commit()

    def get(self, shot_id: str) -> Shot | None:
        """按 shot_id 查询 Shot。"""

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM shots WHERE shot_id = ?", (shot_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_shot(row)

    def list_by_match(self, match_id: str) -> list[Shot]:
        """按 match_id 查询 Shot 历史。"""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shots WHERE match_id = ? ORDER BY stop_time, shot_id",
                (match_id,),
            ).fetchall()
        return [self._row_to_shot(row) for row in rows]

    def count_by_shot_id(self, shot_id: str) -> int:
        """测试使用：确认 SQLite 中没有重复 Shot。"""

        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM shots WHERE shot_id = ?", (shot_id,)).fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接，并确保目录存在。"""

        db_path = Path(self._sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_shot(self, row: sqlite3.Row) -> Shot:
        """把 SQLite 行转换为 Shot 模型。"""

        fields = Shot.model_fields.keys()
        return Shot.model_validate({field: row[field] for field in fields if field in row.keys()})
