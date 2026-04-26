import sqlite3
import json
import time
import os

# Get absolute path for DB to avoid working directory issues
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_cache.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ai_summaries (
            place_id TEXT,
            purpose TEXT,
            summary_json TEXT,
            created_at REAL,
            PRIMARY KEY (place_id, purpose)
        )
    ''')
    conn.commit()
    conn.close()

def get_cached_summary(place_id, purpose):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT summary_json, created_at FROM ai_summaries WHERE place_id=? AND purpose=?', (place_id, purpose))
        row = c.fetchone()
        conn.close()
        
        if row:
            summary_json, created_at = row
            # Cache expires in 24 hours (86400 seconds)
            if time.time() - created_at < 86400:
                return json.loads(summary_json)
    except Exception as e:
        print("CACHE GET ERROR:", e)
    return None

def save_cached_summary(place_id, purpose, summary_json):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO ai_summaries (place_id, purpose, summary_json, created_at)
            VALUES (?, ?, ?, ?)
        ''', (place_id, purpose, json.dumps(summary_json), time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        print("CACHE SAVE ERROR:", e)

# Initialize when module loads
init_db()
