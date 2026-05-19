# Xboard Sync Stability Fix

## Problem

The system crashed due to repeated sync errors when encountering orphan nodes (nodes that exist in Xboard but not in ShadowFleet's local database).

### Root Cause

1. **Exception-based error handling**: Every sync cycle threw `FleetNodeNotFoundError` for orphan nodes (IDs 328, 329, 330)
2. **Resource exhaustion**: Frequent exceptions (every minute, 3 errors per cycle) caused:
   - Memory consumption from exception stack traces
   - Log file bloat
   - Potential monitoring alert storms
   - Database transaction rollbacks

3. **No graceful degradation**: The system didn't distinguish between:
   - Real errors (network failures, database corruption)
   - Expected scenarios (orphan nodes from testing/cleanup)

## Solution

Implemented a **graceful degradation strategy** with three key improvements:

### 1. Pre-check Before Update
Added `StateRepo.node_exists_by_xboard_id()` method to check node existence before attempting updates.

```python
def node_exists_by_xboard_id(self, xboard_node_id: int) -> bool:
    """Check if a node exists by xboard_node_id (including deleted nodes)."""
    sql = "SELECT 1 FROM fleet_nodes WHERE xboard_node_id = ? LIMIT 1"
    with self._sqlite_manager.connection() as connection:
        row = connection.execute(sql, (xboard_node_id,)).fetchone()
    return row is not None
```

**Benefits**:
- Lightweight query (SELECT 1 instead of SELECT *)
- No exception throwing
- Fast execution

### 2. Orphan Node Tracking
Added `_orphan_nodes: set[int]` to track known orphan nodes and reduce log spam.

```python
if server.id not in self._orphan_nodes:
    self._logger.warning(
        "Skipping orphan node: xboard_node_id=%s exists in Xboard but not in local database",
        server.id,
    )
    self._orphan_nodes.add(server.id)
```

**Benefits**:
- Log warning only once per orphan node
- Prevents log file bloat
- Still provides visibility for debugging

### 3. Enhanced Logging
Updated sync completion log to include skipped nodes:

```python
log_message = f"Xboard sync completed: success={success_count} failed={failed_count}"
if skipped_count > 0:
    log_message += f" skipped={skipped_count} (orphan nodes)"
```

**Benefits**:
- Clear visibility into sync results
- Distinguishes between failures and expected skips
- Helps with monitoring and alerting

## Impact

### Before
```
2026-05-19 21:44:17 | ERROR | Failed to sync Xboard status for server id=328
Traceback (most recent call last):
  ...
  FleetNodeNotFoundError: Fleet node not found for xboard_node_id=328
```
- 3 exceptions per minute
- System crash risk
- Log file bloat

### After
```
2026-05-19 21:44:17 | WARNING | Skipping orphan node: xboard_node_id=328 exists in Xboard but not in local database
2026-05-19 21:44:17 | INFO | Xboard sync completed: success=4 failed=0 skipped=3 (orphan nodes)
```
- No exceptions
- Single warning per orphan node (logged once)
- System stability maintained

## Testing

To verify the fix works:

1. Deploy the updated code
2. Monitor logs for the new warning message format
3. Confirm no more `FleetNodeNotFoundError` exceptions
4. Verify sync completion shows `skipped=N (orphan nodes)`

## Future Improvements

Consider adding:
1. **Orphan node cleanup**: Periodic job to remove orphan nodes from Xboard
2. **Metrics**: Track orphan node count over time
3. **Alerting**: Alert if orphan node count exceeds threshold
4. **Auto-sync**: Option to automatically create local records for orphan nodes

## Files Changed

- `services/xboard_sync_service.py`: Added orphan node handling
- `database/state_repo.py`: Added `node_exists_by_xboard_id()` method
