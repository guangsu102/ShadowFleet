#!/bin/bash
# ShadowFleet 同步调试脚本
# 在 Xboard 服务器上运行此脚本

echo "=============================================="
echo "ShadowFleet 同步调试测试"
echo "=============================================="

# 1. 检查 Xboard API 是否正常
echo ""
echo "[1] 测试 Xboard API 返回:"
curl -s 'http://137.175.65.47:7001/api/v1/shadowfleet/server-list' \
  -H 'Authorization: Bearer a3f8c9d2e1b4a7f6e5d8c3b2a1f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Xboard 返回节点数: {len(d[\"servers\"])}'); [print(f'  - id={s[\"id\"]}, name={s[\"name\"]}') for s in d['servers']]"

# 2. 检查 PostgreSQL 中 Xboard 节点
echo ""
echo "[2] 检查 PostgreSQL 中 Xboard 节点:"
PGPASSWORD=your_password psql -h localhost -U shadowfleet -d xboard -c "
SELECT id, name, type, show FROM public.v2_server WHERE name LIKE 'sf-%' ORDER BY id;
" 2>/dev/null || echo "需要手动检查 PostgreSQL"

# 3. 检查本地 SQLite 中 ShadowFleet 节点
echo ""
echo "[3] 检查本地 SQLite 中 ShadowFleet 节点:"
SQLITE_DB="./shadowfleet.db"
if [ -f "$SQLITE_DB" ]; then
  echo "本地节点 (is_deleted=0):"
  sqlite3 "$SQLITE_DB" "SELECT xboard_node_id, node_name, status, is_deleted FROM fleet_nodes WHERE is_deleted = 0;"
  echo ""
  echo "已删除的节点 (is_deleted=1):"
  sqlite3 "$SQLITE_DB" "SELECT xboard_node_id, node_name, status, is_deleted FROM fleet_nodes WHERE is_deleted = 1;"
else
  echo "SQLite 数据库不存在: $SQLITE_DB"
fi

echo ""
echo "=============================================="
echo "请将上述输出发给我，以便诊断同步问题"
echo "=============================================="
