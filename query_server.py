import sqlite3
conn = sqlite3.connect('/var/www/fundamental_analysis2/data/tracker.db')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, ticker, entry_at, entry_price FROM screen_entries WHERE status = 'active' AND gated_entry = 1").fetchall()
print(f"Found {len(rows)} active gated entries on server:")
for r in rows:
    print(f"  {r['ticker']}: id={r['id']}, entry_at={r['entry_at']}, price={r['entry_price']}")
conn.close()
