"""Подключение к базе. Локально — файл SQLite, в облаке — Turso (если задан TURSO_DATABASE_URL)."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    email          TEXT    NOT NULL UNIQUE,
    password_hash  TEXT    NOT NULL,
    role           TEXT    NOT NULL DEFAULT 'client'
                   CHECK (role IN ('client', 'trainer', 'admin')),
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    email_verified INTEGER NOT NULL DEFAULT 0,
    title          TEXT,
    frame          TEXT
);

CREATE TABLE IF NOT EXISTS class_types (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    description      TEXT    NOT NULL DEFAULT '',
    duration_min     INTEGER NOT NULL CHECK (duration_min > 0),
    default_capacity INTEGER NOT NULL CHECK (default_capacity > 0)
);

CREATE TABLE IF NOT EXISTS halls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS slots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    class_type_id INTEGER NOT NULL REFERENCES class_types(id),
    trainer_id    INTEGER NOT NULL REFERENCES users(id),
    hall_id       INTEGER REFERENCES halls(id),
    starts_at     TEXT    NOT NULL,
    ends_at       TEXT    NOT NULL,
    capacity      INTEGER NOT NULL CHECK (capacity > 0),
    status        TEXT    NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'cancelled')),
    CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_slots_starts ON slots(starts_at);
CREATE INDEX IF NOT EXISTS idx_slots_hall ON slots(hall_id, starts_at);

CREATE TABLE IF NOT EXISTS bookings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    slot_id    INTEGER NOT NULL REFERENCES slots(id),
    status     TEXT    NOT NULL DEFAULT 'booked'
               CHECK (status IN ('booked', 'cancelled')),
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, slot_id)
);
CREATE INDEX IF NOT EXISTS idx_bookings_slot ON bookings(slot_id, status);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id, status);

CREATE TABLE IF NOT EXISTS subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    plan       TEXT    NOT NULL,
    price      INTEGER NOT NULL CHECK (price >= 0),
    starts_at  TEXT    NOT NULL,
    ends_at    TEXT    NOT NULL,
    card_last4 TEXT,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id, ends_at);

-- регистрация до ввода кода: пароль уже хешем, код — HMAC-хешем
CREATE TABLE IF NOT EXISTS signup_codes (
    email         TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    code_hash     TEXT    NOT NULL,
    expires_at    TEXT    NOT NULL,
    sent_at       TEXT    NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bonus_xp (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    day        TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    amount     INTEGER NOT NULL CHECK (amount > 0),
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, day, kind)
);
"""


def use_turso():
    return bool(current_app.config.get("TURSO_DATABASE_URL"))


def connect():
    """Новое подключение по настройкам текущего приложения."""
    cfg = current_app.config
    if use_turso():
        import turso
        return turso.Connection(cfg["TURSO_DATABASE_URL"], cfg.get("TURSO_AUTH_TOKEN") or "")
    # isolation_level=None: транзакциями управляем явно (см. booking.py)
    conn = sqlite3.connect(cfg["DATABASE"], isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def batch(conn, statements):
    """Несколько запросов разом. У Turso это один HTTP-запрос вместо нескольких."""
    if hasattr(conn, "batch"):
        return conn.batch(statements)
    return [conn.execute(sql, params) for sql, params in statements]


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def migrate(conn):
    """Донастройка старых баз: новые колонки появились позже."""
    scur, ucur = batch(conn, [("PRAGMA table_info(slots)", ()), ("PRAGMA table_info(users)", ())])
    cols = [r["name"] for r in scur.fetchall()]
    ucols = [r["name"] for r in ucur.fetchall()]
    if "hall_id" not in cols:
        conn.execute("ALTER TABLE slots ADD COLUMN hall_id INTEGER REFERENCES halls(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_slots_hall ON slots(hall_id, starts_at)")

    if "email_verified" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        # аккаунты, созданные до появления подтверждения (демо, тренеры), считаем подтверждёнными
        conn.execute("UPDATE users SET email_verified = 1")
    if "title" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN title TEXT")
    if "frame" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN frame TEXT")


def init_db():
    if not use_turso():
        Path(current_app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)
    migrate(conn)


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
