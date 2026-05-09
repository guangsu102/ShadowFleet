#!/usr/bin/env python3
"""Test script to verify Xboard PostgreSQL query for node status."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.xboard_repo import XboardRepo
from services.runtime_service import RuntimeContext


def main() -> None:
    print("=" * 60)
    print("Testing Xboard PostgreSQL Node Status Query")
    print("=" * 60)

    # Create runtime context from config
    from utils.config import load_config
    from utils.logger import setup_logger

    config = load_config()
    logger = setup_logger("xboard_test")

    runtime_context = RuntimeContext(config=config, logger=logger)

    # Initialize XboardRepo
    print("\n[1] Initializing XboardRepo...")
    try:
        xboard_repo = XboardRepo(runtime_context)
        print("    ✓ XboardRepo initialized successfully")
    except Exception as exc:
        print(f"    ✗ Failed to initialize XboardRepo: {exc}")
        return

    # Query all shadowfleet nodes
    print("\n[2] Querying all ShadowFleet nodes...")
    try:
        nodes = xboard_repo.list_all_shadowfleet_nodes()
        print(f"    ✓ Found {len(nodes)} nodes")
    except Exception as exc:
        print(f"    ✗ Failed to query nodes: {exc}")
        return

    # Display results
    print("\n[3] Node Details:")
    print("-" * 80)
    print(f"{'ID':<6} {'Name':<30} {'Type':<12} {'Host':<25} {'Show':<6}")
    print("-" * 80)

    for node in nodes:
        show_str = "可见" if node.show else "隐藏"
        print(f"{node.node_id:<6} {node.node_name:<30} {node.node_type:<12} {node.host:<25} {show_str:<6}")

    print("-" * 80)

    # Test getting single node runtime
    if nodes:
        print(f"\n[4] Testing get_node_runtime for node_id={nodes[0].node_id}...")
        try:
            runtime = xboard_repo.get_node_runtime(nodes[0].node_id)
            print(f"    ✓ Success!")
            print(f"    - show: {runtime.show} ({'可见' if runtime.show else '隐藏'})")
            print(f"    - xboard_status: {'online' if runtime.show else 'hidden'}")
        except Exception as exc:
            print(f"    ✗ Failed: {exc}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
