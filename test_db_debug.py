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
    from psycopg2 import connect
    from psycopg2.pool import ThreadedConnectionPool

    print("\n=== TEST 0: Raw SQL, no placeholders, no params ===")
    conn0 = connect(**connection_kwargs)
    cur0 = conn0.cursor()
    try:
        cur0.execute("SELECT 1 AS test")
        print(f"Raw SQL success: {cur0.fetchone()}")
    except Exception as e:
        print(f"Raw SQL FAILED: {type(e).__name__}: {e}")
    conn0.close()

    print("\n=== TEST 1: SQL with 1 placeholder ===")
    conn1 = connect(**connection_kwargs)
    cur1 = conn1.cursor()
    try:
        cur1.execute("SELECT %s AS test", (42,))
        print(f"1 placeholder success: {cur1.fetchone()}")
    except Exception as e:
        print(f"1 placeholder FAILED: {type(e).__name__}: {e}")
    conn1.close()

    print("\n=== TEST 2: SQL with 2 placeholders ===")
    conn2 = connect(**connection_kwargs)
    cur2 = conn2.cursor()
    try:
        cur2.execute("SELECT %s AS a, %s AS b", (1, 2))
        print(f"2 placeholders success: {cur2.fetchone()}")
    except Exception as e:
        print(f"2 placeholders FAILED: {type(e).__name__}: {e}")
    conn2.close()

    print("\n=== TEST 3: UPDATE with hardcoded id, 1 placeholder ===")
    conn3 = connect(**connection_kwargs)
    cur3 = conn3.cursor()
    try:
        cur3.execute(
            "UPDATE public.v2_server SET host = 'debug-host' WHERE id = 53"
        )
        print(f"Hardcoded UPDATE success, rowcount={cur3.rowcount}")
        conn3.commit()
    except Exception as e:
        print(f"Hardcoded UPDATE FAILED: {type(e).__name__}: {e}")
    conn3.close()

    print("\n=== TEST 4: UPDATE with 1 param ===")
    conn4 = connect(**connection_kwargs)
    cur4 = conn4.cursor()
    try:
        cur4.execute(
            "UPDATE public.v2_server SET host = %s WHERE id = 53",
            ("param-host-1",)
        )
        print(f"1 param UPDATE success, rowcount={cur4.rowcount}")
        conn4.commit()
    except Exception as e:
        print(f"1 param UPDATE FAILED: {type(e).__name__}: {e}")
    conn4.close()

    print("\n=== TEST 5: UPDATE with 2 params (the failing pattern) ===")
    conn5 = connect(**connection_kwargs)
    cur5 = conn5.cursor()
    try:
        cur5.execute(
            "UPDATE public.v2_server SET host = %s WHERE id = %s",
            ("param-host-2", 53)
        )
        print(f"2 param UPDATE success, rowcount={cur5.rowcount}")
        conn5.commit()
    except Exception as e:
        print(f"2 param UPDATE FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn5.close()

    print("\n=== TEST 6: connection.execute() (not cursor) ===")
    conn6 = connect(**connection_kwargs)
    try:
        result = conn6.execute(
            "UPDATE public.v2_server SET host = %s WHERE id = %s",
            ("conn-execute-host", 53)
        )
        print(f"connection.execute success, rowcount={result.rowcount}")
        conn6.commit()
    except Exception as e:
        print(f"connection.execute FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn6.close()

    print("\n=== TEST 7: Pure psycopg2.sql.SQL ===")
    conn7 = connect(**connection_kwargs)
    cur7 = conn7.cursor()
    from psycopg2 import sql
    try:
        query = sql.SQL("UPDATE public.v2_server SET host = {} WHERE id = {}").format(
            sql.Literal("psycopg2-sql-host"),
            sql.Literal(53)
        )
        cur7.execute(query)
        print(f"psycopg2.sql success, rowcount={cur7.rowcount}")
        conn7.commit()
    except Exception as e:
        print(f"psycopg2.sql FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn7.close()

    print("\nDone!")

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
