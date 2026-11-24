"""Демо-студенты с историей посещений — чтобы профиль, квесты и рейтинг выглядели «живыми».

  python demo_data.py            — добавить демо-студентов (если их ещё нет)
  python demo_data.py --reset    — удалить демо-студентов и создать заново от сегодняшней даты

Пароль у всех демо-студентов: Student12345. В тесты не входит (seed.py их не создаёт).
"""
import random
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

import booking
from seed import CLASS_HALL, TRAINER_SKILLS

PASSWORD = "Student12345"

# (имя, email, занятия, часы начала (от, до), занятий в неделю, сколько недель назад начал, пропускаемые недели назад)
STUDENTS = [
    ("Айгерим Сейтова", "aigerim.seitova@kbtu.kz", ["Йога", "Пилатес", "Стретчинг", "Кардио"], (7, 11), (3, 4), 8, set()),
    ("Мадияр Ержанов", "madiyar.erzhanov@kbtu.kz", ["Кроссфит", "HIIT", "Силовая тренировка", "Бокс"], (17, 21), (3, 4), 7, {5}),
    ("Алия Нурпеисова", "aliya.nurpeisova@kbtu.kz", ["Зумба", "Пилатес", "Кардио", "Йога", "Стретчинг"], (10, 20), (2, 2), 8, set()),
    ("Тимур Беков", "timur.bekov@kbtu.kz", ["Бокс", "Силовая тренировка", "Кроссфит"], (16, 21), (2, 3), 4, set()),
    ("Дана Ким", "dana.kim@kbtu.kz", ["Зумба", "Кардио"], (10, 20), (1, 2), 8, {1, 2, 4, 5}),
    ("Арсен Жумабеков", "arsen.zhumabekov@kbtu.kz", ["Кардио", "HIIT", "Силовая тренировка"], (8, 20), (2, 3), 1, set()),
]
# готовый тестовый клиент тоже получает небольшую историю
CLIENT = ("client@kbtu.kz", ["Йога", "Кардио", "Силовая тренировка"], (8, 19), (1, 2), 2, set())

# время начала занятий берём из ежедневного шаблона, чтобы всё выглядело как настоящее расписание
from seed import DAY_PLAN  # noqa: E402


def _fmt(dt):
    return dt.strftime(booking.FMT)


def _slot_for(conn, rnd, types, class_name, day, hours):
    """Находит или создаёт занятие в прошлом (как в шаблоне расписания)."""
    options = [(h, m) for h, m, c in DAY_PLAN if c == class_name and hours[0] <= h < hours[1]]
    if not options:
        options = [(h, m) for h, m, c in DAY_PLAN if c == class_name]
    h, m = rnd.choice(options)
    start = datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)
    ct = types[class_name]
    end = start + timedelta(minutes=ct["duration_min"])
    row = conn.execute("SELECT id FROM slots WHERE class_type_id = ? AND starts_at = ? AND status = 'active'",
                       (ct["id"], _fmt(start))).fetchone()
    if row:
        return row["id"], start
    hall = conn.execute("SELECT id FROM halls WHERE name = ?", (CLASS_HALL[class_name],)).fetchone()["id"]
    pool = [r["id"] for r in conn.execute("SELECT id, email FROM users WHERE role = 'trainer'")
            if class_name in TRAINER_SKILLS.get(
                conn.execute("SELECT email FROM users WHERE id = ?", (r["id"],)).fetchone()["email"], [])]
    rnd.shuffle(pool)
    trainer = next((t for t in pool if not conn.execute(
        "SELECT 1 FROM slots WHERE trainer_id = ? AND status = 'active' AND starts_at < ? AND ends_at > ?",
        (t, _fmt(end), _fmt(start))).fetchone()), pool[0])
    cur = conn.execute(
        "INSERT INTO slots (class_type_id, trainer_id, hall_id, starts_at, ends_at, capacity) VALUES (?,?,?,?,?,?)",
        (ct["id"], trainer, hall, _fmt(start), _fmt(end), ct["default_capacity"]))
    return cur.lastrowid, start


def _history(conn, rnd, types, uid, classes, hours, per_week, weeks_back, skip):
    today = date.today()
    cur_mon = today - timedelta(days=today.weekday())
    for w in range(weeks_back):
        if w in skip:
            continue
        mon = cur_mon - timedelta(days=7 * w)
        days = [mon + timedelta(days=i) for i in range(7) if mon + timedelta(days=i) < today]
        if not days:
            continue
        for day in rnd.sample(days, min(rnd.randint(*per_week), len(days))):
            sid, start = _slot_for(conn, rnd, types, rnd.choice(classes), day, hours)
            if conn.execute("SELECT 1 FROM bookings WHERE user_id = ? AND slot_id = ?", (uid, sid)).fetchone():
                continue
            clash = conn.execute(
                """SELECT 1 FROM bookings b JOIN slots s ON s.id = b.slot_id
                   WHERE b.user_id = ? AND s.starts_at < (SELECT ends_at FROM slots WHERE id = ?)
                     AND s.ends_at > (SELECT starts_at FROM slots WHERE id = ?)""", (uid, sid, sid)).fetchone()
            if clash:
                continue
            conn.execute("INSERT INTO bookings (user_id, slot_id, status, created_at) VALUES (?,?,'booked',?)",
                         (uid, sid, _fmt(start - timedelta(days=1))))


def _upcoming(conn, rnd, uid, classes, n):
    rows = conn.execute(
        """SELECT s.id FROM slots s JOIN class_types ct ON ct.id = s.class_type_id
           WHERE s.status = 'active' AND s.starts_at > ? AND ct.name IN (%s) ORDER BY s.starts_at"""
        % ",".join("?" * len(classes)), (booking.now_str(), *classes)).fetchall()
    rnd.shuffle(rows)
    done = 0
    for r in rows:
        if done >= n:
            break
        try:
            booking.book(conn, uid, r["id"])
            done += 1
        except booking.BookingError:
            pass  # пересечение или нет мест — берём следующее


def reset(conn):
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM users WHERE email IN (%s)" % ",".join("?" * len(STUDENTS)), [s[1] for s in STUDENTS])]
    for uid in ids:
        conn.execute("DELETE FROM bookings WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM bonus_xp WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    cid = conn.execute("SELECT id FROM users WHERE email = ?", (CLIENT[0],)).fetchone()
    if cid:
        conn.execute("DELETE FROM bookings WHERE user_id = ?", (cid["id"],))
    # пустые занятия из прошлого, созданные для истории
    conn.execute("DELETE FROM slots WHERE starts_at <= ? AND id NOT IN (SELECT slot_id FROM bookings)",
                 (booking.now_str(),))


def add_demo(conn, seed_value=2026):
    """Идемпотентно добавляет демо-студентов. Возвращает число созданных."""
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (STUDENTS[0][1],)).fetchone():
        return 0
    rnd = random.Random(seed_value)
    types = {r["name"]: r for r in conn.execute("SELECT * FROM class_types")}
    pwd = generate_password_hash(PASSWORD)
    # создаём «раньше» в аккаунтах, чтобы «с нами с …» выглядело правдоподобно
    for name, email, classes, hours, per_week, weeks_back, skip in STUDENTS:
        since = _fmt(datetime.now() - timedelta(days=7 * weeks_back + 3))
        conn.execute("INSERT INTO users (name, email, password_hash, role, created_at, email_verified) "
                     "VALUES (?,?,?,'client',?,1)",
                     (name, email, pwd, since))
        uid = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
        _history(conn, rnd, types, uid, classes, hours, per_week, weeks_back, skip)
        _upcoming(conn, rnd, uid, classes, rnd.randint(1, 3))
    # первой демо-студентке — Premium на 3 месяца (начался 3 недели назад), для показа
    aid = conn.execute("SELECT id FROM users WHERE email = ?", (STUDENTS[0][1],)).fetchone()["id"]
    start = datetime.now() - timedelta(weeks=3)
    conn.execute("INSERT INTO subscriptions (user_id, plan, price, starts_at, ends_at, card_last4) "
                 "VALUES (?, 'quarter', 7990, ?, ?, '4242')",
                 (aid, _fmt(start), _fmt(start + timedelta(days=90))))
    email, classes, hours, per_week, weeks_back, skip = CLIENT
    cid = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if cid and not conn.execute("SELECT 1 FROM bookings WHERE user_id = ?", (cid["id"],)).fetchone():
        _history(conn, rnd, types, cid["id"], classes, hours, per_week, weeks_back, skip)
        _upcoming(conn, rnd, cid["id"], classes, 2)
    return len(STUDENTS)


if __name__ == "__main__":
    from app import app
    from db import get_db
    with app.app_context():
        conn = get_db()
        if "--reset" in sys.argv:
            reset(conn)
        n = add_demo(conn)
        print(f"Добавлено демо-студентов: {n}" if n else "Демо-студенты уже есть (для пересоздания: --reset)")
