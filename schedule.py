from datetime import date, datetime, timedelta

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

import booking
from auth import login_required, verified_required
from db import batch, get_db
from roles import roles_required

bp = Blueprint("schedule", __name__)

SLOT_SQL = """
SELECT s.id, s.starts_at, s.ends_at, s.capacity, s.status,
       ct.name AS class_name, ct.description, u.name AS trainer_name,
       h.name AS hall_name,
       (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status = 'booked') AS taken,
       (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.user_id = :uid
                                           AND b.status = 'booked') AS mine
FROM slots s
JOIN class_types ct ON ct.id = s.class_type_id
JOIN users u ON u.id = s.trainer_id
LEFT JOIN halls h ON h.id = s.hall_id
"""


def parse_day(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
TAB_DAYS = 7


def render_schedule():
    conn = get_db()
    type_id = request.args.get("type", type=int)
    trainer_id = request.args.get("trainer", type=int)
    hall_id = request.args.get("hall", type=int)
    only_free = request.args.get("free") == "1"
    today = date.today()
    # выбранный день; по умолчанию — ближайший день (начиная с сегодня), где есть занятия.
    # Всё (день, занятия, справочники) — одним обращением к базе: для облачной Turso это важно.
    day = parse_day(request.args.get("day"))
    first_sql = ("SELECT COALESCE((SELECT substr(MIN(starts_at), 1, 10) FROM slots "
                 "WHERE status = 'active' AND substr(starts_at, 1, 10) >= :today), :today)")
    where = ["s.status = 'active'", "substr(s.starts_at, 1, 10) = " + (":day" if day else f"({first_sql})")]
    params = {"uid": g.user["id"], "today": today.isoformat()}
    if day:
        params["day"] = day.isoformat()
    if type_id:
        where.append("s.class_type_id = :type")
        params["type"] = type_id
    if trainer_id:
        where.append("s.trainer_id = :trainer")
        params["trainer"] = trainer_id
    if hall_id:
        where.append("s.hall_id = :hall")
        params["hall"] = hall_id

    sql = SLOT_SQL + " WHERE " + " AND ".join(where) + " ORDER BY s.starts_at"
    first, slot_rows, types, trainers, halls = batch(conn, [
        (first_sql, {"today": today.isoformat()}),
        (sql, params),
        ("SELECT id, name FROM class_types ORDER BY name", ()),
        ("SELECT id, name FROM users WHERE role = 'trainer' ORDER BY name", ()),
        ("SELECT id, name FROM halls ORDER BY name", ()),
    ])
    if day is None:
        day = parse_day(first.fetchone()[0]) or today

    now = booking.now_str()
    slots = [dict(r) for r in slot_rows.fetchall()]
    for s in slots:
        # то же правило, что и в booking.book: занятие уже началось или прошло
        s["past"] = s["starts_at"] <= now
    if only_free:
        slots = [s for s in slots if s["taken"] < s["capacity"]]

    # вкладки: сегодня + 6 следующих дней; ссылки сохраняют выбранные фильтры
    keep = {k: v for k, v in (("type", type_id), ("trainer", trainer_id),
                              ("hall", hall_id), ("free", "1" if only_free else None)) if v}
    tabs = []
    for i in range(TAB_DAYS):
        d = today + timedelta(days=i)
        tabs.append({
            "date": d.isoformat(),
            "weekday": WEEKDAYS[d.weekday()],
            "num": d.day,
            "today": i == 0,
            "active": d == day,
            "url": url_for("home", day=d.isoformat(), **keep),
        })

    h = None
    if g.user["role"] == "client":
        import game, plans
        h = game.hud()
        mon = day - timedelta(days=day.weekday())
        lo, hi = mon.isoformat(), (mon + timedelta(days=7)).isoformat()
        used = sum(1 for r in h["data"]["stats"]["rows"] if lo <= r["starts_at"] < hi)
        h = {"premium": h["premium"], "limit": plans.FREE_WEEKLY_LIMIT,
             "used": min(used, plans.FREE_WEEKLY_LIMIT),
             "week": f"{mon.strftime('%d.%m')}–{(mon + timedelta(days=6)).strftime('%d.%m')}"}

    return render_template(
        "schedule.html",
        plan=h,
        slots=slots,
        tabs=tabs,
        day=day,
        day_label=f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d.%m.%Y')}",
        types=types.fetchall(),
        trainers=trainers.fetchall(),
        halls=halls.fetchall(),
        f={"type": type_id, "trainer": trainer_id, "hall": hall_id,
           "day": day.isoformat(), "free": only_free},
    )


@bp.route("/book/<int:slot_id>", methods=("POST",))
@roles_required("client")
@verified_required
def book(slot_id):
    try:
        booking.book(get_db(), g.user["id"], slot_id)
        flash("Записан! +10 XP после тренировки 💪", "xp")
    except booking.BookingError as e:
        flash(str(e), "limit" if "Лимит" in str(e) else "error")
    return redirect(request.referrer or url_for("home"))


@bp.route("/cancel/<int:slot_id>", methods=("POST",))
@roles_required("client")
def cancel(slot_id):
    try:
        booking.cancel(get_db(), g.user["id"], slot_id)
        flash("Запись отменена.", "success")
    except booking.BookingError as e:
        flash(str(e), "error")
    return redirect(request.referrer or url_for("schedule.my"))


@bp.route("/my")
@login_required
def my():
    rows = get_db().execute(
        """SELECT s.id, s.starts_at, s.ends_at, s.status AS slot_status,
                  ct.name AS class_name, u.name AS trainer_name,
                  h.name AS hall_name, b.status
           FROM bookings b JOIN slots s ON s.id = b.slot_id
           JOIN class_types ct ON ct.id = s.class_type_id
           JOIN users u ON u.id = s.trainer_id
           LEFT JOIN halls h ON h.id = s.hall_id
           WHERE b.user_id = ? AND b.status = 'booked' AND s.starts_at > ?
           ORDER BY s.starts_at""",
        (g.user["id"], booking.now_str()),
    ).fetchall()
    return render_template("my.html", rows=rows)
