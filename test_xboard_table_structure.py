#!/usr/bin/env python3
"""Query Xboard v2_server table structure and sample data."""

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
    print("Querying Xboard v2_server Table Structure")
    print("=" * 70)

    config = load_config()
    xboard_config = config.get("xboard", {})

    conn = psycopg2.connect(
        host=xboard_config.get("host"),
        port=xboard_config.get("port"),
        database=xboard_config.get("database"),
        user=xboard_config.get("user"),
        password=xboard_config.get("password"),
    )

    cursor = conn.cursor()

    # Query table structure
    print("\n[1] Table columns:")
    print("-" * 70)
    cursor.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'v2_server'
        ORDER BY ordinal_position
    """)
    columns = cursor.fetchall()
    for col in columns:
        nullable = "NULL" if col[2] == 'YES' else "NOT NULL"
        default = f" DEFAULT {col[3]}" if col[3] else ""
        print(f"  {col[0]:<30} {col[1]:<20} {nullable}{default}")

    # Query one sample row
    print("\n[2] Sample row data (first ShadowFleet node):")
    print("-" * 70)
    cursor.execute("""
        SELECT * FROM public.v2_server WHERE name LIKE 'sf-%%' ORDER BY id DESC LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        for i, col in enumerate(columns):
            print(f"  {col[0]:<30} = {row[i]}")
    else:
        print("  No ShadowFleet nodes found")

    # Check for any status-related columns
    print("\n[3] Checking for status columns:")
    print("-" * 70)
    status_keywords = ['status', 'online', 'offline', 'enable', 'check', 'alive', 'health']
    for col in columns:
        col_lower = col[0].lower()
        if any(kw in col_lower for kw in status_keywords):
            print(f"  Found: {col[0]}")

    cursor.close()
    conn.close()

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
