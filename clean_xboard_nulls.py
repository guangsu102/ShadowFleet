"""
清理 xboard v2_server 表中 group_ids、route_ids 等 JSON 字段的 NULL 值。
修复后 xboard PHP 端不会再报 count(): Argument #1 ($value) must be of type Countable|array, null given
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import psycopg2


def main():
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="xboard",
        user="xboard",
        password="your_password_here",  # <-- 改成你的实际密码
    )
    cursor = conn.cursor()

    # 先预览脏数据
    print("=== 预览脏数据 ===")
    cursor.execute("""
        SELECT id, name, group_ids, route_ids, tags, protocol_settings, rate_time_ranges
        FROM public.v2_server
        WHERE group_ids IS NULL OR group_ids = ''
           OR route_ids IS NULL OR route_ids = ''
           OR tags IS NULL
           OR protocol_settings IS NULL
           OR rate_time_ranges IS NULL
        LIMIT 20
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"  id={row[0]} name={row[1]} group_ids={row[2]!r} route_ids={row[3]!r}")

    if not rows:
        print("  没有脏数据，无需清理")
        conn.close()
        return

    # 确认清理范围（只改 ShadowFleet 创建的节点）
    cursor.execute("""
        SELECT COUNT(*)
        FROM public.v2_server
        WHERE name LIKE 'sf-%'
          AND (
              group_ids IS NULL OR group_ids = ''
           OR route_ids IS NULL OR route_ids = ''
           OR tags IS NULL
           OR protocol_settings IS NULL
           OR rate_time_ranges IS NULL
          )
    """)
    count = cursor.fetchone()[0]
    print(f"\nShadowFleet 节点受影响数量: {count}")

    confirm = input("确认执行清理? 输入 YES 继续: ")
    if confirm != "YES":
        print("已取消")
        conn.close()
        return

    # 执行清理
    print("\n=== 执行清理 ===")
    cursor.execute("""
        UPDATE public.v2_server
        SET group_ids = '[]'
        WHERE (group_ids IS NULL OR group_ids = '')
          AND name LIKE 'sf-%'
    """)
    print(f"  group_ids 已修复: {cursor.rowcount} 行")

    cursor.execute("""
        UPDATE public.v2_server
        SET route_ids = '[]'
        WHERE (route_ids IS NULL OR route_ids = '')
          AND name LIKE 'sf-%'
    """)
    print(f"  route_ids 已修复: {cursor.rowcount} 行")

    cursor.execute("""
        UPDATE public.v2_server
        SET tags = '[]'
        WHERE tags IS NULL
          AND name LIKE 'sf-%'
    """)
    print(f"  tags 已修复: {cursor.rowcount} 行")

    cursor.execute("""
        UPDATE public.v2_server
        SET protocol_settings = '{}'
        WHERE protocol_settings IS NULL
          AND name LIKE 'sf-%'
    """)
    print(f"  protocol_settings 已修复: {cursor.rowcount} 行")

    cursor.execute("""
        UPDATE public.v2_server
        SET rate_time_ranges = '[]'
        WHERE rate_time_ranges IS NULL
          AND name LIKE 'sf-%'
    """)
    print(f"  rate_time_ranges 已修复: {cursor.rowcount} 行")

    conn.commit()

    # 验证
    print("\n=== 验证 ===")
    cursor.execute("""
        SELECT COUNT(*)
        FROM public.v2_server
        WHERE name LIKE 'sf-%'
          AND (
              group_ids IS NULL OR group_ids = ''
           OR route_ids IS NULL OR route_ids = ''
           OR tags IS NULL
           OR protocol_settings IS NULL
           OR rate_time_ranges IS NULL
          )
    """)
    remaining = cursor.fetchone()[0]
    print(f"  清理后残留脏数据: {remaining} 行")

    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
