"""Профиль и геймификация: уровень, XP, квесты недели, достижения, рейтинг студентов."""
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
XP_PER_CLASS, XP_NEW_TYPE, XP_PER_ACH, XP_WEEK3, XP_EARLY_WEEK = 10, 5, 15, 30, 10
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


def best_week_streak(days):
    """Лучшая серия недель подряд за всё время (полученное не пропадает при перерыве)."""
    weeks = sorted({_monday(d) for d in days})
    best = run = 0
    prev = None
    for w in weeks:
        run = run + 1 if prev is not None and w - prev == timedelta(days=7) else 1
        best = max(best, run)
        prev = w
    return best


def top(counter):
    if not counter:
        return None
    name, n = counter.most_common(1)[0]
    return {"name": name, "n": n}


BOOKING_ROWS_SQL = """SELECT b.user_id, s.starts_at, s.ends_at, ct.name AS class_name,
                  u.name AS trainer_name, h.name AS hall_name
           FROM bookings b JOIN slots s ON s.id = b.slot_id
           JOIN class_types ct ON ct.id = s.class_type_id
           JOIN users u ON u.id = s.trainer_id
           LEFT JOIN halls h ON h.id = s.hall_id
           WHERE b.status = 'booked' AND s.status = 'active' {extra}
           ORDER BY s.starts_at"""


def client_stats(conn, user_id, now=None):
    rows = conn.execute(BOOKING_ROWS_SQL.format(extra="AND b.user_id = ?"), (user_id,)).fetchall()
    return stats_from_rows(rows, now)


def stats_from_rows(rows, now=None):
    now = now or datetime.now()
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
    best = best_week_streak(dates)
    variety = len(classes)
    hours_of = [_parse(r["starts_at"]).hour for r in done]
    early_cnt = sum(1 for h in hours_of if h < 10)
    evening_cnt = sum(1 for h in hours_of if h >= 18)
    weeks3 = sum(1 for n in per_week.values() if n >= 3)
    early_weeks = len({_monday(_parse(r["starts_at"]).date()) for r in done
                       if _parse(r["starts_at"]).hour < 10})
    ach = [
        ("🎯", "Первый шаг", "Сходить на первое занятие", count >= 1),
        ("🔥", "Серия 3 недели", "Тренироваться 3 недели подряд", best >= 3),
        ("🧭", "Исследователь", "Попробовать 3 разных типа занятий", variety >= 3),
        ("🏋️", "Десяточка", "Посетить 10 занятий", count >= 10),
        ("⏱️", "Марафонец", "Набрать 10 часов тренировок", minutes >= 600),
        ("🤝", "Командный игрок", "Позаниматься у 3 разных тренеров", len(trainers) >= 3),
        ("🌅", "Ранняя пташка", "3 занятия, начавшихся до 10:00", early_cnt >= 3),
        ("🌙", "Сова", "3 занятия, начавшихся после 18:00", evening_cnt >= 3),
        ("🚀", "Серия 5 недель", "Тренироваться 5 недель подряд", best >= 5),
        ("💎", "Четвертак", "Посетить 25 занятий", count >= 25),
        ("🗺️", "Хозяин кампуса", "Позаниматься в 4 разных залах", len(halls) >= 4),
        ("🧱", "Недельный челлендж", "3 занятия за одну неделю", weeks3 >= 1),
    ]
    ach_got = sum(1 for a in ach if a[3])

    # XP: всё считается из истории, поэтому очки только растут
    xp = (XP_PER_CLASS * count + XP_NEW_TYPE * variety + XP_PER_ACH * ach_got
          + XP_WEEK3 * weeks3 + XP_EARLY_WEEK * early_weeks)

    # квесты текущей недели (прогресс считаем и по записям на будущее)
    wk_end = cur_mon + timedelta(days=7)
    this_week = [r for r in rows if cur_mon <= _parse(r["starts_at"]).date() < wk_end]
    seen_before = {r["class_name"] for r in done if _parse(r["starts_at"]).date() < cur_mon}
    new_types = {r["class_name"] for r in this_week} - seen_before
    early_week = sum(1 for r in this_week if _parse(r["starts_at"]).hour < 10)
    quests = []
    for icon, title, text, have, need, reward in [
        ("💪", "Три захода", "3 занятия на этой неделе", len(this_week), 3, XP_WEEK3),
        ("🧪", "Новая дисциплина", "Занятие, которого ты ещё не пробовал", len(new_types), 1, XP_NEW_TYPE),
        ("⏰", "До 10 утра", "Занятие, начинающееся до 10:00", early_week, 1, XP_EARLY_WEEK),
    ]:
        quests.append({"icon": icon, "title": title, "text": text, "have": min(have, need),
                       "need": need, "pct": int(min(have, need) / need * 100),
                       "done": have >= need, "reward": reward})

    return {
        "count": count, "minutes": minutes, "hours": round(minutes / 60, 1),
        "streak": streak, "level": level_for(count),
        "fav_class": top(classes), "fav_trainer": top(trainers), "fav_hall": top(halls),
        "fav_wd": WD_FULL[fav_wd] if fav_wd is not None else None,
        "daypart": part, "bars": bars, "variety": variety,
        "ach": [dict(icon=a, title=b, text=c, got=d) for a, b, c, d in ach],
        "ach_got": ach_got, "best_streak": best, "xp": xp,
        "quests": quests, "quests_done": sum(1 for q in quests if q["done"]),
        "week_n": len(this_week),
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


def leaderboard(conn, now=None):
    """Рейтинг студентов: по XP за всё время и по занятиям на этой неделе."""
    now = now or datetime.now()
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users WHERE role = 'client'")}
    by_user = {uid: [] for uid in names}
    for r in conn.execute(BOOKING_ROWS_SQL.format(extra="")):
        if r["user_id"] in by_user:
            by_user[r["user_id"]].append(r)
    entries = []
    for uid, rows in by_user.items():
        st = stats_from_rows(rows, now)
        entries.append({"id": uid, "name": names[uid], "xp": st["xp"], "count": st["count"],
                        "level": st["level"], "week": st["week_n"]})

    def rank(key):
        ordered = sorted(entries, key=lambda e: (-e[key], e["name"].lower()))
        out = []
        for e in ordered:
            better = sum(1 for o in entries if o[key] > e[key])
            tie = sum(1 for o in entries if o[key] == e[key]) > 1
            out.append(dict(e, rank=better + 1, tie=tie))
        return out
    return {"xp": [e for e in rank("xp")], "week": rank("week")}


@bp.route("/leaderboard")
@login_required
def leaderboard_page():
    boards = leaderboard(get_db())
    me = g.user["id"]
    view = {}
    for key in ("xp", "week"):
        rows = [e for e in boards[key] if e[key] > 0]
        mine = next((e for e in boards[key] if e["id"] == me), None)
        view[key] = {"top": rows[:10], "mine": mine if mine and mine not in rows[:10] else None}
    return render_template("leaderboard.html", board=view, me=me)


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
        board = leaderboard(conn)["xp"]
        mine = next((e for e in board if e["id"] == g.user["id"]), None)
        ctx["rank"] = mine["rank"] if mine and mine["xp"] > 0 else None
        ctx["rank_total"] = sum(1 for e in board if e["xp"] > 0)
    elif role == "trainer":
        ctx["t"] = trainer_stats(conn, g.user["id"])
    else:
        ctx["a"] = admin_stats(conn)
    return render_template("profile.html", **ctx)
