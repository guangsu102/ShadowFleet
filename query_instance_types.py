#!/usr/bin/env python3
"""查询数据库中的实例规格配置"""

import sqlite3
import sys
from pathlib import Path

def get_table_schema(cursor, table_name):
    """获取表结构"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [col[1] for col in cursor.fetchall()]

def query_instance_types(db_path: str):
    """查询 fleet_assets 和 fleet_asset_protocols 表中的实例规格"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 获取表结构
    print("fleet_assets 表结构:")
    print(get_table_schema(cursor, "fleet_assets"))

    print("\nfleet_asset_protocols 表结构:")
    print(get_table_schema(cursor, "fleet_asset_protocols"))

    print()
    print("=" * 80)
    print("fleet_assets 表中的 default_instance_type:")
    print("=" * 80)

    columns = get_table_schema(cursor, "fleet_assets")
    cursor.execute("SELECT * FROM fleet_assets LIMIT 1")
    sample = cursor.fetchone()

    select_cols = []
    for i, col in enumerate(columns):
        if col in ['default_instance_type', 'instance_type', 'name', 'asset_name']:
            select_cols.append(col)

    print(f"可用列: {columns}")
    print(f"示例数据: {sample}")

    # 根据实际列名构建查询
    name_col = 'asset_name' if 'asset_name' in columns else 'name' if 'name' in columns else None
    if name_col:
        query = f"SELECT {name_col}, default_instance_type FROM fleet_assets ORDER BY 1"
        print(f"\n执行查询: {query}")
        cursor.execute(query)
        rows = cursor.fetchall()
        for row in rows:
            print(f"  {row[0]}: default_instance_type = {row[1]}")

    print()
    print("=" * 80)
    print("fleet_asset_protocols 表中的 instance_type:")
    print("=" * 80)

    proto_columns = get_table_schema(cursor, "fleet_asset_protocols")
    print(f"可用列: {proto_columns}")

    # 根据实际列名构建查询
    proto_name = 'protocol_type' if 'protocol_type' in proto_columns else 'protocol' if 'protocol' in proto_columns else None
    if proto_name and 'instance_type' in proto_columns:
        query = f"SELECT {proto_name}, instance_type FROM fleet_asset_protocols ORDER BY 1"
        print(f"\n执行查询: {query}")
        cursor.execute(query)
        rows = cursor.fetchall()
        for row in rows:
            print(f"  {row[0]}: instance_type = {row[1]}")

    conn.close()

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/data/shadowfleet.db"

    if not Path(db_path).exists():
        print(f"Error: Database file not found: {db_path}")
        print(f"Usage: python {sys.argv[0]} [db_path]")
        sys.exit(1)

    query_instance_types(db_path)
