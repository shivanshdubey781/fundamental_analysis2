import sqlite3
conn = sqlite3.connect('/var/www/fundamental_analysis2/data/tracker.db')
r = conn.execute('UPDATE screen_entries SET gated_entry=1 WHERE gated_entry=0 AND entry_price>0')
conn.commit()
print(f'Fixed {r.rowcount} entries')
conn.close()
