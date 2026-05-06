#!/usr/bin/env python3
"""检查生产环境重复节点数据"""

import sys
sys.path.insert(0, '.')

from database.sqlite_connection import get_db_path, SqliteConnectionManager
import sqlite3

def check_duplicates():
    db_path = get_db_path()
    print(f"数据库路径: {db_path}\n")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. 检查迁移是否执行
    print("=" * 60)
    print("1. 检查迁移记录")
    print("=" * 60)
    cursor.execute("SELECT * FROM schema_migrations WHERE name LIKE '%duplicate%'")
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            print(f"  {row}")
    else:
        print("  未找到重复节点相关的迁移记录")

    # 2. 统计总数量
    print("\n" + "=" * 60)
    print("2. 节点统计")
    print("=" * 60)
    cursor.execute("SELECT COUNT(*) FROM fleet_nodes WHERE is_deleted = 0")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT xboard_node_id) FROM fleet_nodes WHERE is_deleted = 0")
    unique = cursor.fetchone()[0]
    print(f"  总节点数: {total}")
    print(f"  唯一 xboard_node_id 数: {unique}")
    print(f"  重复数量: {total - unique}")

    # 3. 查看重复的节点
    print("\n" + "=" * 60)
    print("3. 重复的节点详情 (前20条)")
    print("=" * 60)
    cursor.execute("""
        SELECT xboard_node_id, COUNT(*) as cnt, MAX(id) as max_id, MIN(id) as min_id
        FROM fleet_nodes 
        WHERE is_deleted = 0 AND xboard_node_id IS NOT NULL
        GROUP BY xboard_node_id 
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    if rows:
        print(f"  {'xboard_node_id':<40} {'重复次数':<10} {'最大id':<10} {'最小id'}")
        print("  " + "-" * 75)
        for row in rows:
            print(f"  {row[0]:<40} {row[1]:<10} {row[2]:<10} {row[3]}")
    else:
        print("  没有发现重复节点")

    conn.close()

if __name__ == '__main__':
    check_duplicates()
