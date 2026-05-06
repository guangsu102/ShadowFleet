#!/usr/bin/env python3
"""Minimal debug: isolate the psycopg2 IndexError."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))


def load_config(config_path: str | None = None) -> dict:
    if config_path is None:
        config_path = "config.yaml"
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_minimal_update(connection_kwargs: dict) -> None:
    """Step by step: which exact call fails."""
    from psycopg2.pool import ThreadedConnectionPool

    pool = ThreadedConnectionPool(1, 10, **connection_kwargs)
    conn = pool.getconn()
    cur = conn.cursor()

    # Step 1: Get a node id
    cur.execute("SELECT id FROM public.v2_server WHERE name LIKE 'sf-%' LIMIT 1")
    row = cur.fetchone()
    node_id = row[0]
    print(f"Got node_id={node_id}, type={type(node_id)}")
    print(f"  cur.description: {cur.description}")
    print(f"  cur._result: {cur._result}")
    print(f"  cur._prefetch: {cur._prefetch}")

    # Step 2: Check if updated_at column exists
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'v2_server' AND column_name = 'updated_at'"
    )
    col_row = cur.fetchone()
    print(f"updated_at column info: {col_row}")

    # Step 3: Try UPDATE with ONLY host (no updated_at)
    sql1 = "UPDATE public.v2_server SET host = %s WHERE id = %s AND name LIKE 'sf-%'"
    params1 = ("test-host-only", node_id)
    print(f"\nTest A: UPDATE without updated_at")
    print(f"  SQL placeholders: 2")
    print(f"  Params: {params1}")
    print(f"  Params len: {len(params1)}")
    cur.execute(sql1, params1)
    print(f"  rowcount: {cur.rowcount}")
    conn.commit()

    # Step 4: Try UPDATE with updated_at = literal string
    sql2 = "UPDATE public.v2_server SET host = %s, updated_at = '2026-01-01 00:00:00' WHERE id = %s AND name LIKE 'sf-%'"
    params2 = ("test-literal-date", node_id)
    print(f"\nTest B: UPDATE with literal date")
    print(f"  SQL placeholders: 2")
    print(f"  Params: {params2}")
    cur.execute(sql2, params2)
    print(f"  rowcount: {cur.rowcount}")
    conn.commit()

    # Step 5: Try UPDATE with updated_at = string placeholder
    sql3 = "UPDATE public.v2_server SET host = %s, updated_at = %s WHERE id = %s AND name LIKE 'sf-%'"
    utcnow = datetime.utcnow()
    params3 = ("test-string-date", utcnow, node_id)
    print(f"\nTest C: UPDATE with datetime as 2nd param")
    print(f"  SQL placeholders: 3")
    print(f"  Params: {params3}")
    print(f"  Params len: {len(params3)}")
    cur.execute(sql3, params3)
    print(f"  rowcount: {cur.rowcount}")
    conn.commit()

    # Step 6: Try UPDATE with datetime as 1st param
    params4 = (utcnow, "test-datetime-first", node_id)
    sql4 = "UPDATE public.v2_server SET updated_at = %s, host = %s WHERE id = %s AND name LIKE 'sf-%'"
    print(f"\nTest D: UPDATE with datetime as 1st param")
    print(f"  SQL placeholders: 3")
    print(f"  Params: {params4}")
    print(f"  Params len: {len(params4)}")
    cur.execute(sql4, params4)
    print(f"  rowcount: {cur.rowcount}")
    conn.commit()

    # Step 7: Try with dict params
    params5 = {"host": "test-dict", "ts": utcnow, "id": node_id}
    sql5 = "UPDATE public.v2_server SET host = %(host)s, updated_at = %(ts)s WHERE id = %(id)s AND name LIKE 'sf-%'"
    print(f"\nTest E: UPDATE with dict params (named)")
    print(f"  Params: {params5}")
    cur.execute(sql5, params5)
    print(f"  rowcount: {cur.rowcount}")
    conn.commit()

    cur.close()
    pool.putconn(conn)
    pool.closeall()
    print("\nAll tests passed!")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    xboard = config.get("xboard")
    if xboard is None:
        print("ERROR: config.yaml must contain an 'xboard' section")
        sys.exit(1)

    print(f"Connecting to {xboard['host']}:{xboard['port']}/{xboard['database']}")
    print(f"psycopg2 version info:")
    import psycopg2
    print(f"  __version__ = {psycopg2.__version__}")

    connection_kwargs = {
        "host": xboard["host"],
        "port": xboard["port"],
        "database": xboard["database"],
        "user": xboard["user"],
        "password": xboard.get("password"),
        "sslmode": xboard.get("sslmode", "prefer"),
        "connect_timeout": 10,
    }

    test_minimal_update(connection_kwargs)


if __name__ == "__main__":
    main()
