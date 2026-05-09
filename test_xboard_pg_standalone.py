#!/usr/bin/env python3
"""Standalone test script for Xboard PostgreSQL node status query.

Run directly with: python3 test_xboard_pg_standalone.py
"""

import sys

try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 is not installed.")
    print("Install it with: pip install psycopg2-binary")
    sys.exit(1)

import yaml


def load_config():
    """Load config from config.yaml."""
    config_path = "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    print("=" * 70)
    print("Testing Xboard PostgreSQL Node Status Query (Standalone)")
    print("=" * 70)

    # Load config
    print("\n[1] Loading config.yaml...")
    try:
        config = load_config()
        print("    ✓ Config loaded successfully")
    except Exception as exc:
        print(f"    ✗ Failed to load config: {exc}")
        return

    # Get Xboard database config
    xboard_config = config.get("xboard", {})
    if not xboard_config:
        print("\n    ✗ Error: 'xboard' not found in config.yaml")
        print("    Please check your config.yaml structure")
        return

    print(f"\n[2] Database config:")
    print(f"    - host: {xboard_config.get('host', 'NOT SET')}")
    print(f"    - port: {xboard_config.get('port', 'NOT SET')}")
    print(f"    - database: {xboard_config.get('database', 'NOT SET')}")
    print(f"    - username: {xboard_config.get('user', 'NOT SET')}")

    # Connect to PostgreSQL
    print("\n[3] Connecting to PostgreSQL...")
    try:
        conn = psycopg2.connect(
            host=xboard_config.get("host"),
            port=xboard_config.get("port"),
            database=xboard_config.get("database"),
            user=xboard_config.get("user"),
            password=xboard_config.get("password"),
        )
        print("    ✓ Connected successfully")
    except Exception as exc:
        print(f"    ✗ Connection failed: {exc}")
        return

    cursor = conn.cursor()

    # Query nodes (ShadowFleet nodes have name prefixed with "sf-")
    print("\n[4] Querying ShadowFleet nodes from public.v2_server...")
    query = """
        SELECT
            id,
            name,
            type,
            host,
            port,
            server_port,
            show
        FROM public.v2_server
        WHERE name LIKE 'sf-%'
        ORDER BY id DESC
        LIMIT 20
    """

    try:
        cursor.execute(query)
        nodes = cursor.fetchall()
        print(f"    ✓ Found {len(nodes)} ShadowFleet nodes (showing top 20)")
    except Exception as exc:
        print(f"    ✗ Query failed: {exc}")
        conn.close()
        return

    # Display results
    print("\n[5] Node Details:")
    print("-" * 80)
    print(f"{'ID':<6} {'Name':<30} {'Type':<12} {'Host':<18} {'Port':<6} {'Status':<8}")
    print("-" * 80)

    for node in nodes:
        node_id, name, node_type, host, port, server_port, show = node
        status = "online" if show else "hidden"
        print(f"{node_id:<6} {name:<30} {node_type:<12} {host:<18} {server_port:<6} {status:<8}")

    print("-" * 70)

    # Test get_node_runtime equivalent
    if nodes:
        print(f"\n[6] Testing get_node_runtime for node_id={nodes[0][0]}...")
        print(f"    ✓ Record found:")
        print(f"    - id: {nodes[0][0]}")
        print(f"    - name: {nodes[0][1]}")
        print(f"    - type: {nodes[0][2]}")
        print(f"    - host: {nodes[0][3]}:{nodes[0][5]}")
        print(f"    - show: {nodes[0][6]} ({'可见' if nodes[0][6] else '隐藏'})")
        print(f"    - xboard_status: {'online' if nodes[0][6] else 'hidden'}")

    cursor.close()
    conn.close()

    print("\n" + "=" * 70)
    print("Test completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
