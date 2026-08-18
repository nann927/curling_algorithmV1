"""SQLite 初始化骨架。

当前 Phase 0-5 只创建基础表，不把 Runtime 强制落库。
Phase 4.6 新增 match_records，用于服务重启后恢复历史导播记录。
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    """为已有 SQLite 表补齐新增列，避免现场历史库因缺列启动失败。"""

    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}")


def init_db(sqlite_path: str) -> None:
    """确保 SQLite 文件和基础表存在。"""

    db_path = Path(sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY,
                    scene_type TEXT,
                    start_time TEXT,
                    status TEXT,
                    camera_config_json TEXT,
                    teams_json TEXT,
                    players_json TEXT,
                    edit_status TEXT,
                    edit_progress INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT,
                    sheet_id TEXT,
                    result_mode TEXT,
                    result_type TEXT,
                    local_path TEXT,
                    media_url TEXT,
                    upload_status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shots (
                    shot_id TEXT PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    sheet_id TEXT NOT NULL,
                    touch_time INTEGER,
                    departure_time INTEGER,
                    first_magnetic_time INTEGER,
                    alarm_time INTEGER,
                    second_magnetic_time INTEGER,
                    stop_time INTEGER,
                    direction TEXT NOT NULL,
                    source_end TEXT,
                    target_end TEXT,
                    status TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    player_id TEXT,
                    team_id TEXT,
                    clip_id TEXT,
                    recognition_status TEXT,
                    abnormal_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS match_records (
                    match_id TEXT PRIMARY KEY,
                    match_name TEXT,
                    description TEXT,
                    sheet_id TEXT NOT NULL,
                    scene_type TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    record_status TEXT NOT NULL,
                    edit_status TEXT NOT NULL,
                    media_url TEXT,
                    record_url TEXT,
                    teams_json TEXT,
                    players_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            _ensure_columns(
                conn,
                "match_records",
                {
                    "teams_json": "TEXT",
                    "players_json": "TEXT",
                    "match_name": "TEXT DEFAULT ''",
                    "description": "TEXT DEFAULT ''",
                },
            )
    except sqlite3.OperationalError as exc:
        # 某些现场或测试环境可能挂载了只读历史库；API 启动不应因此失败。
        if "readonly" in str(exc).lower() or "read-only" in str(exc).lower():
            logger.warning("sqlite init skipped for readonly database %s: %s", db_path, exc)
            return
        raise
