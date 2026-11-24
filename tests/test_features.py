"""Подписка Premium, лимит Free, подтверждение почты, сундук, стиль профиля, клиент Turso."""
import re
from datetime import datetime, timedelta

import pytest

import booking
import game
import mailer
import plans
import premium
from conftest import login
from db import get_db


def uid(app, email):
    with app.app_context():
        return get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def week_slots(app, n):
    """n непересекающихся занятий в одной неделе (неделя следующего понедельника)."""
    with app.app_context():
        c = get_db()
        mon = datetime.now().date() + timedelta(days=7 - datetime.now().weekday())
        rows = c.execute("SELECT id, starts_at, ends_at FROM slots WHERE starts_at >= ? AND starts_at < ? "
                         "ORDER BY starts_at", (mon.isoformat(), (mon + timedelta(days=7)).isoformat())).fetchall()
        out, last_end = [], ""
        for r in rows:
            if r["starts_at"] >= last_end:
                out.append(r["id"])
                last_end = r["ends_at"]
            if len(out) == n:
                return out
    pytest.skip("мало занятий на следующей неделе")


# --- лимит Free и Premium
def test_free_limit_per_week(app):
    ids = week_slots(app, plans.FREE_WEEKLY_LIMIT + 1)
    u = uid(app, "client@kbtu.kz")
    with app.app_context():
        c = get_db()
        for sid in ids[:-1]:
            booking.book(c, u, sid)
        with pytest.raises(booking.BookingError, match="Лимит Free"):
            booking.book(c, u, ids[-1])


def test_premium_has_no_limit(app):
    ids = week_slots(app, plans.FREE_WEEKLY_LIMIT + 1)
    u = uid(app, "client@kbtu.kz")
    with app.app_context():
        c = get_db()
        premium.activate(c, u, "month", "4242")
        for sid in ids:
            booking.book(c, u, sid)
        assert plans.is_premium(c, u)


def test_premium_extension_stacks(app):
    u = uid(app, "client@kbtu.kz")
    with app.app_context():
        c = get_db()
        premium.activate(c, u, "month", "4242")
        premium.activate(c, u, "quarter", "4242")
        until = plans.active_until(plans.periods(c, u))
        days = (datetime.strptime(until, plans.FMT) - datetime.now()).days
        assert 118 <= days <= 120  # 30 + 90 дней подряд


def test_premium_xp_multiplier():
    rows = [{"starts_at": "2026-01-05 10:00", "ends_at": "2026-01-05 11:00", "class_name": "Йога",
             "trainer_name": "T", "hall_name": "H"}]
    import userpage
    now = datetime(2026, 1, 10)
    free = userpage.stats_from_rows(rows, now)["xp"]
    prem = userpage.stats_from_rows(rows, now, [("2026-01-01 00:00", "2026-02-01 00:00")])["xp"]
    assert prem - free == 5  # 10 XP -> 15 XP


# --- оплата
@pytest.mark.parametrize("number,ok", [
    ("4242 4242 4242 4242", True), ("4242 4242 4242 4241", False), ("4000 0000 0000 0002", False), ("12", False)])
def test_card_validation(number, ok):
    err, last4 = premium.validate_card({"number": number, "holder": "A", "exp": "12/39", "cvc": "123"})
    assert (err is None) == ok
    if ok:
        assert last4 == "4242"


def test_card_expired():
    err, _ = premium.validate_card({"number": "4242424242424242", "holder": "A", "exp": "01/20", "cvc": "123"})
    assert "истёк" in err


def test_checkout_flow(as_client, app):
    r = as_client.post("/premium/checkout/year", data={
        "method": "card", "number": "4242 4242 4242 4242", "holder": "Test", "exp": "12/39", "cvc": "123"})
    assert r.status_code == 302 and "/premium/success/" in r.headers["Location"]
    with app.app_context():
        row = get_db().execute("SELECT * FROM subscriptions").fetchone()
        assert row["plan"] == "year" and row["price"] == plans.PLANS["year"][2] and row["card_last4"] == "4242"
    assert "Premium" in as_client.get(r.headers["Location"]).get_data(as_text=True)


def test_checkout_never_stores_full_card(as_client, app):
    as_client.post("/premium/checkout/month", data={
        "method": "card", "number": "4242424242424242", "holder": "Test", "exp": "12/39", "cvc": "123"})
    with app.app_context():
        dump = "\n".join(get_db().iterdump())
    assert "4242424242424242" not in dump


# --- регистрация с кодом из письма
def _code():
    return re.search(r"\b(\d{6})\b", mailer.outbox[-1]["text"]).group(1)


def _register(client, email="neo@kbtu.kz"):
    mailer.outbox.clear()
    return client.post("/register", data={"name": "Neo", "email": email,
                                          "password": "12345678", "confirm": "12345678"})


def test_account_created_only_after_code(client, app):
    _register(client)
    assert mailer.outbox and mailer.outbox[-1]["to"] == "neo@kbtu.kz"
    with app.app_context():
        assert get_db().execute("SELECT 1 FROM users WHERE email='neo@kbtu.kz'").fetchone() is None
    assert login(client, "neo@kbtu.kz", "12345678").status_code == 200  # входа ещё нет
    r = client.post("/register/confirm", data={"code": _code()})
    assert r.status_code == 302
    with app.app_context():
        c = get_db()
        u = c.execute("SELECT id, email_verified FROM users WHERE email='neo@kbtu.kz'").fetchone()
        assert u["email_verified"] == 1
        assert c.execute("SELECT amount FROM bonus_xp WHERE kind='verify' AND user_id=?", (u["id"],)).fetchone()[0] == game.VERIFY_BONUS
        assert c.execute("SELECT COUNT(*) FROM signup_codes").fetchone()[0] == 0
        sid = c.execute("SELECT id FROM slots ORDER BY starts_at LIMIT 1").fetchone()[0]
    client.post(f"/book/{sid}")  # сразу после кода пользователь залогинен и может записаться
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1


def test_wrong_code_attempts_limited(client, app):
    _register(client)
    good = _code()
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        client.post("/register/confirm", data={"code": bad})
    html = client.post("/register/confirm", data={"code": good}).get_data(as_text=True)
    assert "Слишком много попыток" in html
    with app.app_context():
        assert get_db().execute("SELECT 1 FROM users WHERE email='neo@kbtu.kz'").fetchone() is None


def test_expired_code_rejected(client, app):
    _register(client)
    with app.app_context():
        get_db().execute("UPDATE signup_codes SET expires_at = '2000-01-01 00:00:00'")
    html = client.post("/register/confirm", data={"code": _code()}).get_data(as_text=True)
    assert "устарел" in html


def test_resend_cooldown_and_new_code(client, app):
    _register(client)
    client.post("/register/resend")
    assert len(mailer.outbox) == 1  # раньше минуты не отправляем
    with app.app_context():
        get_db().execute("UPDATE signup_codes SET sent_at = '2000-01-01 00:00:00'")
    client.post("/register/resend")
    assert len(mailer.outbox) == 2
    old = re.search(r"\b(\d{6})\b", mailer.outbox[0]["text"]).group(1)
    new = _code()
    if old != new:
        client.post("/register/confirm", data={"code": old})
        with app.app_context():
            assert get_db().execute("SELECT 1 FROM users WHERE email='neo@kbtu.kz'").fetchone() is None
    client.post("/register/confirm", data={"code": new})
    with app.app_context():
        assert get_db().execute("SELECT email_verified FROM users WHERE email='neo@kbtu.kz'").fetchone()[0] == 1


def test_existing_email_cannot_register(client):
    html = _register(client, "client@kbtu.kz").get_data(as_text=True)
    assert "уже существует" in html and not mailer.outbox


def test_legacy_unverified_user_must_enter_code(client, app):
    from werkzeug.security import generate_password_hash
    with app.app_context():
        get_db().execute("INSERT INTO users (name, email, password_hash) VALUES ('Old', 'old@kbtu.kz', ?)",
                         (generate_password_hash("12345678"),))
    mailer.outbox.clear()
    r = login(client, "old@kbtu.kz", "12345678")
    assert r.headers["Location"].endswith("/register/confirm")
    assert client.get("/profile").status_code == 302  # не залогинен
    client.post("/register/confirm", data={"code": _code()})
    assert client.get("/profile").status_code == 200


# --- сундук и стиль
def test_chest_once_per_day_for_free(as_client):
    r = as_client.post("/chest")
    assert r.status_code == 200 and r.get_json()["ok"] and r.get_json()["xp"] > 0
    assert as_client.post("/chest").status_code == 400


def test_chest_twice_for_premium(as_client, app):
    with app.app_context():
        premium.activate(get_db(), uid(app, "client@kbtu.kz"), "month", "4242")
    assert as_client.post("/chest").status_code == 200
    assert as_client.post("/chest").status_code == 200
    assert as_client.post("/chest").status_code == 400


def test_locked_frame_rejected(as_client, app):
    as_client.post("/profile/style", data={"frame": "gold", "title": ""})
    with app.app_context():
        assert get_db().execute("SELECT frame FROM users WHERE email='client@kbtu.kz'").fetchone()[0] is None
    as_client.post("/profile/style", data={"frame": "none", "title": "rookie"})
    with app.app_context():
        assert get_db().execute("SELECT title FROM users WHERE email='client@kbtu.kz'").fetchone()[0] == "rookie"


def test_pages_render(as_client):
    for url in ("/", "/my", "/profile", "/leaderboard", "/premium", "/premium/checkout/quarter"):
        assert as_client.get(url).status_code == 200, url


# --- клиент Turso на фейковом сервере (эмуляция протокола поверх sqlite3)
class FakeTurso:
    def __init__(self, path):
        import sqlite3
        self.sqlite3, self.path, self.streams, self.n = sqlite3, path, {}, 0

    def post(self, url, headers=None, timeout=None, json=None):
        baton = json.get("baton")
        conn = self.streams.pop(baton, None) if baton else None
        if conn is None:
            conn = self.sqlite3.connect(self.path, isolation_level=None)
            conn.execute("PRAGMA foreign_keys = ON")
        results, closed = [], False
        for req in json["requests"]:
            if req["type"] == "close":
                closed = True
                continue
            st = req["stmt"]
            dec = lambda v: None if v["type"] == "null" else int(v["value"]) if v["type"] == "integer" else v.get("value")
            args = {a["name"][1:]: dec(a["value"]) for a in st["named_args"]} if "named_args" in st else \
                [dec(a) for a in st.get("args", [])]
            try:
                cur = conn.execute(st["sql"], args)
                rows = cur.fetchall()
                enc = lambda v: {"type": "null"} if v is None else {"type": "integer", "value": str(v)} \
                    if isinstance(v, int) else {"type": "float", "value": v} if isinstance(v, float) \
                    else {"type": "text", "value": v}
                results.append({"type": "ok", "response": {"type": "execute", "result": {
                    "cols": [{"name": d[0]} for d in (cur.description or [])],
                    "rows": [[enc(v) for v in r] for r in rows],
                    "affected_row_count": cur.rowcount, "last_insert_rowid": str(cur.lastrowid)}}})
            except self.sqlite3.IntegrityError as e:
                results.append({"type": "error", "error": {"message": str(e), "code": "SQLITE_CONSTRAINT"}})
            except self.sqlite3.Error as e:
                results.append({"type": "error", "error": {"message": str(e)}})
        new_baton = None
        if not closed:
            self.n += 1
            new_baton = f"b{self.n}"
            self.streams[new_baton] = conn
        else:
            conn.close()

        class R:
            status_code = 200
            text = ""

            def json(self_inner):
                return {"baton": new_baton, "base_url": None, "results": results}
        return R()


def test_turso_client_runs_booking(tmp_path, monkeypatch):
    import seed
    import turso
    from app import create_app
    fake = FakeTurso(str(tmp_path / "remote.db"))
    monkeypatch.setattr(turso, "_session", fake)
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "RATELIMIT_ENABLED": False,
                      "TURSO_DATABASE_URL": "libsql://fake.turso.io", "TURSO_AUTH_TOKEN": "t"})
    with app.app_context():
        c = get_db()
        assert isinstance(c, turso.Connection)
        seed.seed_if_empty(c)
        u = c.execute("SELECT id, name FROM users WHERE email = ?", ("client@kbtu.kz",)).fetchone()
        assert u["name"] == "Клиент Данияр" and dict(u)["id"] == u[0]
        sid = c.execute("SELECT id FROM slots ORDER BY starts_at LIMIT 1").fetchone()[0]
        booking.book(c, u["id"], sid)
        assert not c.in_transaction
        with pytest.raises(booking.BookingError, match="уже записаны"):
            booking.book(c, u["id"], sid)
        assert not c.in_transaction
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO bookings (user_id, slot_id) VALUES (?, ?)", (u["id"], sid))
    login(app.test_client(), "client@kbtu.kz", "Client12345")
