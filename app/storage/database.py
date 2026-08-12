"""SQLite 初始化骨架。

当前 Phase 0-2 只创建基础表，不把 Runtime 强制落库。
后续恢复运行时或记录媒体结果时，可以在 storage 层继续扩展。
"""

import sqlite3
from pathlib import Path


def init_db(sqlite_path: str) -> None:
    """确保 SQLite 文件和基础表存在。"""

    db_path = Path(sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
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
