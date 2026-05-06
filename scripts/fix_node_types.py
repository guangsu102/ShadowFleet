#!/usr/bin/env python3
"""
修复 Xboard 数据库中节点类型大小写错误的问题。

问题：ShadowFleet 早期版本创建的节点使用了大写的类型值（如 'AnyTLS'），
      而 Xboard 需要小写值（如 'anytls'）。

用法：
    python scripts/fix_node_types.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.connection import PostgresConnectionPool
from utils.config_parser import load_config


def fix_all() -> None:
    """修复数据库中节点类型的大小写问题。"""
    # Load config from explicit path
    config_path = project_root / "config.yaml"
    if not config_path.exists():
        config_path = project_root / "config.dev.yaml"
    
    if not config_path.exists():
        print(f"ERROR: Config file not found at {config_path}")
        return
    
    print(f"Loading config from: {config_path}")
    config = load_config(config_path)
    
    # Create database pool manually
    xboard_config = config.xboard
    
    import psycopg2
    
    db_conn = psycopg2.connect(
        host=xboard_config.host,
        port=xboard_config.port,
        database=xboard_config.database,
        user=xboard_config.user,
        password=xboard_config.password,
        sslmode=xboard_config.ssl_mode,
        connect_timeout=10,
    )

    # Type mapping: wrong -> correct
    type_fixes = {
        'AnyTLS': 'anytls',
        'Hysteria2': 'hysteria',
        'hysteria2': 'hysteria',
    }

    try:
        cursor = db_conn.cursor()
        
        # Find nodes with wrong type (only sf- prefixed nodes)
        wrong_types = list(type_fixes.keys())
        placeholders = ','.join(['%s'] * len(wrong_types))
        cursor.execute(
            f"SELECT id, name, type FROM public.v2_server WHERE name LIKE 'sf-%%' AND type IN ({placeholders})",
            wrong_types
        )
        wrong_nodes = cursor.fetchall()

        if not wrong_nodes:
            print("No ShadowFleet nodes with wrong type found.")
            return

        print(f"Found {len(wrong_nodes)} ShadowFleet nodes with wrong type:")
        for node_id, name, node_type in wrong_nodes:
            correct = type_fixes.get(node_type, node_type)
            print(f"  - {name} (ID: {node_id}): '{node_type}' -> '{correct}'")

        # Fix the types
        for node_id, name, node_type in wrong_nodes:
            correct_type = type_fixes.get(node_type)
            if correct_type:
                cursor.execute(
                    "UPDATE public.v2_server SET type = %s WHERE id = %s",
                    (correct_type, node_id)
                )
                print(f"Fixed: '{name}' (ID: {node_id})")

        db_conn.commit()
        print("All node types fixed successfully!")
        cursor.close()

    except Exception as e:
        db_conn.rollback()
        print(f"ERROR: {e}")
    finally:
        db_conn.close()


if __name__ == '__main__':
    fix_all()
