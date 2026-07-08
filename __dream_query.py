import sqlite3
import json
import os

DB_PATH = r"C:\Users\sinch\.local\share\mimocode\mimocode.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# List tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("=== TABLES ===")
for t in tables:
    print(t)

# List sessions
print("\n=== SESSIONS ===")
cur.execute("SELECT id, project_id, directory, title, time_created FROM session ORDER BY time_created DESC")
for row in cur.fetchall():
    print(f"  {row}")

# List tasks
print("\n=== TASKS ===")
cur.execute("SELECT id, session_id, title, status FROM task ORDER BY time_created DESC")
for row in cur.fetchall():
    print(f"  {row}")

conn.close()
