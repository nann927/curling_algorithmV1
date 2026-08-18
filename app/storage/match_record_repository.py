"""历史导播记录 SQLite 仓储。

该仓储只保存算法服务器实际执行过的直播记录，不替代软件方完整赛事数据库。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.enums import EditStatus
from app.storage.database import init_db


class MatchRecordRepository:
    """负责 match_records 表的最小读写。"""

    def __init__(self, sqlite_path: str | None = None) -> None:
        self._sqlite_path = sqlite_path or get_settings().sqlite_path
        init_db(self._sqlite_path)

    def upsert_started(
        self,
        *,
        match_id: str,
        match_name: str,
        description: str,
        sheet_id: str,
        scene_type: str,
        start_time: str,
        media_url: str | None,
        teams: list[dict[str, Any]] | None = None,
        players: list[dict[str, Any]] | None = None,
    ) -> None:
        """start 时保存 recording 记录，并持久化剪辑所需的比赛元数据和人员上下文。"""

        teams_json = json.dumps(teams or [], ensure_ascii=False)
        players_json = json.dumps(players or [], ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO match_records (
                    match_id, match_name, description, sheet_id, scene_type, start_time,
                    record_status, edit_status, media_url, teams_json, players_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'recording', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    match_id,
                    match_name,
                    description,
                    sheet_id,
                    scene_type,
                    start_time,
                    EditStatus.NOT_STARTED.value,
                    media_url,
                    teams_json,
                    players_json,
                ),
            )
            conn.commit()

    def mark_stopped(self, *, match_id: str, end_time: str, record_url: str | None) -> None:
        """stop 时标记录像完成并保持 edit_status=not_started。"""

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE match_records
                SET end_time = ?, record_status = 'completed', edit_status = ?, record_url = ?, updated_at = CURRENT_TIMESTAMP
                WHERE match_id = ?
                """,
                (end_time, EditStatus.NOT_STARTED.value, record_url, match_id),
            )
            conn.commit()

    def update_metadata(
        self,
        *,
        match_id: str,
        match_name: str,
        description: str,
        teams: list[dict[str, Any]] | None = None,
        players: list[dict[str, Any]] | None = None,
    ) -> None:
        """update_config 时同步保存名称、说明和人员上下文，保证重启后 history/edit 可恢复。"""

        teams_json = json.dumps(teams or [], ensure_ascii=False)
        players_json = json.dumps(players or [], ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE match_records
                SET match_name = ?, description = ?, teams_json = ?, players_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE match_id = ?
                """,
                (match_name, description, teams_json, players_json, match_id),
            )
            conn.commit()

    def update_edit_status(self, match_id: str, edit_status: str) -> None:
        """更新剪辑状态。"""

        with self._connect() as conn:
            conn.execute(
                "UPDATE match_records SET edit_status = ?, updated_at = CURRENT_TIMESTAMP WHERE match_id = ?",
                (edit_status, match_id),
            )
            conn.commit()

    def get(self, match_id: str) -> dict | None:
        """按 match_id 查询历史记录。"""

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM match_records WHERE match_id = ?", (match_id,)).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        """按创建时间倒序返回历史导播记录。"""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM match_records ORDER BY COALESCE(end_time, start_time) DESC, created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接。"""

        db_path = Path(self._sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
