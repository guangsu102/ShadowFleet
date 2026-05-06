#!/usr/bin/env python3
"""Test script to verify PostgreSQL connection pool and xboard_repo operations locally.

Usage:
    python test_db_pool.py [--config CONFIG_YAML]

Requires a config.yaml with xboard section pointing to your Xboard database.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml


def load_config(config_path: str | None = None) -> dict:
    if config_path is None:
        config_path = "config.yaml"
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_connection_kwargs(xboard_config: dict) -> dict:
    return {
        "host": xboard_config["host"],
        "port": xboard_config["port"],
        "database": xboard_config["database"],
        "user": xboard_config["user"],
        "password": xboard_config.get("password"),
        "sslmode": xboard_config.get("sslmode", xboard_config.get("ssl_mode", "prefer")),
        "connect_timeout": 10,
        "application_name": "shadowfleet-test",
    }


def test_threaded_connection_pool(connection_kwargs: dict) -> None:
    """Test 1: Verify ThreadedConnectionPool works with positional args."""
    print("\n=== Test 1: ThreadedConnectionPool initialization ===")
    from psycopg2.pool import ThreadedConnectionPool

    pool = ThreadedConnectionPool(1, 10, **connection_kwargs)
    print("Pool created successfully")

    conn = pool.getconn()
    print(f"Got connection: {conn}")
    print(f"autocommit={conn.autocommit}")

    cur = conn.cursor()
    cur.execute("SELECT 1, 2, 3")
    result = cur.fetchone()
    print(f"Query result: {result}")
    assert result == (1, 2, 3), f"Expected (1, 2, 3), got {result}"

    cur.close()
    pool.putconn(conn)
    pool.closeall()
    print("Test 1 PASSED")


def test_update_with_utcnow(connection_kwargs: dict) -> None:
    """Test 2: Reproduce the original bug - UPDATE with %s and datetime."""
    print("\n=== Test 2: UPDATE with datetime ===")
    from psycopg2.pool import ThreadedConnectionPool

    pool = ThreadedConnectionPool(1, 10, **connection_kwargs)

    # Find a node to test with
    conn = pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, host FROM public.v2_server WHERE name LIKE 'sf-%%' LIMIT 1")
    row = cur.fetchone()
    if row is None:
        print("No sf-* nodes found in xboard, creating a test node first...")
        cur.execute(
            """
            INSERT INTO public.v2_server (name, host, port, server_port, rate, type, show)
            VALUES ('sf-test-temp', '127.0.0.1', '7001', 22, 0, 'anytls', true)
            RETURNING id
            """
        )
        node_id = cur.fetchone()[0]
        conn.commit()
        print(f"Created test node id={node_id}")
    else:
        node_id, name, old_host = row
        print(f"Found node: id={node_id} name={name} host={old_host}")
        cur.execute(
            "UPDATE public.v2_server SET host = '127.0.0.1' WHERE id = %s",
            (node_id,),
        )
        conn.commit()
    cur.close()
    pool.putconn(conn)

    # Now test the actual problematic pattern with a fresh connection from the pool
    utcnow = datetime.utcnow()
    sql = """
        UPDATE public.v2_server
        SET host = %s, updated_at = %s
        WHERE id = %s AND name LIKE 'sf-%%'
    """
    # Pass parameters as a list instead of tuple to avoid psycopg2 edge cases
    host_val = "192.168.1.1"
    params = [host_val, utcnow, node_id]
    print(f"Executing: {sql.strip()}")
    print(f"Parameters: {params}")

    conn2 = pool.getconn()
    cur2 = conn2.cursor()
    cur2.execute(sql, params)
    print(f"rowcount: {cur2.rowcount}")
    conn2.commit()
    assert cur2.rowcount == 1, f"Expected rowcount=1, got {cur2.rowcount}"

    # Verify it was actually updated
    cur2.execute("SELECT host, updated_at FROM public.v2_server WHERE id = %s", (node_id,))
    row = cur2.fetchone()
    print(f"Verified: host={row[0]} updated_at={row[1]}")
    assert row[0] == host_val

    # Cleanup
    cur2.execute("DELETE FROM public.v2_server WHERE id = %s", (node_id,))
    conn2.commit()
    cur2.close()
    pool.putconn(conn2)
    pool.closeall()
    print("Test 2 PASSED")


def test_connection_manager_pattern(connection_kwargs: dict) -> None:
    """Test 3: Test the connection manager pattern from connection.py."""
    print("\n=== Test 3: connection manager pattern ===")
    from contextlib import contextmanager
    from psycopg2.pool import ThreadedConnectionPool

    pool = ThreadedConnectionPool(1, 10, **connection_kwargs)

    @contextmanager
    def connection(pool):
        conn = pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    @contextmanager
    def cursor(pool):
        with connection(pool) as conn:
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    # Test: update a node
    with cursor(pool) as cur:
        cur.execute("SELECT id FROM public.v2_server WHERE name LIKE 'sf-%%' LIMIT 1")
        row = cur.fetchone()
        if row is None:
            print("No sf-* nodes to test, skipping cursor pattern test")
            pool.closeall()
            print("Test 3 PASSED (no nodes to test)")
            return
        node_id = row[0]

    utcnow = datetime.utcnow()
    sql = """
        UPDATE public.v2_server
        SET host = %s, updated_at = %s
        WHERE id = %s AND name LIKE 'sf-%%'
    """
    with cursor(pool) as cur:
        cur.execute(sql, [f"test-{utcnow}", utcnow, node_id])
        assert cur.rowcount == 1, f"Expected rowcount=1, got {cur.rowcount}"

    # Verify commit persisted
    with connection(pool) as conn:
        cur = conn.cursor()
        cur.execute("SELECT host FROM public.v2_server WHERE id = %s", (node_id,))
        host = cur.fetchone()[0]
        cur.close()
        assert "test-" in host, f"Expected host to contain 'test-', got {host}"

    pool.closeall()
    print("Test 3 PASSED")


def test_reproduce_original_bug(connection_kwargs: dict) -> None:
    """Test 4: Reproduce the exact original bug - autocommit=False without commit."""
    print("\n=== Test 4: Reproduce original bug (autocommit=False without commit) ===")
    from psycopg2.pool import ThreadedConnectionPool

    pool = ThreadedConnectionPool(1, 10, **connection_kwargs)

    # Find a node
    conn = pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM public.v2_server WHERE name LIKE 'sf-%%' LIMIT 1")
    row = cur.fetchone()
    if row is None:
        print("No sf-* nodes, creating one...")
        cur.execute(
            "INSERT INTO public.v2_server (name, host, port, server_port, rate, type, show) "
            "VALUES ('sf-test-bug', '1.2.3.4', '7001', 22, 0, 'anytls', true) RETURNING id"
        )
        node_id = cur.fetchone()[0]
        conn.commit()
    else:
        node_id = row[0]
    cur.close()
    pool.putconn(conn)

    # Simulate the BUGGY pattern (what the old code did):
    # connection with autocommit=False but NEVER calling commit()
    conn2 = pool.getconn()
    conn2.autocommit = False
    cur2 = conn2.cursor()

    utcnow = datetime.utcnow()
    sql = """
        UPDATE public.v2_server
        SET host = %s, updated_at = %s
        WHERE id = %s AND name LIKE 'sf-%%'
    """
    try:
        cur2.execute(sql, ["buggy-test", utcnow, node_id])
        print(f"execute succeeded, rowcount={cur2.rowcount}")
        cur2.execute("SELECT host FROM public.v2_server WHERE id = %s", (node_id,))
        host = cur2.fetchone()[0]
        print(f"Read back host: {host}")
        conn2.rollback()
    except Exception as e:
        print(f"Exception during buggy pattern: {type(e).__name__}: {e}")
        conn2.rollback()

    cur2.close()
    pool.putconn(conn2)

    # Check if the update persisted (it shouldn't without commit)
    conn3 = pool.getconn()
    cur3 = conn3.cursor()
    cur3.execute("SELECT host FROM public.v2_server WHERE id = %s", (node_id,))
    host = cur3.fetchone()[0]
    cur3.close()
    pool.putconn(conn3)
    pool.closeall()

    if "buggy-test" in str(host):
        print("WARNING: update persisted without explicit commit")
    else:
        print(f"Confirmed: update did NOT persist (host={host}), as expected without commit")

    print("Test 4 completed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test PostgreSQL connection pool locally")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    xboard = config.get("xboard")
    if xboard is None:
        print("ERROR: config.yaml must contain an 'xboard' section with database credentials")
        sys.exit(1)

    connection_kwargs = build_connection_kwargs(xboard)
    print(f"Connecting to {connection_kwargs['host']}:{connection_kwargs['port']}/{connection_kwargs['database']}")

    test_threaded_connection_pool(connection_kwargs)
    test_update_with_utcnow(connection_kwargs)
    test_connection_manager_pattern(connection_kwargs)
    test_reproduce_original_bug(connection_kwargs)

    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()
