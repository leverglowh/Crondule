import sqlite3

import pytz

DB_NAME = "crondule.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            chat_id TEXT PRIMARY KEY,
            timezone TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            type TEXT,
            trigger TEXT,
            message TEXT,
            next_run_time TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_timezone_for_chat(chat_id, timezone):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("REPLACE INTO user_settings (chat_id, timezone) VALUES (?, ?)", (str(chat_id), timezone))
    conn.commit()
    conn.close()

def get_timezone_for_chat(chat_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT timezone FROM user_settings WHERE chat_id = ?", (str(chat_id),))
    row = cur.fetchone()
    conn.close()
    return pytz.timezone(row[0]) if row else pytz.timezone("UTC")
