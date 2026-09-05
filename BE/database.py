import sqlite3
import os
from datetime import datetime

# Mengubah nama database sesuai nama prototype
DB_NAME = "bytecraft.db"

def init_db():
    """Membuat tabel jika belum ada."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabel untuk pengaturan (tombol on/off, notif, dll)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Tabel untuk log kejadian jatuh
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fall_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            track_id INTEGER,
            status TEXT
        )
    ''')
    
    # Insert default settings jika kosong (termasuk setting untuk UI Web)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('notifMode', 'keduanya')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cameraStatus', 'off')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('poseEnabled', 'true')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('displayFilter', 'normal')")
    
    conn.commit()
    conn.close()

def get_setting(key, default_value=None):
    """Mengambil nilai pengaturan."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default_value

def update_setting(key, value):
    """Memperbarui nilai pengaturan."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings():
    """Mengambil semua pengaturan dalam bentuk dictionary (berguna untuk kirim ke Web UI)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def log_fall_event(track_id, status):
    """Mencatat saat ada yang jatuh."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO fall_logs (timestamp, track_id, status) VALUES (?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), track_id, status)
    )
    conn.commit()
    conn.close()

# Inisialisasi DB saat file di-import
init_db()