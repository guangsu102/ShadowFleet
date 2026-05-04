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
    """Create fleet_ready_callbacks table if it does not exist (for existing databases)."""
    conn = sqlite3.connect(db_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fleet_ready_callbacks'"
        ).fetchone()
        if tables:
            print("fleet_ready_callbacks table already exists.")
            return

        print("Creating fleet_ready_callbacks table ...")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS fleet_ready_callbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL UNIQUE,
                xboard_node_id INTEGER NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                callback_token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK (status IN ({READY_CALLBACK_STATUS_LIST})),
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                received_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (task_id) REFERENCES fleet_provisioning_tasks(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fleet_ready_callbacks_token_status ON fleet_ready_callbacks (callback_token, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fleet_ready_callbacks_task_status ON fleet_ready_callbacks (task_id, status)"
        )
        conn.commit()
        print("fleet_ready_callbacks table created.")
    finally:
        conn.close()


def insert_test_callback(db_path: str) -> str | None:
    """Insert a dummy pending callback record and return its token. Returns None if task_id 1 does not exist."""
    conn = sqlite3.connect(db_path)
    try:
        exists = conn.execute(
            "SELECT id FROM fleet_provisioning_tasks WHERE id = 1"
        ).fetchone()
        if not exists:
            print("fleet_provisioning_tasks table empty or task_id=1 missing, skipping auto-insert.")
            return None

        import secrets
        token = secrets.token_urlsafe(24)
        now = "datetime('now')"
        conn.execute(f"""
            INSERT INTO fleet_ready_callbacks
                (task_id, xboard_node_id, correlation_id, callback_token, status, created_at, updated_at)
            VALUES
                (1, 1, 'python-test-correlation', ?, 'pending', {now}, {now})
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
