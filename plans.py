"""Тарифы: Free и Premium (1, 3 или 12 месяцев). Подписка хранится в таблице subscriptions."""
from datetime import datetime, timedelta

FMT = "%Y-%m-%d %H:%M"

FREE_WEEKLY_LIMIT = 3      # Free: записей в неделю (по неделе занятия, Пн–Вс)
PREMIUM_XP_MULT = 1.5      # Premium: множитель XP за посещённые занятия
CHESTS_FREE, CHESTS_PREMIUM = 1, 2  # сундуков в день

# код: (название, месяцев, цена в тенге, подпись)
PLANS = {
    "month": ("1 месяц", 1, 2990, "Попробовать"),
    "quarter": ("3 месяца", 3, 7990, "Семестр"),
    "year": ("12 месяцев", 12, 24990, "Выгоднее всего"),
}


def plan_info(code):
    name, months, price, tag = PLANS[code]
    per_month = round(price / months)
    base = PLANS["month"][2]
    save = round((1 - per_month / base) * 100)
    return {"code": code, "name": name, "months": months, "price": price, "tag": tag,
            "per_month": per_month, "save": save}


def all_plans():
    return [plan_info(c) for c in PLANS]


def add_months(dt, months):
    return dt + timedelta(days=30 * months)


def periods(conn, user_id):
    """Все периоды Premium пользователя: [(starts_at, ends_at), ...] в формате FMT."""
    return [(r["starts_at"], r["ends_at"]) for r in conn.execute(
        "SELECT starts_at, ends_at FROM subscriptions WHERE user_id = ? ORDER BY starts_at",
        (user_id,))]


def premium_at(pers, moment):
    """Был ли Premium в момент moment (строка FMT)."""
    return any(s <= moment < e for s, e in pers)


def active_until(pers, now=None):
    """До какого момента действует Premium (с учётом продлений подряд) или None."""
    now_s = (now or datetime.now()).strftime(FMT)
    end = None
    for s, e in sorted(pers):
        if e <= now_s:
            continue
        if end is None:
            if s <= now_s:
                end = e
        elif s <= end:
            end = max(end, e)
    return end


def is_premium(conn, user_id, now=None):
    now_s = (now or datetime.now()).strftime(FMT)
    return conn.execute(
        "SELECT 1 FROM subscriptions WHERE user_id = ? AND starts_at <= ? AND ends_at > ?",
        (user_id, now_s, now_s)).fetchone() is not None


def fmt_ru(s):
    """'2026-12-24 15:00' -> '24.12.2026'."""
    return datetime.strptime(s, FMT).strftime("%d.%m.%Y") if s else ""
