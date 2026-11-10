"""Страница профиля: статистика, уровень, достижения и активность по неделям."""
from collections import Counter
from datetime import date, datetime, timedelta

from flask import Blueprint, g, render_template

import booking
from auth import login_required
from db import get_db

bp = Blueprint("profile", __name__)

# (порог занятий, название, подпись)
LEVELS = [
    (0, "Новичок", "Первый шаг — самый трудный"),
    (3, "Разогрелся", "Зал уже знает твоё лицо"),
    (8, "Постоянный гость", "Привычка пошла в рост"),
    (15, "Железный", "Штанга тебя уважает"),
    (30, "Легенда зала", "Тренеры здороваются первыми"),
]
WEEKS = 8
DAYPARTS = [(12, "Жаворонок", "🌅", "утренние занятия"),
            (17, "Дневной боец", "☀️", "дневные занятия"),
            (24, "Сова", "🌙", "вечерние занятия")]
WD_FULL = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"]


def _parse(s):
    return datetime.strptime(s, booking.FMT)


def _monday(d):
    return d - timedelta(days=d.weekday())


def level_for(count):
    idx = max(i for i, lv in enumerate(LEVELS) if count >= lv[0])
    cur = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    if nxt:
        pct = int((count - cur[0]) / (nxt[0] - cur[0]) * 100)
    else:
        pct = 100
    return {"n": idx + 1, "name": cur[1], "tagline": cur[2], "pct": pct,
            "next_name": nxt[1] if nxt else None,
            "left": (nxt[0] - count) if nxt else 0}


def week_streak(days, today):
    """Сколько недель подряд (включая текущую, если уже были занятия) есть хотя бы одно занятие."""
    weeks = {_monday(d) for d in days}
    cur = _monday(today)
    if cur not in weeks:
        cur -= timedelta(days=7)  # текущая неделя ещё может «догнаться»
    streak = 0
    while cur in weeks:
        streak += 1
        cur -= timedelta(days=7)
    return streak


def top(counter):
    if not counter:
        return None
    name, n = counter.most_common(1)[0]
    return {"name": name, "n": n}


def client_stats(conn, user_id, now=None):
    now = now or datetime.now()
    rows = conn.execute(
        """SELECT s.starts_at, s.ends_at, ct.name AS class_name,
                  u.name AS trainer_name, h.name AS hall_name
           FROM bookings b JOIN slots s ON s.id = b.slot_id
           JOIN class_types ct ON ct.id = s.class_type_id
           JOIN users u ON u.id = s.trainer_id
           LEFT JOIN halls h ON h.id = s.hall_id
           WHERE b.user_id = ? AND b.status = 'booked' AND s.status = 'active'
           ORDER BY s.starts_at""", (user_id,)).fetchall()
    now_s = booking.now_str(now)
    done = [r for r in rows if r["starts_at"] <= now_s]
    upcoming = [r for r in rows if r["starts_at"] > now_s]

    minutes = sum(int((_parse(r["ends_at"]) - _parse(r["starts_at"])).total_seconds() // 60) for r in done)
    dates = [_parse(r["starts_at"]).date() for r in done]

    classes = Counter(r["class_name"] for r in done)
    trainers = Counter(r["trainer_name"] for r in done)
    halls = Counter(r["hall_name"] for r in done if r["hall_name"])
    weekdays = Counter(d.weekday() for d in dates)
    fav_wd = weekdays.most_common(1)[0][0] if weekdays else None

    part = None
    if done:
        hours = Counter()
        for r in done:
            h = _parse(r["starts_at"]).hour
            hours[next(p for p in DAYPARTS if h < p[0])] += 1
        p = hours.most_common(1)[0][0]
        part = {"name": p[1], "icon": p[2], "text": p[3]}

    # активность по неделям (последние WEEKS недель, текущая — последняя)
    cur_mon = _monday(now.date())
    per_week = Counter(_monday(d) for d in dates)
    bars = []
    for i in range(WEEKS - 1, -1, -1):
        m = cur_mon - timedelta(days=7 * i)
        bars.append({"label": m.strftime("%d.%m"), "n": per_week.get(m, 0), "now": i == 0})
    peak = max([b["n"] for b in bars] + [1])
    for b in bars:
        b["h"] = int(b["n"] / peak * 100)

    count = len(done)
    streak = week_streak(dates, now.date())
    variety = len(classes)
    ach = [
        ("🎯", "Первый шаг", "Сходить на первое занятие", count >= 1),
        ("🔥", "Серия 3 недели", "Тренироваться 3 недели подряд", streak >= 3),
        ("🧭", "Исследователь", "Попробовать 3 разных типа занятий", variety >= 3),
        ("🏋️", "Десяточка", "Посетить 10 занятий", count >= 10),
        ("⏱️", "Марафонец", "Набрать 10 часов тренировок", minutes >= 600),
        ("🤝", "Командный игрок", "Позаниматься у 3 разных тренеров", len(trainers) >= 3),
    ]
    return {
        "count": count, "minutes": minutes, "hours": round(minutes / 60, 1),
        "streak": streak, "level": level_for(count),
        "fav_class": top(classes), "fav_trainer": top(trainers), "fav_hall": top(halls),
        "fav_wd": WD_FULL[fav_wd] if fav_wd is not None else None,
        "daypart": part, "bars": bars, "variety": variety,
        "ach": [dict(icon=a, title=b, text=c, got=d) for a, b, c, d in ach],
        "ach_got": sum(1 for a in ach if a[3]),
        "next": upcoming[0] if upcoming else None, "upcoming": len(upcoming),
        "recent": list(reversed(done[-3:])),
    }


def trainer_stats(conn, user_id):
    now_s = booking.now_str()
    rows = conn.execute(
        """SELECT s.starts_at, s.capacity, ct.name AS class_name,
                  (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status='booked') AS taken
           FROM slots s JOIN class_types ct ON ct.id = s.class_type_id
           WHERE s.trainer_id = ? AND s.status = 'active'""", (user_id,)).fetchall()
    past = [r for r in rows if r["starts_at"] <= now_s]
    classes = Counter(r["class_name"] for r in rows)
    cap = sum(r["capacity"] for r in rows)
    return {"slots": len(rows), "past": len(past), "upcoming": len(rows) - len(past),
            "people": sum(r["taken"] for r in past),
            "fill": int(sum(r["taken"] for r in rows) / cap * 100) if cap else 0,
            "fav_class": top(classes)}


def admin_stats(conn):
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "clients": one("SELECT COUNT(*) FROM users WHERE role='client'"),
        "trainers": one("SELECT COUNT(*) FROM users WHERE role='trainer'"),
        "slots": one("SELECT COUNT(*) FROM slots WHERE status='active'"),
        "bookings": one("SELECT COUNT(*) FROM bookings WHERE status='booked'"),
    }


@bp.route("/profile")
@login_required
def profile():
    conn = get_db()
    role = g.user["role"]
    created = conn.execute("SELECT created_at FROM users WHERE id = ?", (g.user["id"],)).fetchone()[0]
    since = datetime.strptime(created[:10], "%Y-%m-%d").date()
    ctx = {"since": since, "days_with_us": (date.today() - since).days}
    if role == "client":
        ctx["s"] = client_stats(conn, g.user["id"])
    elif role == "trainer":
        ctx["t"] = trainer_stats(conn, g.user["id"])
    else:
        ctx["a"] = admin_stats(conn)
    return render_template("profile.html", **ctx)
