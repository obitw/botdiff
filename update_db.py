import sqlite3

conn = sqlite3.connect("data/botdiff.db")
try:
    conn.execute("ALTER TABLE tracked_players ADD COLUMN solo_tier TEXT")
    conn.execute("ALTER TABLE tracked_players ADD COLUMN solo_rank TEXT")
    conn.commit()
except Exception as e:
    print(e)
