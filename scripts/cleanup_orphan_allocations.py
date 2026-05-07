#!/usr/bin/env python3
"""
清理 ShadowFleet 孤儿的 Allocation 记录
检查 xboard_node_id 在 fleet_nodes 中是否还存在，如果不存在则清理

使用方法:
    python scripts/cleanup_orphan_allocations.py
"""
import argparse
import os
import sqlite3
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="清理孤儿的 Allocation 记录")
    parser.add_argument(
        "--db",
        default="/home/shadowfleet/ShadowFleet/data/shadowfleet.db",
        help=f"SQLite 数据库路径 (默认: /home/shadowfleet/ShadowFleet/data/shadowfleet.db)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认直接执行",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示不执行",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.db):
        print(f"错误: 数据库文件不存在: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 先查看当前状态
    print("=" * 60)
    print("当前 Allocation 统计")
    print("=" * 60)

    cursor.execute(
        """
        SELECT allocation_status, COUNT(*) as cnt, SUM(vcpu_count) as vcpu
        FROM fleet_asset_allocations
        GROUP BY allocation_status
    """
    )
    for row in cursor.fetchall():
        print(f"  {row['allocation_status']}: {row['cnt']} 条, vCPU: {row['vcpu'] or 0}")

    # 2. 找出孤儿的 allocation（xboard_node_id 在 fleet_nodes 中不存在或已删除）
    print("\n" + "=" * 60)
    print("检查孤儿 Allocation（节点已删除但 allocation 仍存在）")
    print("=" * 60)

    cursor.execute(
        """
        SELECT faa.id, faa.asset_id, faa.xboard_node_id, faa.protocol_type,
               faa.allocation_status, faa.vcpu_count,
               fa.asset_name, fn.node_name, fn.is_deleted
        FROM fleet_asset_allocations faa
        JOIN fleet_assets fa ON fa.id = faa.asset_id
        LEFT JOIN fleet_nodes fn ON fn.xboard_node_id = faa.xboard_node_id
        WHERE faa.allocation_status = 'allocated'
    """
    )

    orphans = []
    for row in cursor.fetchall():
        node_deleted = row["is_deleted"] == 1
        node_not_exists = row["node_name"] is None

        if node_deleted or node_not_exists:
            orphans.append(dict(row))
            status = "节点已删除" if node_deleted else "节点不存在"
            print(
                f"  [孤儿] id={row['id']:4}, asset={row['asset_name']:15}, "
                f"xboard_node_id={row['xboard_node_id']:6}, "
                f"protocol={row['protocol_type']:10}, "
                f"status={row['allocation_status']:12}, "
                f"({status})"
            )

    if not orphans:
        print("  没有发现孤儿 allocation 记录")
        conn.close()
        return

    print(f"\n共发现 {len(orphans)} 条孤儿 allocation 记录")

    # 3. 按资产统计
    print("\n按资产统计:")
    asset_stats = {}
    for o in orphans:
        asset_name = o["asset_name"]
        if asset_name not in asset_stats:
            asset_stats[asset_name] = 0
        asset_stats[asset_name] += 1
    for name, cnt in asset_stats.items():
        print(f"  {name}: {cnt} 条")

    # 4. Dry run
    if args.dry_run:
        print("\n[DRY RUN] 跳过实际清理操作")
        conn.close()
        return

    # 5. 确认清理
    print("\n" + "=" * 60)
    if args.yes:
        response = "yes"
    else:
        response = input(f"确认清理这 {len(orphans)} 条孤儿记录? (yes/no): ")

    if response.lower() != "yes":
        print("已取消")
        conn.close()
        return

    # 6. 执行清理
    orphan_ids = [o["id"] for o in orphans]
    placeholders = ",".join("?" * len(orphan_ids))

    cursor.execute(
        f"""
        UPDATE fleet_asset_allocations
        SET allocation_status = 'released'
        WHERE id IN ({placeholders})
    """,
        orphan_ids,
    )
    conn.commit()

    print(f"\n已清理 {cursor.rowcount} 条记录")

    # 7. 显示清理后的统计
    print("\n" + "=" * 60)
    print("清理后的 Allocation 统计")
    print("=" * 60)

    cursor.execute(
        """
        SELECT allocation_status, COUNT(*) as cnt, SUM(vcpu_count) as vcpu
        FROM fleet_asset_allocations
        GROUP BY allocation_status
    """
    )
    for row in cursor.fetchall():
        print(f"  {row['allocation_status']}: {row['cnt']} 条, vCPU: {row['vcpu'] or 0}")

    conn.close()
    print("\n清理完成!")


if __name__ == "__main__":
    main()
