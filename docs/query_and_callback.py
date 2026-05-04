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
    token = get_pending_token(db_path)
    if not token:
        print("No pending callback token found in database.")
        sys.exit(1)

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
