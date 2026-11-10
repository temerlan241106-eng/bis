from datetime import date, datetime, timedelta

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

import booking
from auth import login_required
from db import get_db
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
    # выбранный день; по умолчанию — ближайший день (начиная с сегодня), где есть занятия
    day = parse_day(request.args.get("day"))
    if day is None:
        first = conn.execute(
            "SELECT substr(MIN(starts_at), 1, 10) FROM slots "
            "WHERE status = 'active' AND substr(starts_at, 1, 10) >= ?",
            (today.isoformat(),),
        ).fetchone()[0]
        day = parse_day(first) or today

    where = ["s.status = 'active'", "substr(s.starts_at, 1, 10) = :day"]
    params = {"uid": g.user["id"], "day": day.isoformat()}
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
    now = booking.now_str()
    slots = [dict(r) for r in conn.execute(sql, params)]
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

    return render_template(
        "schedule.html",
        slots=slots,
        tabs=tabs,
        day=day,
        day_label=f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d.%m.%Y')}",
        types=conn.execute("SELECT id, name FROM class_types ORDER BY name").fetchall(),
        trainers=conn.execute(
            "SELECT id, name FROM users WHERE role = 'trainer' ORDER BY name"
        ).fetchall(),
        halls=conn.execute("SELECT id, name FROM halls ORDER BY name").fetchall(),
        f={"type": type_id, "trainer": trainer_id, "hall": hall_id,
           "day": day.isoformat(), "free": only_free},
    )


@bp.route("/book/<int:slot_id>", methods=("POST",))
@roles_required("client")
def book(slot_id):
    try:
        booking.book(get_db(), g.user["id"], slot_id)
        flash("Вы записаны на занятие.", "success")
    except booking.BookingError as e:
        flash(str(e), "error")
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
