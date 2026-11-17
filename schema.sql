CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'client'
                  CHECK (role IN ('client', 'trainer', 'admin')),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE class_types (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    description      TEXT    NOT NULL DEFAULT '',
    duration_min     INTEGER NOT NULL CHECK (duration_min > 0),
    default_capacity INTEGER NOT NULL CHECK (default_capacity > 0)
);

CREATE TABLE halls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE slots (
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

CREATE INDEX idx_slots_starts ON slots(starts_at);

CREATE TABLE bookings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    slot_id    INTEGER NOT NULL REFERENCES slots(id),
    status     TEXT    NOT NULL DEFAULT 'booked'
               CHECK (status IN ('booked', 'cancelled')),
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, slot_id)
);

CREATE INDEX idx_bookings_slot ON bookings(slot_id, status);

CREATE INDEX idx_slots_hall ON slots(hall_id, starts_at);
