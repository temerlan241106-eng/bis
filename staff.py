from datetime import datetime, timedelta

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

import booking
from db import get_db
from roles import roles_required

bp = Blueprint("staff", __name__)


def slots_with_people(where="", params=()):
    conn = get_db()
    slots = conn.execute(
        f"""SELECT s.id, s.starts_at, s.capacity, s.status, ct.name AS class_name,
                   u.name AS trainer_name, h.name AS hall_name
            FROM slots s JOIN class_types ct ON ct.id = s.class_type_id
            JOIN users u ON u.id = s.trainer_id
            LEFT JOIN halls h ON h.id = s.hall_id
            WHERE s.starts_at > ? {where} ORDER BY s.starts_at""",
        (booking.now_str(), *params),
    ).fetchall()
    out = []
    for s in slots:
        people = conn.execute(
            """SELECT u.name, u.email FROM bookings b JOIN users u ON u.id = b.user_id
               WHERE b.slot_id = ? AND b.status = 'booked' ORDER BY u.name""",
            (s["id"],),
        ).fetchall()
        out.append({**dict(s), "people": people})
    return out


@bp.route("/trainer")
@roles_required("trainer")
def trainer():
    return render_template(
        "staff_slots.html", title="Мои занятия",
        slots=slots_with_people("AND s.trainer_id = ?", (g.user["id"],)),
        admin=False,
    )


@bp.route("/admin")
@roles_required("admin")
def admin():
    conn = get_db()
    return render_template(
        "staff_slots.html", title="Управление расписанием",
        slots=slots_with_people(), admin=True,
        types=conn.execute("SELECT * FROM class_types ORDER BY name").fetchall(),
        trainers=conn.execute(
            "SELECT id, name FROM users WHERE role = 'trainer' ORDER BY name"
        ).fetchall(),
        halls=conn.execute("SELECT id, name FROM halls ORDER BY name").fetchall(),
    )


@bp.route("/admin/slots", methods=("POST",))
@roles_required("admin")
def create_slot():
    conn = get_db()
    try:
        type_id = int(request.form.get("class_type_id", ""))
        trainer_id = int(request.form.get("trainer_id", ""))
        hall_id = int(request.form.get("hall_id", ""))
        start = datetime.strptime(
            f"{request.form.get('date', '')} {request.form.get('time', '')}", booking.FMT
        )
        ct = conn.execute("SELECT * FROM class_types WHERE id = ?", (type_id,)).fetchone()
        trainer = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'trainer'", (trainer_id,)
        ).fetchone()
        hall = conn.execute("SELECT id FROM halls WHERE id = ?", (hall_id,)).fetchone()
        raw_cap = request.form.get("capacity", "").strip()
        capacity = int(raw_cap) if raw_cap else (ct["default_capacity"] if ct else 0)
    except (ValueError, TypeError):
        flash("Проверьте поля формы.", "error")
        return redirect(url_for("staff.admin"))

    end = start + timedelta(minutes=ct["duration_min"]) if ct else None
    if ct is None or trainer is None or hall is None or not 0 < capacity <= 200:
        flash("Проверьте тип занятия, тренера, зал и вместимость.", "error")
    elif start <= datetime.now():
        flash("Нельзя создать занятие в прошлом.", "error")
    elif conn.execute(
        """SELECT 1 FROM slots WHERE trainer_id = ? AND status = 'active'
           AND starts_at < ? AND ends_at > ?""",
        (trainer_id, end.strftime(booking.FMT), start.strftime(booking.FMT)),
    ).fetchone():
        flash("У тренера уже есть занятие в это время.", "error")
    elif conn.execute(
        """SELECT 1 FROM slots WHERE hall_id = ? AND status = 'active'
           AND starts_at < ? AND ends_at > ?""",
        (hall_id, end.strftime(booking.FMT), start.strftime(booking.FMT)),
    ).fetchone():
        flash("Этот зал уже занят в это время.", "error")
    else:
        conn.execute(
            "INSERT INTO slots (class_type_id, trainer_id, hall_id, starts_at, ends_at, capacity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (type_id, trainer_id, hall_id, start.strftime(booking.FMT),
             end.strftime(booking.FMT), capacity),
        )
        flash("Занятие создано.", "success")
    return redirect(url_for("staff.admin"))


@bp.route("/admin/slots/<int:slot_id>/cancel", methods=("POST",))
@roles_required("admin")
def cancel_slot(slot_id):
    get_db().execute("UPDATE slots SET status = 'cancelled' WHERE id = ?", (slot_id,))
    flash("Занятие отменено.", "success")
    return redirect(url_for("staff.admin"))
