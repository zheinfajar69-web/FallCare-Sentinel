import sqlite3
import os
import hashlib
import secrets
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

    # Tabel khusus untuk perangkat Pushover (maks 5 di sisi UI/API).
    # DIPERTAHANKAN untuk kompatibilitas mundur, tapi sudah tidak dipakai
    # aktif sejak beralih ke local_devices (broadcast lokal via IP) —
    # lihat catatan di local_devices di bawah.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pushover_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabel untuk akun login (users)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL
        )
    ''')

    # Tabel untuk perangkat HP lokal (MENGGANTIKAN Pushover).
    # Alurnya: aplikasi Android di HP memasukkan "IP Pusat" (IP laptop/
    # server yang menjalankan FastAPI ini) lalu HP mendaftarkan dirinya
    # sendiri (nama + IP miliknya) lewat POST /api/devices/register.
    # Baris `last_seen` diperbarui tiap kali device registrasi ulang
    # (dipakai sebagai heartbeat) sehingga backend bisa menandai device
    # ONLINE/OFFLINE tanpa perlu koneksi WebSocket permanen dari HP.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS local_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip TEXT NOT NULL UNIQUE,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Insert default settings jika kosong (termasuk setting untuk UI Web)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('notifMode', 'keduanya')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cameraStatus', 'off')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('poseEnabled', 'true')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('displayFilter', 'normal')")

    conn.commit()
    conn.close()

    # Pastikan ada akun admin default (admin/admin) supaya login pertama
    # kali tidak terkunci. Kalau sudah ada user apapun, dilewati.
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    if count == 0:
        create_user("admin", "admin")

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

# ==================== PUSHOVER DEVICES (legacy, tidak dipakai aktif) ====================

def get_all_pushover_devices():
    """Ambil semua perangkat Pushover, urut dari yang paling lama ditambahkan."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, api_key FROM pushover_devices ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "api_key": r[2]} for r in rows]

def replace_all_pushover_devices(devices):
    """Ganti seluruh daftar perangkat Pushover sekaligus."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM pushover_devices")
        cursor.executemany(
            "INSERT INTO pushover_devices (name, api_key) VALUES (?, ?)",
            [(d["name"], d["api_key"]) for d in devices]
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ==================== LOCAL DEVICES (IP Pusat, pengganti Pushover) ====================

def register_local_device(name: str, ip: str):
    """
    Daftarkan / perbarui heartbeat perangkat HP lokal.
    Dipanggil oleh app Android tiap kali dibuka / tiap interval tertentu,
    dengan mengirim nama + IP miliknya sendiri ke IP Pusat (server ini).
    Kalau IP sudah pernah terdaftar, hanya nama & last_seen yang diperbarui
    (jadi satu HP = satu baris, meski dia registrasi ulang berkali-kali).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO local_devices (name, ip, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(ip) DO UPDATE SET
            name = excluded.name,
            last_seen = CURRENT_TIMESTAMP
    ''', (name, ip))
    conn.commit()
    conn.close()

def get_all_local_devices():
    """Ambil semua perangkat lokal terdaftar, beserta kapan terakhir terlihat."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, ip, last_seen FROM local_devices ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "ip": r[2], "last_seen": r[3]} for r in rows]

def get_local_device_by_id(device_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, ip, last_seen FROM local_devices WHERE id=?", (device_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "ip": row[2], "last_seen": row[3]}

def delete_local_device(device_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM local_devices WHERE id=?", (device_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

# ==================== USERS / AUTH ====================

def _hash_password(password: str, salt: str) -> str:
    """Hash password + salt pakai SHA-256."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def create_user(username: str, password: str):
    """Bikin user baru. Dipakai lewat script create_admin.py."""
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
        (username, password_hash, salt)
    )
    conn.commit()
    conn.close()

def verify_user(username: str, password: str) -> bool:
    """True kalau username+password cocok dengan yang di database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, salt FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    stored_hash, salt = row
    return _hash_password(password, salt) == stored_hash

def change_password(username: str, old_password: str, new_password: str) -> bool:
    """
    Ganti password admin. Mengembalikan False kalau username tidak
    ditemukan ATAU old_password salah (supaya endpoint bisa balas 401
    tanpa membedakan dua kasus itu ke penyerang).
    """
    if not verify_user(username, old_password):
        return False
    salt = secrets.token_hex(16)
    password_hash = _hash_password(new_password, salt)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password_hash=?, salt=? WHERE username=?",
        (password_hash, salt, username)
    )
    conn.commit()
    conn.close()
    return True

# Inisialisasi DB saat file di-import
init_db()