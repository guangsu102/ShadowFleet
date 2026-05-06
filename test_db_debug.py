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


def test_isolated(connection_kwargs: dict) -> None:
    """Test isolated cases - basic building blocks."""
    from psycopg2 import connect

    print("\n=== ISOLATED: Basic tests ===")
    # TEST 0: Raw SQL, no placeholders
    conn = connect(**connection_kwargs)
    cur = conn.cursor()
    cur.execute("SELECT 1 AS test")
    print(f"TEST 0 (raw): {cur.fetchone()}")
    conn.close()

    # TEST 1: 1 placeholder
    conn = connect(**connection_kwargs)
    cur = conn.cursor()
    cur.execute("SELECT %s AS test", (42,))
    print(f"TEST 1 (1 param): {cur.fetchone()}")
    conn.close()

    # TEST 2: 2 placeholders
    conn = connect(**connection_kwargs)
    cur = conn.cursor()
    cur.execute("SELECT %s AS a, %s AS b", (1, 2))
    print(f"TEST 2 (2 params): {cur.fetchone()}")
    conn.close()

    # TEST 3: UPDATE with 1 param
    conn = connect(**connection_kwargs)
    cur = conn.cursor()
    cur.execute("UPDATE public.v2_server SET host = %s WHERE id = 53", ("test-1p",))
    print(f"TEST 3 (UPDATE 1p): rowcount={cur.rowcount}")
    conn.commit()
    conn.close()

    # TEST 4: UPDATE with 2 params
    conn = connect(**connection_kwargs)
    cur = conn.cursor()
    cur.execute("UPDATE public.v2_server SET host = %s WHERE id = %s", ("test-2p", 53))
    print(f"TEST 4 (UPDATE 2p): rowcount={cur.rowcount}")
    conn.commit()
    conn.close()

    # TEST 5: UPDATE with 3 params
    from datetime import timezone as tz
    utcnow = datetime.now(tz.utc)
    conn = connect(**connection_kwargs)
    cur = conn.cursor()
    cur.execute(
        "UPDATE public.v2_server SET host = %s, updated_at = %s WHERE id = %s",
        ("test-3p", utcnow, 53)
    )
    print(f"TEST 5 (UPDATE 3p): rowcount={cur.rowcount}")
    conn.commit()
    conn.close()


def test_same_cursor(connection_kwargs: dict) -> None:
    """Reproduce the exact pattern: SELECT on same cursor, then UPDATE."""
    from psycopg2 import connect

    print("\n=== SAME CURSOR: SELECT then UPDATE on same cursor ===")

    # Pattern A: SELECT id, then UPDATE on SAME cursor
    conn = connect(**connection_kwargs)
    cur = conn.cursor()

    cur.execute("SELECT id, name, host FROM public.v2_server WHERE name LIKE 'sf-%' LIMIT 1")
    row = cur.fetchone()
    node_id = row[0]
    print(f"SELECT: id={node_id}, name={row[1]}, host={row[2]}")
    print(f"cur.description: {cur.description}")

    sql = "UPDATE public.v2_server SET host = %s WHERE id = %s"
    params = (row[2], node_id)
    print(f"UPDATE params: {params}")
    try:
        cur.execute(sql, params)
        print(f"SUCCESS! rowcount={cur.rowcount}")
        conn.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn.close()

    # Pattern B: SELECT, commit, then UPDATE on SAME cursor
    print("\n--- Pattern B: SELECT + commit, then UPDATE on SAME cursor ---")
    conn = connect(**connection_kwargs)
    cur = conn.cursor()

    cur.execute("SELECT id, name, host FROM public.v2_server WHERE name LIKE 'sf-%' LIMIT 1")
    row = cur.fetchone()
    node_id = row[0]
    conn.commit()  # commit after SELECT

    sql = "UPDATE public.v2_server SET host = %s WHERE id = %s"
    params = (row[2], node_id)
    print(f"UPDATE params: {params}")
    try:
        cur.execute(sql, params)
        print(f"SUCCESS! rowcount={cur.rowcount}")
        conn.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn.close()


def test_pool(connection_kwargs: dict) -> None:
    """Reproduce the exact pool pattern from test_db_pool.py."""
    from psycopg2.pool import ThreadedConnectionPool

    print("\n=== POOL: ThreadedConnectionPool ===")

    pool = ThreadedConnectionPool(1, 10, **connection_kwargs)
    conn = pool.getconn()
    cur = conn.cursor()

    # Same pattern as test_db_pool.py
    cur.execute("SELECT id, name, host FROM public.v2_server WHERE name LIKE 'sf-%' LIMIT 1")
    row = cur.fetchone()
    node_id = row[0]
    print(f"SELECT: id={node_id}")

    sql = "UPDATE public.v2_server SET host = %s WHERE id = %s"
    params = (row[2], node_id)
    print(f"UPDATE params: {params}")
    try:
        cur.execute(sql, params)
        print(f"SUCCESS! rowcount={cur.rowcount}")
        conn.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    cur.close()
    pool.putconn(conn)
    pool.closeall()


def test_compare_params_style(connection_kwargs: dict) -> None:
    """Compare list vs tuple params with multi-line SQL (exact test_db_pool.py pattern)."""
    from psycopg2 import connect
    from datetime import timezone

    print("\n=== COMPARE: list vs tuple params with multi-line SQL ===")

    utcnow = datetime.now(tz.utc)

    # SQL exactly like test_db_pool.py (multi-line with triple quotes)
    sql = """
        UPDATE public.v2_server
        SET host = %s, updated_at = %s
        WHERE id = %s AND name LIKE 'sf-%'
    """
    print(f"SQL repr: {repr(sql)}")
    print(f"SQL placeholder count: {sql.count('%s')}")

    # --- Test A: list params (like test_db_pool.py) ---
    conn_a = connect(**connection_kwargs)
    cur_a = conn_a.cursor()
    params_a = ["192.168.1.1-list", utcnow, 53]
    print(f"\nTest A (list params): {params_a}, len={len(params_a)}")
    try:
        cur_a.execute(sql, params_a)
        print(f"SUCCESS! rowcount={cur_a.rowcount}")
        conn_a.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn_a.close()

    # --- Test B: tuple params ---
    conn_b = connect(**connection_kwargs)
    cur_b = conn_b.cursor()
    params_b = ("192.168.1.1-tuple", utcnow, 53)
    print(f"\nTest B (tuple params): {params_b}, len={len(params_b)}")
    try:
        cur_b.execute(sql, params_b)
        print(f"SUCCESS! rowcount={cur_b.rowcount}")
        conn_b.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn_b.close()

    # --- Test C: list from list() cast ---
    conn_c = connect(**connection_kwargs)
    cur_c = conn_c.cursor()
    params_c = list(["192.168.1.1-list-fn", utcnow, 53])
    print(f"\nTest C (list() cast): {params_c}, len={len(params_c)}")
    try:
        cur_c.execute(sql, params_c)
        print(f"SUCCESS! rowcount={cur_c.rowcount}")
        conn_c.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn_c.close()

    # --- Test D: single-line SQL with list ---
    conn_d = connect(**connection_kwargs)
    cur_d = conn_d.cursor()
    sql_d = "UPDATE public.v2_server SET host = %s, updated_at = %s WHERE id = %s AND name LIKE 'sf-%'"
    params_d = ["192.168.1.1-single", utcnow, 53]
    print(f"\nTest D (single-line, list): {params_d}, len={len(params_d)}")
    try:
        cur_d.execute(sql_d, params_d)
        print(f"SUCCESS! rowcount={cur_d.rowcount}")
        conn_d.commit()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    conn_d.close()


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
    import psycopg2
    print(f"psycopg2 version: {psycopg2.__version__}")

    connection_kwargs = {
        "host": xboard["host"],
        "port": xboard["port"],
        "database": xboard["database"],
        "user": xboard["user"],
        "password": xboard.get("password"),
        "sslmode": xboard.get("sslmode", "prefer"),
        "connect_timeout": 10,
    }

    test_isolated(connection_kwargs)
    test_same_cursor(connection_kwargs)
    test_pool(connection_kwargs)
    test_compare_params_style(connection_kwargs)

    print("\nAll tests done!")


if __name__ == "__main__":
    main()
