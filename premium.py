"""Подписка Premium и демо-оплата. Деньги не списываются, номер карты нигде не сохраняется
(в базу пишутся только последние 4 цифры для истории платежей)."""
import re
from datetime import datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)

import game
import plans
from auth import login_required, verified_required
from db import get_db
from roles import roles_required

bp = Blueprint("premium", __name__)

DECLINED_CARD = "4000000000000002"  # тестовая карта «недостаточно средств»


def luhn_ok(number):
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_brand(number):
    if number.startswith("4"):
        return "Visa"
    if re.match(r"^(5[1-5]|2[2-7])", number):
        return "Mastercard"
    return "Card"


def validate_card(form, now=None):
    """Проверка полей карты. Возвращает (ошибка или None, last4)."""
    now = now or datetime.now()
    number = re.sub(r"\D", "", form.get("number", ""))
    name = form.get("holder", "").strip()
    exp = form.get("exp", "").strip()
    cvc = form.get("cvc", "").strip()
    if not 13 <= len(number) <= 19 or not luhn_ok(number):
        return "Номер карты некорректный. Для демо подойдёт 4242 4242 4242 4242.", None
    if not name or len(name) > 60:
        return "Укажи имя владельца карты.", None
    m = re.match(r"^(\d{2})\s*/\s*(\d{2})$", exp)
    if not m or not 1 <= int(m.group(1)) <= 12:
        return "Срок действия в формате ММ/ГГ.", None
    month, year = int(m.group(1)), 2000 + int(m.group(2))
    if (year, month) < (now.year, now.month):
        return "Срок действия карты истёк.", None
    if not re.fullmatch(r"\d{3,4}", cvc):
        return "CVC — 3 цифры на обороте карты.", None
    if number == DECLINED_CARD:
        return "Банк отклонил платёж: недостаточно средств (тестовая карта).", None
    return None, number[-4:]


def activate(conn, user_id, code, last4, now=None):
    """Создаёт период подписки. Продление начинается с конца текущего периода."""
    now = now or datetime.now()
    plan = plans.plan_info(code)
    until = plans.active_until(plans.periods(conn, user_id), now)
    start = datetime.strptime(until, plans.FMT) if until else now
    end = plans.add_months(start, plan["months"])
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, plan, price, starts_at, ends_at, card_last4) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, code, plan["price"], start.strftime(plans.FMT), end.strftime(plans.FMT), last4))
    game.give_bonus(conn, user_id, f"premium{cur.lastrowid}", game.PREMIUM_BONUS)
    return cur.lastrowid


@bp.route("/premium")
@login_required
def pricing():
    h = game.hud()
    return render_template("premium.html", plans_list=plans.all_plans(),
                           limit=plans.FREE_WEEKLY_LIMIT, mult=plans.PREMIUM_XP_MULT,
                           until=plans.fmt_ru(h["premium_until"]) if h else None)


@bp.route("/premium/checkout/<code>", methods=("GET", "POST"))
@roles_required("client")
@verified_required
def checkout(code):
    if code not in plans.PLANS:
        abort(404)
    plan = plans.plan_info(code)
    form = {"holder": "", "exp": "", "method": "card"}
    if request.method == "POST":
        method = request.form.get("method", "card")
        form = {"holder": request.form.get("holder", "").strip()[:60],
                "exp": request.form.get("exp", "").strip()[:7], "method": method}
        if method == "kaspi":
            error, last4 = None, "KASP"
        else:
            error, last4 = validate_card(request.form)
        if error:
            flash(error, "error")
        else:
            sub_id = activate(get_db(), g.user["id"], code, last4)
            return redirect(url_for("premium.success", sub_id=sub_id))
    return render_template("checkout.html", plan=plan, form=form)


@bp.route("/premium/success/<int:sub_id>")
@roles_required("client")
def success(sub_id):
    sub = get_db().execute("SELECT * FROM subscriptions WHERE id = ? AND user_id = ?",
                           (sub_id, g.user["id"])).fetchone()
    if sub is None:
        abort(404)
    return render_template("premium_success.html", sub=sub, plan=plans.plan_info(sub["plan"]),
                           until=plans.fmt_ru(sub["ends_at"]), bonus=game.PREMIUM_BONUS)
