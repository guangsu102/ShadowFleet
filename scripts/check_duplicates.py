#!/usr/bin/env python3
"""检查生产环境重复节点数据 - 独立版本"""

import sqlite3
from pathlib import Path

# 自动检测数据库路径
def find_db_path():
    # 先尝试当前目录
    p = Path("shadowfleet.db")
    if p.exists():
        return str(p.absolute())
    p = Path("data/shadowfleet.db")
    if p.exists():
        return str(p.absolute())
    # 尝试上一级目录
    p = Path("../shadowfleet.db")
    if p.exists():
        return str(p.absolute())
    p = Path("../data/shadowfleet.db")
    if p.exists():
        return str(p.absolute())
    # 尝试常见的绝对路径
    for path in ["/data/shadowfleet.db", "/home/shadowfleet/shadowfleet.db"]:
        if Path(path).exists():
            return path
    return None

def check_duplicates():
    db_path = find_db_path()
    if not db_path:
        print("错误: 无法找到数据库文件 shadowfleet.db")
        print("请手动指定数据库路径，或在项目根目录运行此脚本")
        return

    print(f"数据库路径: {db_path}\n")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. 检查迁移是否执行
    print("=" * 60)
    print("1. 检查迁移记录")
    print("=" * 60)
    try:
        cursor.execute("SELECT * FROM schema_migrations WHERE name LIKE '%duplicate%'")
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(f"  {row}")
        else:
            print("  未找到重复节点相关的迁移记录")
    except sqlite3.OperationalError as e:
        print(f"  查询失败: {e}")

    # 2. 统计总数量
    print("\n" + "=" * 60)
    print("2. 节点统计")
    print("=" * 60)
    try:
        cursor.execute("SELECT COUNT(*) FROM fleet_nodes WHERE is_deleted = 0")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT xboard_node_id) FROM fleet_nodes WHERE is_deleted = 0")
        unique = cursor.fetchone()[0]
        print(f"  总节点数: {total}")
        print(f"  唯一 xboard_node_id 数: {unique}")
        print(f"  重复数量: {total - unique}")
    except sqlite3.OperationalError as e:
        print(f"  查询失败: {e}")

    # 3. 查看重复的节点
    print("\n" + "=" * 60)
    print("3. 重复的节点详情 (前20条)")
    print("=" * 60)
    try:
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
    except sqlite3.OperationalError as e:
        print(f"  查询失败: {e}")

    # 4. 检查索引是否已创建
    print("\n" + "=" * 60)
    print("4. 检查唯一索引")
    print("=" * 60)
    try:
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE '%xboard_node_id%'
        """)
        indexes = cursor.fetchall()
        if indexes:
            for idx in indexes:
                print(f"  索引: {idx[0]}")
        else:
            print("  未找到 xboard_node_id 相关的索引")
    except sqlite3.OperationalError as e:
        print(f"  查询失败: {e}")

    conn.close()

if __name__ == '__main__':
    check_duplicates()
