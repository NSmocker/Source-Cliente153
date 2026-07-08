import sqlite3
import json

DB_PATH = r"C:\Users\sinch\.local\share\mimocode\mimocode.db"
PROJECT_ID = "0115b98b-db3b-449d-9b82-2d5c48c44e8d"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Task schema
print("=== TASK SCHEMA ===")
cur.execute("PRAGMA table_info(task)")
for row in cur.fetchall():
    print(f"  {row}")

# Project sessions for this project
print("\n=== PROJECT SESSIONS (this project) ===")
cur.execute("SELECT id, title, time_created FROM session WHERE project_id=? ORDER BY time_created DESC", (PROJECT_ID,))
sessions = cur.fetchall()
for s in sessions:
    print(f"  {s}")

# Tasks for this project's sessions
print("\n=== TASKS ===")
session_ids = [s[0] for s in sessions]
if session_ids:
    placeholders = ",".join(["?"] * len(session_ids))
    cur.execute(f"SELECT * FROM task WHERE session_id IN ({placeholders})", session_ids)
    cols = [d[0] for d in cur.description]
    print(f"  Columns: {cols}")
    for row in cur.fetchall():
        print(f"  {row}")

# Messages per session - count
print("\n=== MESSAGE COUNTS PER SESSION ===")
for sid in session_ids:
    cur.execute("SELECT COUNT(*) FROM message WHERE session_id=?", (sid,))
    count = cur.fetchone()[0]
    print(f"  {sid}: {count} messages")

# Memory FTS check
print("\n=== MEMORY FTS CONTENT ===")
cur.execute("SELECT COUNT(*) FROM memory_fts")
print(f"  Total memory_fts rows: {cur.fetchone()[0]}")
cur.execute("SELECT * FROM memory_fts LIMIT 10")
cols = [d[0] for d in cur.description]
print(f"  Columns: {cols}")
for row in cur.fetchall():
    print(f"  {row[:3]}...")

conn.close()
