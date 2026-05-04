#!/usr/bin/env python3
"""
Query a pending callback token from shadowfleet.db and send it to the local ready endpoint.
"""
import json
import sqlite3
import sys
import urllib.request
import urllib.error

DB_PATH = "shadowfleet.db"
ENDPOINT = "http://localhost:8787/api/v1/provisioning/ready"

READY_CALLBACK_STATUS_LIST = "'pending', 'received', 'completed'"


def ensure_schema(db_path: str) -> None:
    """Initialize the full ShadowFleet schema using the shared builder."""
    conn = sqlite3.connect(db_path)
    try:
        from database.sqlite_connection import SqliteConnectionManager

        script = SqliteConnectionManager._build_schema_script()
        for stmt in script.split(";"):
            trimmed = stmt.strip()
            if trimmed:
                try:
                    conn.executescript(trimmed)
                except sqlite3.OperationalError:
                    pass
        conn.commit()
        print("Schema initialized (tables created if absent).")
    except ImportError:
        print("Warning: could not import SqliteConnectionManager, falling back to local schema.")
        _ensure_local_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_local_schema(conn: sqlite3.Connection) -> None:
    """Minimal fallback schema for environments where sqlite_connection.py is not importable."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fleet_provisioning_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL CHECK (task_type IN ('provision_node')),
            status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed')),
            correlation_id TEXT NOT NULL,
            request_payload_json TEXT NOT NULL,
            result_payload_json TEXT,
            last_error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            locked_by TEXT,
            locked_at TEXT,
            next_run_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_fleet_provisioning_tasks_status_next_run_at
            ON fleet_provisioning_tasks (status, next_run_at);
        CREATE INDEX IF NOT EXISTS idx_fleet_provisioning_tasks_correlation_id
            ON fleet_provisioning_tasks (correlation_id);
        CREATE INDEX IF NOT EXISTS idx_fleet_provisioning_tasks_created_at
            ON fleet_provisioning_tasks (created_at);

        CREATE TABLE IF NOT EXISTS fleet_ready_callbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL UNIQUE,
            xboard_node_id INTEGER NOT NULL UNIQUE,
            correlation_id TEXT NOT NULL,
            callback_token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ('pending', 'received', 'completed')),
            payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            received_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (task_id) REFERENCES fleet_provisioning_tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fleet_ready_callbacks_token_status
            ON fleet_ready_callbacks (callback_token, status);
        CREATE INDEX IF NOT EXISTS idx_fleet_ready_callbacks_task_status
            ON fleet_ready_callbacks (task_id, status);
    """)


def insert_test_callback(db_path: str) -> str | None:
    """Insert a dummy pending callback record and return its token.
    Creates a placeholder provisioning task if none exists so the FK constraint is satisfied."""
    conn = sqlite3.connect(db_path)
    try:
        now_expr = "datetime('now')"
        row = conn.execute("SELECT id FROM fleet_provisioning_tasks WHERE id = 1").fetchone()
        if not row:
            conn.execute(f"""
                INSERT INTO fleet_provisioning_tasks
                    (task_type, status, correlation_id, request_payload_json,
                     attempt_count, max_attempts, next_run_at, created_at, updated_at)
                VALUES
                    ('provision_node', 'running', 'python-test-callback-corr', '{{}}',
                     0, 1, {now_expr}, {now_expr}, {now_expr})
            """)
            conn.commit()
            row = conn.execute("SELECT id FROM fleet_provisioning_tasks WHERE id = 1").fetchone()
            if not row:
                print("Failed to create a placeholder provisioning task.")
                return None

        import secrets
        token = secrets.token_urlsafe(24)
        conn.execute(f"""
            INSERT INTO fleet_ready_callbacks
                (task_id, xboard_node_id, correlation_id, callback_token, status, created_at, updated_at)
            VALUES
                (1, 1, 'python-test-correlation', ?, 'pending', {now_expr}, {now_expr})
        """, (token,))
        conn.commit()
        print(f"Inserted test callback record with task_id=1, token={token}")
        return token
    finally:
        conn.close()


def get_pending_token(db_path: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT callback_token, xboard_node_id, task_id, status FROM fleet_ready_callbacks WHERE status = 'pending' LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def send_ready_callback(token: str, xboard_node_id: int | None = None) -> dict:
    payload = {
        "token": token,
        "correlation_id": "python-test",
        "service_status": "ready",
    }
    if xboard_node_id is not None:
        payload["xboard_node_id"] = xboard_node_id

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH

    print(f"Connecting to: {db_path}")

    ensure_schema(db_path)
    token = get_pending_token(db_path)

    if not token:
        print("No pending callback token found, inserting a test record ...")
        token = insert_test_callback(db_path)
        if not token:
            sys.exit(1)
        print(f"Inserted token: {token}")

    print(f"Found token: {token}")
    print(f"Sending ready callback to {ENDPOINT} ...")

    try:
        result = send_ready_callback(token)
        print(f"Success: {json.dumps(result, indent=2)}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        print(f"HTTP error {exc.code}: {body}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Connection error: {exc.reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
