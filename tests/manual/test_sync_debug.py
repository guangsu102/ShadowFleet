#!/usr/bin/env python3
"""
测试脚本：验证 Xboard 同步逻辑
模拟 sync_with_xboard 的对比过程，定位同步问题
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataclasses import dataclass
from typing import Optional


@dataclass
class XboardNode:
    node_id: int
    node_name: str
    node_type: str


@dataclass
class LocalNode:
    id: int
    xboard_node_id: int
    node_name: str
    status: str


def strip_sf_prefix(name: str) -> str:
    """Strip sf- prefix from node name for comparison."""
    if name.startswith("sf-"):
        return name[3:]
    return name


def simulate_sync():
    print("=" * 60)
    print("Xboard 同步逻辑模拟测试")
    print("=" * 60)

    # 模拟 Xboard API 返回的数据
    xboard_nodes = [
        XboardNode(node_id=65, node_name="sf-jpt-atl-667845", node_type="anytls"),
        XboardNode(node_id=66, node_name="sf-jpt-tro-661503", node_type="trojan"),
        XboardNode(node_id=67, node_name="sf-jpt-vls-665149", node_type="vless"),
        XboardNode(node_id=68, node_name="sf-jpt-vms-666592", node_type="vmess"),
    ]

    # 模拟本地数据库的活跃节点
    # 假设本地节点名称已经去掉了 sf- 前缀（这是正常的）
    local_nodes = [
        LocalNode(id=1, xboard_node_id=65, node_name="jpt-atl-667845", status="offline"),
        LocalNode(id=2, xboard_node_id=66, node_name="jpt-tro-661503", status="offline"),
        LocalNode(id=3, xboard_node_id=67, node_name="jpt-vls-665149", status="offline"),
        LocalNode(id=4, xboard_node_id=68, node_name="jpt-vms-666592", status="offline"),
    ]

    print("\n[步骤1] Xboard 返回的节点:")
    for node in xboard_nodes:
        print(f"  - id={node.node_id}, name='{node.node_name}'")

    print("\n[步骤2] 本地数据库中的活跃节点:")
    for node in local_nodes:
        print(f"  - id={node.id}, xboard_id={node.xboard_node_id}, name='{node.node_name}', status={node.status}")

    # 同步逻辑
    print("\n[步骤3] 执行同步对比:")

    xboard_names_stripped = {strip_sf_prefix(n.node_name) for n in xboard_nodes}
    local_names = {n.node_name for n in local_nodes}

    print(f"\n  Xboard 节点名称集合 (去前缀): {xboard_names_stripped}")
    print(f"  本地节点名称集合: {local_names}")

    # 检查匹配情况
    print("\n[步骤4] 逐个节点对比:")
    for xboard_node in xboard_nodes:
        name_stripped = strip_sf_prefix(xboard_node.node_name)
        if name_stripped in local_names:
            print(f"  ✓ '{name_stripped}' 在本地存在，会标记为 already_synced")
        else:
            print(f"  ✗ '{name_stripped}' 不在本地存在，会创建新记录")

    print("\n[步骤5] 检查本地孤儿节点 (本地有但 Xboard 没有):")
    for local_node in local_nodes:
        if local_node.node_name not in xboard_names_stripped:
            print(f"  ✗ 本地节点 '{local_node.node_name}' 在 Xboard 中不存在，会被标记为 deleted")
        else:
            print(f"  ✓ 本地节点 '{local_node.node_name}' 在 Xboard 中存在，保留")

    # 预期结果
    print("\n" + "=" * 60)
    print("预期同步结果:")
    print("  created = 0 (Xboard 中的节点本地都有)")
    print("  orphan_local_deleted = 0 (本地节点 Xboard 都有)")
    print("  already_synced = 4")
    print("=" * 60)


def check_actual_database():
    """检查实际数据库状态"""
    print("\n\n" + "=" * 60)
    print("检查实际数据库状态")
    print("=" * 60)

    try:
        from database.state_repo import StateRepo
        from services.runtime_service import RuntimeContext

        # 尝试创建运行时上下文
        # 这里需要配置文件

        print("\n提示: 如果要检查实际数据库，请确保:")
        print("  1. 运行 shadowfleet 服务")
        print("  2. 在 Python 控制台中执行以下代码:")
        print()
        print("  from database.state_repo import StateRepo")
        print("  from services.runtime_service import RuntimeContext")
        print("  ")
        print("  # 假设你已经初始化了 runtime_context")
        print("  repo = StateRepo(runtime_context)")
        print("  nodes = repo.list_active_nodes()")
        print("  ")
        print("  # 打印所有节点")
        print("  for n in nodes:")
        print("      print(f'xboard_id={n.xboard_node_id}, name={n.node_name}')")

    except ImportError as e:
        print(f"\n无法导入模块: {e}")
        print("请在项目根目录运行此脚本")


def check_xboard_api():
    """直接调用 Xboard API 检查"""
    print("\n\n" + "=" * 60)
    print("直接调用 Xboard API 验证")
    print("=" * 60)

    import requests

    # 你需要配置这些值
    API_BASE_URL = "http://137.175.65.47:7001"
    API_KEY = "a3f8c9d2e1b4a7f6e5d8c3b2a1f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2"

    try:
        response = requests.get(
            f"{API_BASE_URL}/api/v1/shadowfleet/server-list",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=10
        )
        data = response.json()

        print(f"\nAPI 返回状态: {response.status_code}")
        print(f"节点数量: {len(data.get('servers', []))}")

        for server in data.get('servers', []):
            print(f"  - id={server['id']}, name='{server['name']}', type={server['type']}, is_online={server['is_online']}")

    except Exception as e:
        print(f"\nAPI 调用失败: {e}")


if __name__ == "__main__":
    simulate_sync()
    check_xboard_api()
    check_actual_database()
