"""Правила записи на занятия. Все проверки и вставка идут в одной транзакции."""
from datetime import datetime, timedelta

FMT = "%Y-%m-%d %H:%M"
CANCEL_BEFORE = timedelta(hours=2)


class BookingError(Exception):
    pass


def now_str(now=None):
    return (now or datetime.now()).strftime(FMT)


def book(conn, user_id, slot_id, now=None):
    conn.execute("BEGIN IMMEDIATE")
    try:
        slot = conn.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)).fetchone()
        # 1. занятие существует и не отменено
        if slot is None or slot["status"] != "active":
            raise BookingError("Занятие не найдено или отменено.")
        # 2. занятие ещё не началось
        if slot["starts_at"] <= now_str(now):
            raise BookingError("Занятие уже началось или прошло.")
        # 3. нет активной записи на это же занятие
        old = conn.execute(
            "SELECT id, status FROM bookings WHERE user_id = ? AND slot_id = ?",
            (user_id, slot_id),
        ).fetchone()
        if old is not None and old["status"] == "booked":
            raise BookingError("Вы уже записаны на это занятие.")
        # 4. нет пересечения по времени с другими записями пользователя
        clash = conn.execute(
            """SELECT 1 FROM bookings b JOIN slots s ON s.id = b.slot_id
               WHERE b.user_id = ? AND b.status = 'booked' AND s.status = 'active'
                 AND s.starts_at < ? AND s.ends_at > ?""",
            (user_id, slot["ends_at"], slot["starts_at"]),
        ).fetchone()
        if clash:
            raise BookingError("У вас уже есть занятие в это время.")
        # 5. есть свободные места
        taken = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE slot_id = ? AND status = 'booked'",
            (slot_id,),
        ).fetchone()[0]
        if taken >= slot["capacity"]:
            raise BookingError("Свободных мест нет.")

        if old is None:
            conn.execute(
                "INSERT INTO bookings (user_id, slot_id) VALUES (?, ?)",
                (user_id, slot_id),
            )
        else:
            conn.execute(
                "UPDATE bookings SET status = 'booked', created_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (old["id"],),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def cancel(conn, user_id, slot_id, now=None):
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """SELECT b.id, s.starts_at FROM bookings b JOIN slots s ON s.id = b.slot_id
               WHERE b.user_id = ? AND b.slot_id = ? AND b.status = 'booked'""",
            (user_id, slot_id),
        ).fetchone()
        if row is None:
            raise BookingError("Запись не найдена.")
        starts = datetime.strptime(row["starts_at"], FMT)
        if starts - (now or datetime.now()) < CANCEL_BEFORE:
            raise BookingError("Отменить можно не позднее чем за 2 часа до начала.")
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (row["id"],))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
