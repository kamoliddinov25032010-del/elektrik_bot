import aiosqlite
from datetime import datetime

from config import ADMIN_IDS, DB_PATH


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


DEFAULT_SETTINGS = {
    "about": "Biz elektr montaj ishlari bilan shug'ullanamiz: uylarda sim tortish, shit yig'ish, rozetka va yoritish o'rnatish.",
    "phone": "Hali kiritilmagan",
    "hours": "Dushanba, Chorshanba, Juma, Yakshanba",
    "address": "Hali kiritilmagan",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,
    name TEXT,
    username TEXT,
    phone TEXT,
    role TEXT NOT NULL DEFAULT 'mijoz',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    file_type TEXT NOT NULL,
    caption TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_tg INTEGER,
    client_name TEXT,
    client_phone TEXT,
    usta_id INTEGER,
    description TEXT,
    lat REAL,
    lon REAL,
    status TEXT DEFAULT 'yangi',
    work_price REAL DEFAULT 0,
    estimate REAL DEFAULT 0,
    estimate_ok INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS order_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    file_type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    kind TEXT,
    method TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    by_user INTEGER,
    category TEXT,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    details TEXT,
    created_at TEXT
);
"""

# Har bir zakaz uchun: ish haqi (wp), materiallar summasi (mat_sum), to'langan (paid)
ORDER_SELECT = """
SELECT o.*,
  COALESCE(o.work_price, 0) AS wp,
  COALESCE((SELECT SUM(m.qty * m.price) FROM materials m WHERE m.order_id = o.id), 0) AS mat_sum,
  COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.order_id = o.id), 0) AS paid
FROM orders o
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        await conn.commit()


async def execute(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(sql, params)
        await conn.commit()
        return cur.lastrowid


async def fetchall(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def fetchone(sql, params=()):
    rows = await fetchall(sql, params)
    return rows[0] if rows else None


async def scalar(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(sql, params)
        row = await cur.fetchone()
        return row[0] if row else None


# ---------- foydalanuvchilar ----------
async def upsert_user(tg_id, name, username):
    await execute(
        "INSERT INTO users (tg_id, name, username, role, created_at) VALUES (?, ?, ?, 'mijoz', ?) "
        "ON CONFLICT(tg_id) DO UPDATE SET name=excluded.name, username=excluded.username",
        (tg_id, name, username, now()),
    )
    if tg_id in ADMIN_IDS:
        await execute("UPDATE users SET role='admin' WHERE tg_id=?", (tg_id,))


async def get_role(tg_id) -> str:
    if tg_id in ADMIN_IDS:
        return "admin"
    r = await fetchone("SELECT role FROM users WHERE tg_id=?", (tg_id,))
    return r["role"] if r else "mijoz"


async def staff_ids() -> set:
    rows = await fetchall("SELECT tg_id FROM users WHERE role IN ('usta', 'admin')")
    return set(ADMIN_IDS) | {r["tg_id"] for r in rows}


async def user_name(tg_id) -> str:
    r = await fetchone("SELECT name FROM users WHERE tg_id=?", (tg_id,))
    return r["name"] if r and r["name"] else str(tg_id)


# ---------- sozlamalar ----------
async def get_setting(key):
    r = await fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else ""


async def set_setting(key, value):
    await execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ---------- zakaz ----------
async def get_order(oid):
    o = await fetchone(
        f"SELECT *, wp + mat_sum AS total, wp + mat_sum - paid AS debt FROM ({ORDER_SELECT}) WHERE id=?",
        (oid,),
    )
    return o


# ---------- log ----------
async def log(user_id, action, details=""):
    await execute(
        "INSERT INTO logs (user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        (user_id, action, details, now()),
    )
