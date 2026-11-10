from datetime import datetime, timedelta

import pytest

import booking
from conftest import login
from db import get_db


def slot_ids(app, n=3):
    with app.app_context():
        return [r[0] for r in get_db().execute(
            "SELECT id FROM slots ORDER BY starts_at LIMIT ?", (n,))]


def uid(app, email):
    with app.app_context():
        return get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def hall_id(app, name):
    with app.app_context():
        return get_db().execute("SELECT id FROM halls WHERE name = ?", (name,)).fetchone()[0]


def new_client(app, n):
    with app.app_context():
        get_db().execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, 'x')",
            (f"U{n}", f"u{n}@kbtu.kz"))
        return get_db().execute("SELECT id FROM users WHERE email = ?",
                                (f"u{n}@kbtu.kz",)).fetchone()[0]


# --- авторизация (FR-01, FR-02, FR-14)
def test_register_requires_kbtu_domain(client):
    r = client.post("/register", data={"name": "A", "email": "a@gmail.com",
                    "password": "12345678", "confirm": "12345678"})
    assert "kbtu.kz" in r.get_data(as_text=True)


def test_register_and_login(client):
    r = client.post("/register", data={"name": "A", "email": "a@kbtu.kz",
                    "password": "12345678", "confirm": "12345678"})
    assert r.status_code == 302
    assert login(client, "a@kbtu.kz", "12345678").status_code == 302


def test_login_errors_do_not_reveal_which_field(client):
    a = login(client, "client@kbtu.kz", "wrong").get_data(as_text=True)
    b = login(client, "nobody@kbtu.kz", "wrong").get_data(as_text=True)
    assert "Неверный email или пароль" in a and "Неверный email или пароль" in b


# --- роли (FR-03)
@pytest.mark.parametrize("email,pwd,url,code", [
    ("client@kbtu.kz", "Client12345", "/admin", 403),
    ("client@kbtu.kz", "Client12345", "/trainer", 403),
    ("trainer@kbtu.kz", "Trainer12345", "/admin", 403),
    ("admin@kbtu.kz", "Admin12345", "/admin", 200),
    ("trainer@kbtu.kz", "Trainer12345", "/trainer", 200),
])
def test_role_separation(client, email, pwd, url, code):
    login(client, email, pwd)
    assert client.get(url).status_code == code


def test_anonymous_redirected(client):
    assert client.get("/admin").status_code == 302
    assert client.get("/").status_code == 302


def test_client_cannot_post_admin_actions(as_client, app):
    assert as_client.post("/admin/slots/1/cancel").status_code == 403
    with app.app_context():
        assert get_db().execute("SELECT status FROM slots WHERE id=1").fetchone()[0] == "active"


# --- расписание и фильтры (FR-04, FR-15)
def test_schedule_and_filters(as_client):
    html = as_client.get("/").get_data(as_text=True)
    assert "Кроссфит" in html and "Записаться" in html
    only_yoga = as_client.get("/?type=1").get_data(as_text=True)
    assert "<b>Кроссфит</b>" not in only_yoga and "<b>Йога</b>" in only_yoga


def test_filter_free_only(as_client, app):
    ids = slot_ids(app, 1)
    with app.app_context():
        c = get_db()
        c.execute("UPDATE slots SET capacity = 1 WHERE id = ?", ids)
    other = new_client(app, 1)
    with app.app_context():
        booking.book(get_db(), other, ids[0])
    html = as_client.get("/?free=1").get_data(as_text=True)
    assert "Мест нет" not in html


# --- запись (FR-05..FR-08)
def test_book_and_cancel(as_client, app):
    sid = slot_ids(app)[0]
    as_client.post(f"/book/{sid}")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM bookings WHERE status='booked'").fetchone()[0] == 1
    as_client.post(f"/cancel/{sid}")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM bookings WHERE status='booked'").fetchone()[0] == 0
        booking.book(get_db(), uid(app, "client@kbtu.kz"), sid)  # повторная запись после отмены


def test_duplicate_rejected(app):
    sid, u = slot_ids(app)[0], uid(app, "client@kbtu.kz")
    with app.app_context():
        c = get_db()
        booking.book(c, u, sid)
        with pytest.raises(booking.BookingError, match="уже записаны"):
            booking.book(c, u, sid)


def test_full_slot_rejected(app):
    sid = slot_ids(app)[0]
    with app.app_context():
        c = get_db()
        c.execute("UPDATE slots SET capacity = 1 WHERE id = ?", (sid,))
        booking.book(c, new_client(app, 1), sid)
        with pytest.raises(booking.BookingError, match="мест нет"):
            booking.book(c, uid(app, "client@kbtu.kz"), sid)
        assert c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1


def test_overlap_rejected(app):
    with app.app_context():
        c = get_db()
        a = c.execute("SELECT * FROM slots ORDER BY id LIMIT 1").fetchone()
        c.execute("INSERT INTO slots (class_type_id, trainer_id, starts_at, ends_at, capacity)"
                  " VALUES (1, ?, ?, ?, 5)", (a["trainer_id"], a["starts_at"], a["ends_at"]))
        b = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        u = uid(app, "client@kbtu.kz")
        booking.book(c, u, a["id"])
        with pytest.raises(booking.BookingError, match="в это время"):
            booking.book(c, u, b)


def test_past_and_cancelled_slot_rejected(app):
    sid = slot_ids(app)[0]
    u = uid(app, "client@kbtu.kz")
    with app.app_context():
        c = get_db()
        far = datetime.now() + timedelta(days=30)
        with pytest.raises(booking.BookingError, match="началось"):
            booking.book(c, u, sid, now=far)
        c.execute("UPDATE slots SET status='cancelled' WHERE id=?", (sid,))
        with pytest.raises(booking.BookingError, match="отменено"):
            booking.book(c, u, sid)
        with pytest.raises(booking.BookingError):
            booking.book(c, u, 99999)


def test_late_cancel_rejected(app):
    sid, u = slot_ids(app)[0], uid(app, "client@kbtu.kz")
    with app.app_context():
        c = get_db()
        booking.book(c, u, sid)
        starts = datetime.strptime(
            c.execute("SELECT starts_at FROM slots WHERE id=?", (sid,)).fetchone()[0], booking.FMT)
        with pytest.raises(booking.BookingError, match="2 часа"):
            booking.cancel(c, u, sid, now=starts - timedelta(minutes=30))


def test_failed_booking_leaves_no_open_transaction(app):
    with app.app_context():
        c = get_db()
        with pytest.raises(booking.BookingError):
            booking.book(c, 1, 99999)
        assert not c.in_transaction


# --- БД: ограничения
def test_db_constraints(app):
    import sqlite3
    with app.app_context():
        c = get_db()
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO slots (class_type_id, trainer_id, starts_at, ends_at, capacity)"
                      " VALUES (1, 2, '2030-01-01 10:00', '2030-01-01 11:00', 0)")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO bookings (user_id, slot_id) VALUES (999, 1)")
        c.execute("INSERT INTO bookings (user_id, slot_id) VALUES (3, 1)")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO bookings (user_id, slot_id) VALUES (3, 1)")


# --- админ и тренер (FR-11..FR-13)
def test_admin_creates_and_cancels_slot(client, app):
    login(client, "admin@kbtu.kz", "Admin12345")
    day = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
    form = {"class_type_id": 1, "trainer_id": uid(app, "trainer@kbtu.kz"),
            "hall_id": hall_id(app, "Студия йоги"), "date": day, "time": "10:00"}
    client.post("/admin/slots", data=form)
    with app.app_context():
        row = get_db().execute("SELECT * FROM slots WHERE starts_at = ?", (f"{day} 10:00",)).fetchone()
        assert row and row["ends_at"] == f"{day} 11:00" and row["capacity"] == 12
    client.post("/admin/slots", data={**form, "time": "10:30"})  # пересечение у тренера
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM slots WHERE starts_at LIKE ?", (f"{day}%",)).fetchone()[0] == 1
    client.post(f"/admin/slots/{row['id']}/cancel")
    with app.app_context():
        assert get_db().execute("SELECT status FROM slots WHERE id=?", (row["id"],)).fetchone()[0] == "cancelled"


def test_trainer_sees_attendees(client, app):
    with app.app_context():
        sid = get_db().execute(
            "SELECT id FROM slots WHERE trainer_id = ? ORDER BY starts_at LIMIT 1",
            (uid(app, "trainer@kbtu.kz"),)).fetchone()[0]
        booking.book(get_db(), uid(app, "client@kbtu.kz"), sid)
    login(client, "trainer@kbtu.kz", "Trainer12345")
    assert "client@kbtu.kz" in client.get("/trainer").get_data(as_text=True)


# --- залы, тренеры, разнообразие расписания
def test_seed_has_halls_trainers_and_variety(app):
    with app.app_context():
        c = get_db()
        assert c.execute("SELECT COUNT(*) FROM halls").fetchone()[0] >= 5
        assert c.execute("SELECT COUNT(*) FROM users WHERE role='trainer'").fetchone()[0] >= 5
        assert c.execute("SELECT COUNT(DISTINCT class_type_id) FROM slots").fetchone()[0] >= 8
        assert c.execute("SELECT COUNT(DISTINCT substr(starts_at, 12)) FROM slots").fetchone()[0] >= 10
        assert c.execute("SELECT COUNT(*) FROM slots WHERE hall_id IS NULL").fetchone()[0] == 0


def test_seed_has_no_overlaps_for_trainer_or_hall(app):
    with app.app_context():
        c = get_db()
        for col in ("trainer_id", "hall_id"):
            clash = c.execute(
                f"""SELECT 1 FROM slots a JOIN slots b
                    ON a.{col} = b.{col} AND a.id < b.id
                   AND a.starts_at < b.ends_at AND a.ends_at > b.starts_at LIMIT 1""").fetchone()
            assert clash is None, col


def test_seed_extend_is_idempotent(app):
    import seed
    with app.app_context():
        c = get_db()
        before = c.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
        seed.seed(c)
        assert c.execute("SELECT COUNT(*) FROM slots").fetchone()[0] == before


def test_filter_by_hall(as_client, app):
    hid = hall_id(app, "Зал единоборств")
    html = as_client.get(f"/?hall={hid}").get_data(as_text=True)
    assert "<b>Бокс</b>" in html and "<b>Йога</b>" not in html


def test_admin_cannot_double_book_hall(client, app):
    login(client, "admin@kbtu.kz", "Admin12345")
    day = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
    hid = hall_id(app, "Студия йоги")
    form = {"class_type_id": 1, "trainer_id": uid(app, "trainer@kbtu.kz"),
            "hall_id": hid, "date": day, "time": "10:00"}
    client.post("/admin/slots", data=form)
    # другой тренер, тот же зал и время: отказ
    client.post("/admin/slots", data={**form, "trainer_id": uid(app, "trainer2@kbtu.kz")})
    # другой тренер, другой зал: можно
    client.post("/admin/slots", data={**form, "trainer_id": uid(app, "trainer2@kbtu.kz"),
                                      "hall_id": hall_id(app, "Зал групповых программ")})
    with app.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM slots WHERE starts_at = ?", (f"{day} 10:00",)).fetchone()[0] == 2


def test_old_db_gets_hall_column(tmp_path):
    import sqlite3
    from app import create_app
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE,
            password_hash TEXT, role TEXT DEFAULT 'client', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE class_types (id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT DEFAULT '',
            duration_min INTEGER, default_capacity INTEGER);
        CREATE TABLE slots (id INTEGER PRIMARY KEY, class_type_id INTEGER, trainer_id INTEGER,
            starts_at TEXT, ends_at TEXT, capacity INTEGER, status TEXT DEFAULT 'active');
    """)
    conn.close()
    app = create_app({"DATABASE": str(path), "TESTING": True, "RATELIMIT_ENABLED": False})
    with app.app_context():
        cols = [r[1] for r in get_db().execute("PRAGMA table_info(slots)")]
        assert "hall_id" in cols


def test_trainer_sees_only_own_slots(client, app):
    login(client, "trainer@kbtu.kz", "Trainer12345")
    html = client.get("/trainer").get_data(as_text=True)
    assert "Тренер Алия" in html and "Тренер Ерлан" not in html


# --- вкладки по дням и прошедшие занятия
def test_schedule_has_seven_day_tabs(as_client):
    html = as_client.get("/").get_data(as_text=True)
    assert html.count('<a class="daytab') == 7
    assert "сегодня" in html


def test_day_tab_shows_only_that_day(as_client):
    day = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    html = as_client.get(f"/?day={day}").get_data(as_text=True)
    assert "Записаться" in html
    assert day[8:10] in html


def test_past_slot_visible_but_cannot_be_booked(as_client, app):
    past = (datetime.now() - timedelta(hours=3)).strftime(booking.FMT)
    end = (datetime.now() - timedelta(hours=2)).strftime(booking.FMT)
    with app.app_context():
        c = get_db()
        trainer = uid(app, "trainer@kbtu.kz")
        c.execute("INSERT INTO slots (class_type_id, trainer_id, starts_at, ends_at, capacity)"
                  " VALUES (1, ?, ?, ?, 5)", (trainer, past, end))
        sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    html = as_client.get(f"/?day={past[:10]}").get_data(as_text=True)
    assert "Занятие прошло" in html
    assert f"/book/{sid}" not in html          # кнопки записи нет
    as_client.post(f"/book/{sid}")              # прямой POST всё равно отклоняется
    with app.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM bookings WHERE slot_id = ?", (sid,)).fetchone()[0] == 0


def test_profile_page_client(as_client):
    r = as_client.get("/profile")
    assert r.status_code == 200
    assert "Достижения" in r.get_data(as_text=True)


@pytest.mark.parametrize("email,pwd,marker", [
    ("trainer@kbtu.kz", "Trainer12345", "Твоя специализация"),
    ("admin@kbtu.kz", "Admin12345", "Пульс зала"),
])
def test_profile_page_staff(client, email, pwd, marker):
    login(client, email, pwd)
    r = client.get("/profile")
    assert r.status_code == 200 and marker in r.get_data(as_text=True)


def test_profile_requires_login(client):
    assert client.get("/profile").status_code == 302


def test_profile_counts_attended_classes(app):
    from datetime import datetime, timedelta
    import userpage
    with app.app_context():
        conn = get_db()
        uid = conn.execute("SELECT id FROM users WHERE email='client@kbtu.kz'").fetchone()[0]
        sid = conn.execute("SELECT id FROM slots LIMIT 1").fetchone()[0]
        start = datetime.now() - timedelta(days=1)
        conn.execute("UPDATE slots SET starts_at=?, ends_at=? WHERE id=?",
                     (start.strftime("%Y-%m-%d %H:%M"),
                      (start + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M"), sid))
        conn.execute("INSERT INTO bookings (user_id, slot_id) VALUES (?, ?)", (uid, sid))
        s = userpage.client_stats(conn, uid)
        assert s["count"] == 1 and s["minutes"] == 60 and s["streak"] == 1
        assert s["level"]["n"] == 1 and s["ach_got"] >= 1
