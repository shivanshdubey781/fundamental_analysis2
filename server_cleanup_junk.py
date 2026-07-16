import sqlite3

db_path = '/var/www/fundamental_analysis2/data/tracker.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Get IDs of all entries with gated_entry = 0
rows = conn.execute("SELECT id, ticker, status FROM screen_entries WHERE gated_entry = 0").fetchall()
junk_ids = [r['id'] for r in rows]

print(f"Found {len(junk_ids)} junk entries with gated_entry = 0 on server.")

if junk_ids:
    placeholders = ",".join(str(x) for x in junk_ids)
    
    # 1. Delete snapshots
    cur = conn.execute(f"DELETE FROM screen_snapshots WHERE entry_id IN ({placeholders})")
    print(f"Deleted {cur.rowcount} snapshots.")
    
    # 2. Delete telegram events
    cur = conn.execute(f"DELETE FROM telegram_events WHERE entry_id IN ({placeholders})")
    print(f"Deleted {cur.rowcount} telegram events.")
    
    # 3. Delete entries
    cur = conn.execute(f"DELETE FROM screen_entries WHERE id IN ({placeholders})")
    print(f"Deleted {cur.rowcount} screen_entries.")
    
    conn.commit()
    print("Cleanup transaction committed successfully.")
else:
    print("No junk entries to clean up.")

# Verify remaining counts
active_count = conn.execute("SELECT COUNT(*) FROM screen_entries WHERE status = 'active'").fetchone()[0]
booked_count = conn.execute("SELECT COUNT(*) FROM screen_entries WHERE status IN ('target_hit', 'sl_hit', 'trail_sl_hit')").fetchone()[0]
print(f"Remaining active entries on server: {active_count}")
print(f"Remaining booked entries on server: {booked_count}")

conn.close()
