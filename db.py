import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'client'
                  CHECK (role IN ('client', 'trainer', 'admin')),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
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
"""


def get_db():
    if "db" not in g:
        # isolation_level=None: транзакциями управляем явно (см. booking.py)
        g.db = sqlite3.connect(current_app.config["DATABASE"], isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def migrate(conn):
    """Донастройка старых баз: колонка hall_id у slots появилась позже."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(slots)")]
    if "hall_id" not in cols:
        conn.execute("ALTER TABLE slots ADD COLUMN hall_id INTEGER REFERENCES halls(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_slots_hall ON slots(hall_id, starts_at)")


def init_db():
    Path(current_app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)
    migrate(conn)


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
