#!/usr/bin/env python3
"""
同步逻辑 bug 验证测试

问题描述：
- 本地节点被标记为 is_deleted=1 后，sync_with_xboard() 无法恢复它们
- 因为 list_active_nodes() 只返回 is_deleted=0 的节点
- 唯一索引是部分索引 (WHERE is_deleted=0)，所以会创建重复记录
"""

from dataclasses import dataclass


@dataclass
class XboardNode:
    node_id: int
    node_name: str  # 带 sf- 前缀
    node_type: str


@dataclass
class LocalNode:
    xboard_node_id: int
    node_name: str  # 带 sf- 前缀
    status: str
    is_deleted: int


def strip_sf_prefix(name: str) -> str:
    """去掉 sf- 前缀"""
    if name.startswith("sf-"):
        return name[3:]
    return name


def simulate_sync_logic(xboard_nodes: list[XboardNode], local_nodes: list[LocalNode]):
    """模拟 sync_with_xboard 的逻辑"""

    print("=" * 70)
    print("同步逻辑模拟")
    print("=" * 70)

    # 模拟 list_active_nodes() - 只返回 is_deleted=0 的节点
    active_local_nodes = [n for n in local_nodes if n.is_deleted == 0]
    print(f"\n[1] Xboard 节点数量: {len(xboard_nodes)}")
    for n in xboard_nodes:
        print(f"    - id={n.node_id}, name='{n.node_name}', type={n.node_type}")

    print(f"\n[2] 本地活跃节点 (is_deleted=0): {len(active_local_nodes)}")
    if active_local_nodes:
        for n in active_local_nodes:
            print(f"    - id={n.xboard_node_id}, name='{n.node_name}', status={n.status}")
    else:
        print("    (无)")

    print(f"\n[3] 本地被删除节点 (is_deleted=1): {len(local_nodes) - len(active_local_nodes)}")
    deleted_nodes = [n for n in local_nodes if n.is_deleted == 1]
    if deleted_nodes:
        for n in deleted_nodes:
            print(f"    - id={n.xboard_node_id}, name='{n.node_name}', status={n.status}")

    # 同步逻辑
    xboard_names_stripped = {strip_sf_prefix(n.node_name) for n in xboard_nodes}
    local_names = {n.node_name for n in active_local_nodes}  # 只看活跃的

    print("\n" + "=" * 70)
    print("同步对比分析")
    print("=" * 70)

    print(f"\n[Xboard 名称集合 (去 sf- 前缀)]: {xboard_names_stripped}")
    print(f"[本地活跃名称集合]: {local_names}")

    created = 0
    already_synced = 0
    deleted_recovery_needed = 0
    orphan_deleted_skipped = 0

    # 步骤1: 处理 Xboard 节点
    print("\n[步骤1] 处理 Xboard 节点:")
    for xboard_node in xboard_nodes:
        name_stripped = strip_sf_prefix(xboard_node.node_name)
        if name_stripped in local_names:
            already_synced += 1
            print(f"  ✓ '{name_stripped}' 在本地活跃节点中存在 → already_synced")
        else:
            # 问题：检查被删除的节点
            deleted_match = next(
                (n for n in deleted_nodes if strip_sf_prefix(n.node_name) == name_stripped),
                None
            )
            if deleted_match:
                deleted_recovery_needed += 1
                print(f"  ✗ '{name_stripped}' 在本地存在但被 deleted (id={deleted_match.xboard_node_id})")
                print(f"     → BUG! sync 应该恢复它，但当前逻辑会尝试创建新记录!")
                print(f"     → 由于 UNIQUE 索引是部分索引 (WHERE is_deleted=0)，不会冲突")
                print(f"     → 会创建重复记录!")
            else:
                created += 1
                print(f"  + '{name_stripped}' 在本地不存在 → 创建新记录")

    # 步骤2: 检查孤儿节点
    print("\n[步骤2] 检查本地孤儿节点 (is_deleted=1 的节点会被跳过):")
    for deleted_node in deleted_nodes:
        orphan_deleted_skipped += 1
        print(f"  ⚠  '{deleted_node.node_name}' 在 is_deleted=1 中，跳过不处理")

    # 结果
    print("\n" + "=" * 70)
    print("同步结果统计")
    print("=" * 70)
    print(f"  already_synced = {already_synced}")
    print(f"  created = {created}")
    print(f"  deleted_recovery_needed = {deleted_recovery_needed}")
    print(f"  orphan_deleted_skipped = {orphan_deleted_skipped}")

    return {
        "already_synced": already_synced,
        "created": created,
        "deleted_recovery_needed": deleted_recovery_needed,
        "orphan_deleted_skipped": orphan_deleted_skipped,
    }


def show_database_schema():
    """显示数据库约束"""
    print("\n\n" + "=" * 70)
    print("数据库 Schema 分析")
    print("=" * 70)
    print("""
当前 UNIQUE 索引定义:
    CREATE UNIQUE INDEX idx_fleet_nodes_xboard_node_id_active
        ON fleet_nodes (xboard_node_id)
        WHERE is_deleted = 0;

这意味着:
- xboard_node_id 对 is_deleted=0 的行是唯一的
- xboard_node_id 对 is_deleted=1 的行可以有重复值
- 当 sync 创建新记录时，不会触发唯一约束冲突
- 结果：会创建重复记录！

例如:
  原始记录: id=10, xboard_node_id=65, is_deleted=1
  sync 创建: id=20, xboard_node_id=65, is_deleted=0 (不会冲突!)
  结果: 两个活跃节点引用同一个 Xboard 节点!
""")


def show_fix_solution():
    """显示修复方案"""
    print("\n\n" + "=" * 70)
    print("修复方案")
    print("=" * 70)
    print("""
方案1: 在创建前检查 xboard_node_id 是否已存在（包括 deleted）
    def sync_with_xboard():
        # 获取所有节点（包括 deleted）
        existing = self._get_node_by_xboard_node_id(xboard_node_id)  # 修改查询
        if existing and existing.is_deleted == 1:
            # 恢复已删除的节点
            self._state_repo.restore_node(xboard_node_id)
        elif not existing:
            self._state_repo.create_node(...)

方案2: 修改 UNIQUE 索引覆盖所有行
    CREATE UNIQUE INDEX idx_fleet_nodes_xboard_node_id
        ON fleet_nodes (xboard_node_id);
    (删除部分索引)

方案3: 添加"恢复已删除节点"的逻辑
    def restore_deleted_node(xboard_node_id):
        UPDATE fleet_nodes SET is_deleted=0, status='offline'
        WHERE xboard_node_id=? AND is_deleted=1

推荐方案1 + 方案3组合使用
""")


def main():
    # 模拟当前状态 - Xboard 有 4 个节点，本地全部是 deleted
    xboard_nodes = [
        XboardNode(node_id=65, node_name="sf-jpt-atl-667845", node_type="anytls"),
        XboardNode(node_id=66, node_name="sf-jpt-tro-661503", node_type="trojan"),
        XboardNode(node_id=67, node_name="sf-jpt-vls-665149", node_type="vless"),
        XboardNode(node_id=68, node_name="sf-jpt-vms-666592", node_type="vmess"),
    ]

    # 本地 SQLite 状态 - 全部是 deleted
    local_nodes = [
        LocalNode(xboard_node_id=65, node_name="sf-jpt-atl-667845", status="deleted", is_deleted=1),
        LocalNode(xboard_node_id=66, node_name="sf-jpt-tro-661503", status="deleted", is_deleted=1),
        LocalNode(xboard_node_id=67, node_name="sf-jpt-vls-665149", status="deleted", is_deleted=1),
        LocalNode(xboard_node_id=68, node_name="sf-jpt-vms-666592", status="deleted", is_deleted=1),
    ]

    print("BUG 验证测试")
    print("当前状态: Xboard 有 4 个节点 (id=65-68)，本地全部 is_deleted=1\n")

    result = simulate_sync_logic(xboard_nodes, local_nodes)
    show_database_schema()
    show_fix_solution()

    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)
    print(f"""
BUG 确认:
1. sync_with_xboard() 只处理 is_deleted=0 的节点
2. {result['deleted_recovery_needed']} 个节点被 deleted，但同步无法恢复它们
3. 重新同步会创建新记录，但由于部分 UNIQUE 索引，不会冲突
4. 结果：数据重复！

下一步:
需要在 sync_with_xboard() 中添加恢复已删除节点的逻辑
""")

    return result


if __name__ == "__main__":
    main()
