"""Игровой слой: уровни по XP, лиги, титулы, рамки аватара, ежедневный сундук, HUD в шапке."""
import random
import sqlite3
from datetime import date, datetime

from flask import Blueprint, abort, g, jsonify, request, session

import plans
from db import batch, get_db

bp = Blueprint("game", __name__)

# (порог XP, название, подпись)
LEVELS = [
    (0, "Новичок", "Первый шаг — самый трудный"),
    (40, "Разогрелся", "Зал уже знает твоё лицо"),
    (100, "Постоянный гость", "Привычка пошла в рост"),
    (180, "Железный", "Штанга тебя уважает"),
    (280, "Стальной", "Пресс уже виден в планах"),
    (400, "Титан", "Гравитация нервничает"),
    (600, "Чемпион", "На тебя равняются"),
    (850, "Легенда зала", "Тренеры здороваются первыми"),
]

# (порог XP, код, название, иконка)
LEAGUES = [(0, "bronze", "Бронза", "🥉"), (150, "silver", "Серебро", "🥈"),
           (400, "gold", "Золото", "🥇"), (700, "diamond", "Алмаз", "💎")]

# код: (название, как открыть, проверка по контексту)
TITLES = {
    "rookie": ("Новичок зала", "Есть у всех", lambda c: True),
    "explorer": ("Исследователь", "3 разных типа занятий", lambda c: c["variety"] >= 3),
    "early": ("Ранняя пташка", "3 занятия до 10:00", lambda c: "Ранняя пташка" in c["ach"]),
    "owl": ("Ночная сова", "3 занятия после 18:00", lambda c: "Сова" in c["ach"]),
    "iron": ("Железный", "Уровень 4", lambda c: c["level"] >= 4),
    "streak": ("Огненная серия", "3 недели подряд", lambda c: c["best"] >= 3),
    "titan": ("Титан KBTU", "Уровень 6", lambda c: c["level"] >= 6),
    "legend": ("Легенда кампуса", "Уровень 8", lambda c: c["level"] >= 8),
    "vip": ("Premium-атлет", "Подписка Premium", lambda c: c["premium"]),
}

FRAMES = {
    "none": ("Без рамки", "Есть у всех", lambda c: True),
    "neon": ("Неон", "Уровень 2", lambda c: c["level"] >= 2),
    "toxic": ("Токсик", "10 занятий", lambda c: c["count"] >= 10),
    "fire": ("Пламя", "3 недели подряд", lambda c: c["best"] >= 3),
    "ice": ("Лёд", "Уровень 4", lambda c: c["level"] >= 4),
    "rainbow": ("Радуга", "Уровень 7", lambda c: c["level"] >= 7),
    "gold": ("Золото", "Подписка Premium", lambda c: c["premium"]),
}

VERIFY_BONUS = 20
PREMIUM_BONUS = 50


def level_for(xp):
    idx = max(i for i, lv in enumerate(LEVELS) if xp >= lv[0])
    cur = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    pct = int((xp - cur[0]) / (nxt[0] - cur[0]) * 100) if nxt else 100
    return {"n": idx + 1, "name": cur[1], "tagline": cur[2], "pct": pct,
            "next_name": nxt[1] if nxt else None, "left": (nxt[0] - xp) if nxt else 0}


def league_for(xp):
    lg = [lv for lv in LEAGUES if xp >= lv[0]][-1]
    return {"code": lg[1], "name": lg[2], "icon": lg[3]}


def unlock_ctx(stats, premium):
    return {"level": stats["level"]["n"], "best": stats["best_streak"], "variety": stats["variety"],
            "count": stats["count"], "premium": premium,
            "ach": {a["title"] for a in stats["ach"] if a["got"]}}


def cosmetics(stats, premium):
    c = unlock_ctx(stats, premium)
    titles = [{"code": k, "name": v[0], "how": v[1], "open": v[2](c)} for k, v in TITLES.items()]
    frames = [{"code": k, "name": v[0], "how": v[1], "open": v[2](c)} for k, v in FRAMES.items()]
    return titles, frames


def user_style(user, stats=None, premium=False):
    """Какие титул и рамку показывать (выбранные, если ещё доступны)."""
    title = user["title"] if "title" in user.keys() else None
    frame = user["frame"] if "frame" in user.keys() else None
    if stats is not None:
        c = unlock_ctx(stats, premium)
        if title not in TITLES or not TITLES[title][2](c):
            title = None
        if frame not in FRAMES or not FRAMES[frame][2](c):
            frame = None
    return {"title": TITLES[title][0] if title in TITLES else None, "frame": frame or "none"}


def client_queries(user_id):
    """Запросы для статистики клиента: записи, периоды Premium, бонусный XP."""
    import userpage
    return [
        (userpage.BOOKING_ROWS_SQL.format(extra="AND b.user_id = ?"), (user_id,)),
        ("SELECT starts_at, ends_at FROM subscriptions WHERE user_id = ? ORDER BY starts_at", (user_id,)),
        ("SELECT day, kind, amount FROM bonus_xp WHERE user_id = ?", (user_id,)),
    ]


def client_data(conn, user_id, now=None, prefetched=None):
    """Всё для статистики клиента. prefetched — уже полученные (rows, subs, bonus),
    чтобы не ходить в базу второй раз за запрос (см. auth.load_user)."""
    import userpage
    if prefetched is None:
        prefetched = [c.fetchall() for c in batch(conn, client_queries(user_id))]
    rows, subs, bonus = prefetched
    pers = [(r["starts_at"], r["ends_at"]) for r in subs]
    stats = userpage.stats_from_rows(rows, now, pers, sum(b["amount"] for b in bonus))
    today = date.today().isoformat()
    opened = sum(1 for b in bonus if b["day"] == today and b["kind"].startswith("chest"))
    until = plans.active_until(pers, now)
    return {"stats": stats, "periods": pers, "premium": until is not None, "premium_until": until,
            "chests_left": max(0, (plans.CHESTS_PREMIUM if until else plans.CHESTS_FREE) - opened),
            "bonus": bonus}


def hud():
    """Данные для шапки: уровень, XP, серия, сундук. Кэшируется на запрос."""
    if "hud" in g:
        return g.hud
    g.hud = None
    user = g.get("user")
    if user is not None and user["role"] == "client":
        pre = g.pop("prefetch", None)
        d = client_data(get_db(), user["id"],
                        prefetched=pre[1] if pre and pre[0] == user["id"] else None)
        s = d["stats"]
        style = user_style(g.user, s, d["premium"])
        g.hud = {"level": s["level"], "xp": s["xp"], "streak": s["streak"], "premium": d["premium"],
                 "premium_until": d["premium_until"], "chests_left": d["chests_left"],
                 "league": league_for(s["xp"]), "data": d, **style}
        # новый уровень с прошлого визита -> салют
        prev = session.get("lvl")
        if prev is not None and s["level"]["n"] > prev:
            g.hud["levelup"] = s["level"]
        if prev != s["level"]["n"]:
            session["lvl"] = s["level"]["n"]
    return g.hud


def give_bonus(conn, user_id, kind, amount, day=None):
    """Начислить бонусный XP один раз (повтор с тем же kind в тот же день игнорируется)."""
    try:
        conn.execute("INSERT INTO bonus_xp (user_id, day, kind, amount) VALUES (?, ?, ?, ?)",
                     (user_id, day or date.today().isoformat(), kind, amount))
        return True
    except sqlite3.IntegrityError:
        return False


def roll_chest(rnd=random):
    x = rnd.random()
    if x < 0.05:
        return rnd.choice([50, 60, 75]), "legendary"
    if x < 0.30:
        return rnd.randint(20, 30), "rare"
    return rnd.randint(5, 15), "common"


@bp.route("/chest", methods=("POST",))
def open_chest():
    if g.user is None or g.user["role"] != "client":
        abort(403)
    if not g.user["email_verified"]:
        return jsonify(ok=False, error="Сначала подтверди почту — письмо уже ждёт тебя."), 400
    h = hud()
    if h["chests_left"] <= 0:
        return jsonify(ok=False, error="Сундук уже открыт. Возвращайся завтра!"), 400
    conn = get_db()
    total = plans.CHESTS_PREMIUM if h["premium"] else plans.CHESTS_FREE
    amount, rarity = roll_chest()
    kind = f"chest{total - h['chests_left'] + 1}"
    if not give_bonus(conn, g.user["id"], kind, amount):
        return jsonify(ok=False, error="Сундук уже открыт. Возвращайся завтра!"), 400
    g.pop("hud", None)
    after = hud()
    return jsonify(ok=True, xp=amount, rarity=rarity, total=after["xp"],
                   left=after["chests_left"], level=after["level"]["n"],
                   levelup=bool(after.get("levelup")), level_name=after["level"]["name"],
                   pct=after["level"]["pct"])


@bp.route("/profile/style", methods=("POST",))
def set_style():
    from flask import flash, redirect, url_for
    if g.user is None or g.user["role"] != "client":
        abort(403)
    h = hud()
    titles, frames = cosmetics(h["data"]["stats"], h["premium"])
    title = request.form.get("title") or None
    frame = request.form.get("frame") or None
    ok_t = {t["code"] for t in titles if t["open"]}
    ok_f = {f["code"] for f in frames if f["open"]}
    if (title and title not in ok_t) or (frame and frame not in ok_f):
        flash("Это ещё не открыто — продолжай тренироваться 💪", "error")
    else:
        get_db().execute("UPDATE users SET title = ?, frame = ? WHERE id = ?",
                         (title, frame if frame != "none" else None, g.user["id"]))
        flash("Стиль профиля обновлён ✨", "success")
    return redirect(url_for("profile.profile") + "#style")


def init_app(app):
    app.register_blueprint(bp)

    @app.context_processor
    def inject_hud():
        return {"hud": hud(), "now_year": datetime.now().year,
                "premium_from": min(p["per_month"] for p in plans.all_plans())}
