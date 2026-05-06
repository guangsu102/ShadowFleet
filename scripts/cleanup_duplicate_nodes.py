#!/usr/bin/env python3
"""
Cleanup duplicate nodes from fleet_nodes table.

This script:
1. Finds and removes duplicate xboard_node_id entries (keeps latest by id)
2. Adds a UNIQUE index on xboard_node_id for non-deleted rows

Run this script manually or as part of deployment:
    python scripts/cleanup_duplicate_nodes.py

For dry-run mode (shows what would be deleted without actually deleting):
    python scripts/cleanup_duplicate_nodes.py --dry-run

    python scripts/cleanup_duplicate_nodes.py --dry-run --db-path data/shadowfleet.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def find_duplicates(connection) -> dict[int, list[tuple]]:
    """Find all xboard_node_ids that have duplicate entries."""
    query = """
        SELECT xboard_node_id, id, node_name, status, updated_at
        FROM fleet_nodes
        WHERE is_deleted = 0
        ORDER BY xboard_node_id, id DESC
    """
    rows = connection.execute(query).fetchall()

    # Group by xboard_node_id
    groups: dict[int, list[tuple]] = {}
    for row in rows:
        xboard_node_id = row["xboard_node_id"]
        if xboard_node_id not in groups:
            groups[xboard_node_id] = []
        groups[xboard_node_id].append(tuple(row))

    # Return only groups with duplicates
    return {k: v for k, v in groups.items() if len(v) > 1}


def cleanup_duplicates(connection, dry_run: bool = True) -> tuple[int, list[tuple]]:
    """
    Remove duplicate nodes, keeping the one with highest id (most recent).
    Returns (total_duplicates_removed, list of removed node info).
    """
    # Find duplicates
    duplicates = find_duplicates(connection)

    if not duplicates:
        return 0, []

    removed = []
    total_removed = 0

    for xboard_node_id, rows in duplicates.items():
        # Keep the first one (highest id due to ORDER BY DESC)
        keeper = rows[0]
        to_delete = rows[1:]  # rest are duplicates

        for dup in to_delete:
            dup_id, dup_name, dup_status, dup_updated = dup[1], dup[2], dup[3], dup[4]
            removed.append((xboard_node_id, dup_id, dup_name, dup_status, dup_updated))
            total_removed += 1

            if not dry_run:
                connection.execute(
                    "DELETE FROM fleet_nodes WHERE id = ?",
                    (dup_id,)
                )

    return total_removed, removed


def add_unique_index(connection) -> bool:
    """Add UNIQUE index on xboard_node_id. Returns True if successful."""
    index_name = "idx_fleet_nodes_xboard_node_id_active"

    # Check if index already exists
    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,)
    ).fetchone()

    if existing:
        print(f"  Index '{index_name}' already exists.")
        return True

    try:
        connection.execute(f"""
            CREATE UNIQUE INDEX {index_name}
            ON fleet_nodes (xboard_node_id)
            WHERE is_deleted = 0
        """)
        print(f"  Created index '{index_name}'.")
        return True
    except Exception as e:
        print(f"  Failed to create index: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup duplicate nodes from fleet_nodes table"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/shadowfleet.db",
        help="Path to SQLite database (default: data/shadowfleet.db)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Please run from project root or specify --db-path")
        sys.exit(1)

    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        print(f"\n{'='*60}")
        print(f"Duplicate Node Cleanup Script")
        print(f"{'='*60}")
        print(f"Database: {db_path.absolute()}")
        print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
        print(f"{'-'*60}\n")

        # Step 1: Find duplicates
        print("Step 1: Scanning for duplicate xboard_node_ids...")
        duplicates = find_duplicates(connection)

        if not duplicates:
            print("  No duplicates found. Database is clean!")
        else:
            print(f"  Found {len(duplicates)} xboard_node_ids with duplicates:")
            total_dups = sum(len(v) - 1 for v in duplicates.values())
            print(f"  Total duplicate rows: {total_dups}\n")

            for xboard_node_id, rows in sorted(duplicates.items()):
                print(f"  xboard_node_id={xboard_node_id}: {len(rows)} entries")
                for i, row in enumerate(rows):
                    marker = " <- KEEP" if i == 0 else "    DELETE"
                    print(f"    [{i}] id={row[1]:6} | {row[2][:30]:30} | {row[3]:10} | {row[4]}")

            # Step 2: Cleanup
            print(f"\nStep 2: {'[DRY RUN] Would delete' if args.dry_run else 'Deleting'} duplicate nodes...")
            removed_count, removed_info = cleanup_duplicates(connection, dry_run=args.dry_run)

            if removed_count > 0:
                if args.dry_run:
                    print(f"  Would remove {removed_count} duplicate rows:")
                else:
                    print(f"  Removed {removed_count} duplicate rows:")
                    connection.commit()

                for xboard_node_id, node_id, name, status, updated in removed_info[:10]:
                    print(f"    xboard_node_id={xboard_node_id}, id={node_id}: {name[:30]} ({status})")
                if len(removed_info) > 10:
                    print(f"    ... and {len(removed_info) - 10} more")

        # Step 3: Add unique index
        print(f"\nStep 3: Ensuring UNIQUE index exists...")
        success = add_unique_index(connection)
        if not args.dry_run and success:
            connection.commit()

        # Final summary
        print(f"\n{'='*60}")
        if args.dry_run:
            print("DRY RUN complete. Run without --dry-run to apply changes.")
        else:
            print("Cleanup complete!")
        print(f"{'='*60}\n")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
