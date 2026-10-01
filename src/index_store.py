"""SQLite-backed cache/index of decoded workflow executions.

Keyed by (bucket, key, etag) so unchanged S3 objects are never re-fetched or
re-decoded on repeat searches. Lives at ~/.cache/temporal-archive-viewer/index.db
so it persists across app restarts.
"""

import json
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path.home() / ".cache" / "temporal-archive-viewer" / "index.db"
# Guards every access, not just writes: the connection is shared across
# scan_and_index's worker threads (check_same_thread=False), and sqlite3
# connections aren't safe for concurrent use from multiple threads without
# external serialization — an unguarded read could otherwise race a write
# mid-transaction.
_db_lock = threading.Lock()


def _escape_like(value: str) -> str:
    """Escape SQL LIKE metacharacters so user input is matched literally.

    Workflow IDs in this dataset are full of underscores (e.g.
    "aws_jitaccess_TICKET-001") — `_` is a LIKE wildcard for "any one
    character", so searching that literal string would also match
    "awsXjitaccessXTICKET-001" without this.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    bucket TEXT NOT NULL,
    key TEXT NOT NULL,
    etag TEXT,
    size INTEGER,
    last_modified TEXT,
    indexed_at TEXT,
    PRIMARY KEY (bucket, key)
);

CREATE TABLE IF NOT EXISTS workflow_index (
    bucket TEXT NOT NULL,
    key TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    workflow_id TEXT,
    run_id TEXT,
    workflow_type TEXT,
    task_queue TEXT,
    start_time TEXT,
    close_time TEXT,
    status TEXT,
    event_count INTEGER,
    payload_text TEXT,
    history_json TEXT,
    PRIMARY KEY (bucket, key, item_index)
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout=30 makes sqlite retry (rather than immediately error) if it
    # ever finds the db locked, as a defense-in-depth backstop behind _db_lock.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    with _db_lock:
        conn.executescript(_SCHEMA)
        conn.commit()
    return conn


def get_cached_etag(conn: sqlite3.Connection, bucket: str, key: str) -> str | None:
    with _db_lock:
        row = conn.execute(
            "SELECT etag FROM files WHERE bucket = ? AND key = ?", (bucket, key)
        ).fetchone()
    return row[0] if row else None


def upsert_file(conn, bucket: str, key: str, etag: str, size: int, last_modified: str, rows: list[dict]):
    with _db_lock:
        conn.execute("DELETE FROM workflow_index WHERE bucket = ? AND key = ?", (bucket, key))
        conn.execute(
            """INSERT OR REPLACE INTO files (bucket, key, etag, size, last_modified, indexed_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (bucket, key, etag, size, last_modified),
        )
        conn.executemany(
            """INSERT INTO workflow_index
               (bucket, key, item_index, workflow_id, run_id, workflow_type, task_queue,
                start_time, close_time, status, event_count, payload_text, history_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    bucket, key, r["item_index"], r["workflow_id"], r["run_id"], r["workflow_type"],
                    r["task_queue"], r["start_time"], r["close_time"], r["status"], r["event_count"],
                    r["payload_text"], r["history_json"],
                )
                for r in rows
            ],
        )
        conn.commit()


def search(
    conn: sqlite3.Connection,
    bucket: str,
    key_prefix: str = "",
    workflow_id: str = "",
    workflow_type: str = "",
    text: str = "",
    statuses: list[str] | None = None,
) -> list[dict]:
    clauses = ["bucket = ?", "key LIKE ? ESCAPE '\\'"]
    params: list = [bucket, f"{_escape_like(key_prefix)}%"]

    if workflow_id:
        clauses.append("workflow_id LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(workflow_id)}%")
    if workflow_type:
        clauses.append("workflow_type LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(workflow_type)}%")
    if text:
        clauses.append("payload_text LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(text)}%")
    if statuses:
        clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)

    sql = f"""
        SELECT bucket, key, item_index, workflow_id, run_id, workflow_type, task_queue,
               start_time, close_time, status, event_count
        FROM workflow_index
        WHERE {' AND '.join(clauses)}
        ORDER BY start_time DESC
    """
    cols = [
        "bucket", "key", "item_index", "workflow_id", "run_id", "workflow_type", "task_queue",
        "start_time", "close_time", "status", "event_count",
    ]
    with _db_lock:
        return [dict(zip(cols, row)) for row in conn.execute(sql, params).fetchall()]


def get_history_json(conn: sqlite3.Connection, bucket: str, key: str, item_index: int) -> dict | None:
    with _db_lock:
        row = conn.execute(
            "SELECT history_json FROM workflow_index WHERE bucket = ? AND key = ? AND item_index = ?",
            (bucket, key, item_index),
        ).fetchone()
    return json.loads(row[0]) if row else None
