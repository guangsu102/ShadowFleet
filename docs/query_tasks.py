import sqlite3
conn = sqlite3.connect('shadowfleet.db')
rows = conn.execute(
    "SELECT id, task_type, status, correlation_id, last_error, attempt_count, created_at FROM fleet_provisioning_tasks ORDER BY created_at DESC LIMIT 10"
).fetchall()
for r in rows:
    print(r)
conn.close()
