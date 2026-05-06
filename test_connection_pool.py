#!/usr/bin/env python3
"""Test the PostgresConnectionPool class directly with the actual ShadowFleet config.

Usage:
    python test_connection_pool.py [--config CONFIG_YAML]

This simulates exactly how the daemon uses PostgresConnectionPool,
including the cursor() context manager pattern.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from database.connection import PostgresConnectionPool


def load_config(config_path: str | None = None) -> dict:
    if config_path is None:
        config_path = "config.yaml"
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_runtime_context(cfg: dict) -> SimpleNamespace:
    """Build a minimal RuntimeContext mock that PostgresConnectionPool expects."""
    xboard_cfg = cfg.get("xboard", {})
    app_cfg = cfg.get("app", {})

    config = SimpleNamespace(
        xboard=SimpleNamespace(
            host=xboard_cfg.get("host", "localhost"),
            port=xboard_cfg.get("port", 5432),
            database=xboard_cfg.get("database", "xboard"),
            user=xboard_cfg.get("user", "postgres"),
            password=xboard_cfg.get("password"),
            ssl_mode=xboard_cfg.get("sslmode", xboard_cfg.get("ssl_mode", "prefer")),
        ),
        app=SimpleNamespace(
            request_timeout_seconds=app_cfg.get("request_timeout_seconds", 10),
            max_retries=app_cfg.get("max_retries", 3),
            retry_backoff_seconds=app_cfg.get("retry_backoff_seconds", 1.0),
        ),
    )
    root_logger = _MockLogger("")

    return SimpleNamespace(
        config=config,
        logger=root_logger,
        correlation_id="test",
    )


class _MockLogger:
    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    def _log(self, level: str, msg: str, *args):
        print(f"[{level.upper()}] {self._prefix}{msg % args}")

    def getChild(self, name: str):
        return _MockLogger(self._prefix + name + ".")

    def info(self, msg: str, *args):
        self._log("info", msg, *args)

    def warning(self, msg: str, *args):
        self._log("warning", msg, *args)

    def error(self, msg: str, *args):
        self._log("error", msg, *args)

    def exception(self, msg: str, *args):
        self._log("exception", msg, *args)

    def debug(self, msg: str, *args):
        self._log("debug", msg, *args)


def test_pool_initialization(runtime) -> None:
    """Test 1: Pool initializes correctly."""
    print("\n=== Test 1: Pool initialization ===")
    pool = PostgresConnectionPool(runtime)
    print("Pool created successfully")
    pool.close()
    print("Pool closed successfully")
    print("Test 1 PASSED")


def test_simple_query(pool: PostgresConnectionPool) -> None:
    """Test 2: Simple SELECT query."""
    print("\n=== Test 2: Simple SELECT query ===")
    with pool.cursor() as cursor:
        cursor.execute("SELECT 1, 2, 3")
        result = cursor.fetchone()
        print(f"Result: {result}")
        assert result == (1, 2, 3)
    print("Test 2 PASSED")


def test_update_node_host(pool: PostgresConnectionPool) -> None:
    """Test 3: The exact update_node_host pattern that was failing."""
    print("\n=== Test 3: update_node_host pattern ===")

    # Find a node to test
    with pool.cursor() as cursor:
        cursor.execute("SELECT id FROM public.v2_server WHERE name LIKE 'sf-%' LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            print("No sf-* nodes found, creating a test node...")
            cursor.execute(
                """
                INSERT INTO public.v2_server (name, host, port, server_port, rate, type, show)
                VALUES ('sf-test-pool', '1.2.3.4', '7001', 22, 0, 'anytls', true)
                RETURNING id
                """
            )
            node_id = cursor.fetchone()[0]
            print(f"Created test node id={node_id}")
        else:
            node_id = row[0]
            print(f"Found node id={node_id}")

    # Test the exact pattern that was failing
    utcnow = datetime.now(timezone.utc)
    sql = """
        UPDATE public.v2_server
        SET host = %s, updated_at = %s
        WHERE id = %s AND name LIKE 'sf-%'
    """
    params = ("pool-test-" + str(utcnow), utcnow, node_id)

    print(f"Parameters: {params}")
    with pool.cursor() as cursor:
        cursor.execute(sql, params)
        print(f"rowcount: {cursor.rowcount}")
        assert cursor.rowcount == 1, f"Expected rowcount=1, got {cursor.rowcount}"

    # Verify commit persisted
    with pool.cursor() as cursor:
        cursor.execute("SELECT host FROM public.v2_server WHERE id = %s", (node_id,))
        host = cursor.fetchone()[0]
        print(f"Verified host after commit: {host}")
        assert "pool-test-" in host, f"Expected host to contain 'pool-test-', got {host}"

    # Cleanup
    with pool.cursor() as cursor:
        cursor.execute("DELETE FROM public.v2_server WHERE id = %s", (node_id,))

    print("Test 3 PASSED")


def test_concurrent_connections(pool: PostgresConnectionPool) -> None:
    """Test 4: Multiple concurrent operations."""
    print("\n=== Test 4: Concurrent connection pattern ===")

    import threading

    results = []
    errors = []

    def worker(worker_id: int) -> None:
        try:
            with pool.cursor() as cursor:
                cursor.execute("SELECT id FROM public.v2_server LIMIT 1")
                row = cursor.fetchone()
                host = f"worker-{worker_id}"
                if row:
                    cursor.execute(
                        "UPDATE public.v2_server SET host = %s WHERE id = %s",
                        (host, row[0]),
                    )
            results.append((worker_id, "ok"))
        except Exception as e:
            errors.append((worker_id, str(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"Results: {results}")
    print(f"Errors: {errors}")
    assert len(errors) == 0, f"Expected no errors, got {errors}"
    print("Test 4 PASSED")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test PostgresConnectionPool directly")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    if config.get("xboard") is None:
        print("ERROR: config.yaml must contain an 'xboard' section")
        sys.exit(1)

    print(f"Testing against xboard at {config['xboard']['host']}:{config['xboard']['port']}")

    runtime = build_runtime_context(config)
    test_pool_initialization(runtime)
    pool = PostgresConnectionPool(runtime)

    try:
        test_simple_query(pool)
        test_update_node_host(pool)
        test_concurrent_connections(pool)
    finally:
        pool.close()

    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()
