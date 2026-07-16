import os
import glob
import sqlite3
import pandas as pd

# Find latest autoscan CSV on the server
reports_dir = '/var/www/fundamental_analysis2/reports'
csv_files = glob.glob(os.path.join(reports_dir, 'screener_autoscan_*.csv'))
if not csv_files:
    # Fallback to any screener CSV
    csv_files = glob.glob(os.path.join(reports_dir, 'screener_*.csv'))

if not csv_files:
    print("Error: No screener CSV files found in reports directory!")
    sys.exit(1)

latest_csv = max(csv_files, key=os.path.getmtime)
print(f"Using latest report for pruning: {latest_csv}")

df = pd.read_csv(latest_csv)
ticker_scores = dict(zip(df['ticker'], df['total_score']))

db_path = '/var/www/fundamental_analysis2/data/tracker.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Get all active entries
rows = conn.execute("SELECT id, ticker, entry_at FROM screen_entries WHERE status = 'active'").fetchall()

to_delete_ids = []
# Let's dynamically resolve today's date in IST
from datetime import datetime
import pytz
IST = pytz.timezone('Asia/Kolkata')
today_str = datetime.now(IST).strftime("%Y-%m-%d")

for r in rows:
    ticker = r['ticker']
    entry_id = r['id']
    entry_at = r['entry_at']
    score = ticker_scores.get(ticker, 0.0)
    is_today = entry_at.startswith(today_str)
    
    if not is_today and score < 65.0:
        to_delete_ids.append(entry_id)

print(f"Active entries before: {len(rows)}")
print(f"Identifying {len(to_delete_ids)} active entries to prune.")

if to_delete_ids:
    placeholders = ",".join(str(x) for x in to_delete_ids)
    
    # Delete snapshots
    cur = conn.execute(f"DELETE FROM screen_snapshots WHERE entry_id IN ({placeholders})")
    print(f"Deleted {cur.rowcount} snapshots.")
    
    # Delete telegram events
    cur = conn.execute(f"DELETE FROM telegram_events WHERE entry_id IN ({placeholders})")
    print(f"Deleted {cur.rowcount} telegram events.")
    
    # Delete entries
    cur = conn.execute(f"DELETE FROM screen_entries WHERE id IN ({placeholders})")
    print(f"Deleted {cur.rowcount} screen_entries.")
    
    conn.commit()
    print("Database transaction committed successfully.")
else:
    print("No entries to prune.")

# Verify final active count
active_after = conn.execute("SELECT COUNT(*) FROM screen_entries WHERE status = 'active'").fetchone()[0]
print(f"Active entries after: {active_after}")

conn.close()
