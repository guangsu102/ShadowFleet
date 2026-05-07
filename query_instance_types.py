#!/usr/bin/env python3
"""查询数据库中的实例规格配置"""

import sqlite3
import sys
from pathlib import Path

def query_instance_types(db_path: str):
    """查询 fleet_assets 和 fleet_asset_protocols 表中的实例规格"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("fleet_assets 表中的 default_instance_type:")
    print("=" * 80)
    cursor.execute("""
        SELECT asset_id, asset_name, region, default_instance_type, default_vcpu, default_architecture
        FROM fleet_assets
        ORDER BY asset_id
    """)
    rows = cursor.fetchall()
    if rows:
        print(f"{'asset_id':<10} {'asset_name':<25} {'region':<10} {'default_instance_type':<20} {'vcpu':<6} {'arch':<8}")
        print("-" * 80)
        for row in rows:
            print(f"{row[0]:<10} {row[1]:<25} {row[2] or 'N/A':<10} {row[3] or 'NULL':<20} {row[4] or 'NULL':<6} {row[5] or 'NULL':<8}")
    else:
        print("No records found")

    print()
    print("=" * 80)
    print("fleet_asset_protocols 表中的 instance_type:")
    print("=" * 80)
    cursor.execute("""
        SELECT asset_id, protocol_type, instance_type, vcpu, architecture, enabled
        FROM fleet_asset_protocols
        ORDER BY asset_id, protocol_type
    """)
    rows = cursor.fetchall()
    if rows:
        print(f"{'asset_id':<10} {'protocol_type':<15} {'instance_type':<20} {'vcpu':<6} {'arch':<8} {'enabled':<8}")
        print("-" * 80)
        for row in rows:
            print(f"{row[0]:<10} {row[1]:<15} {row[2] or 'NULL':<20} {row[3] or 'NULL':<6} {row[4] or 'NULL':<8} {row[5]}")
    else:
        print("No records found")

    conn.close()

if __name__ == "__main__":
    # 默认数据库路径
    default_db = "/data/shadowfleet.db"

    db_path = sys.argv[1] if len(sys.argv) > 1 else default_db

    if not Path(db_path).exists():
        print(f"Error: Database file not found: {db_path}")
        print(f"Usage: python {sys.argv[0]} [db_path]")
        sys.exit(1)

    query_instance_types(db_path)
