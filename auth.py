"""Регистрация с кодом из письма, вход, выход.

Аккаунт НЕ создаётся, пока человек не введёт 6-значный код, отправленный на @kbtu.kz:
данные формы лежат в таблице signup_codes (пароль — уже хешем, код — HMAC-хешем),
пользователь появляется в users только после верного кода.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import mailer
from db import batch, get_db
from extensions import limiter

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME, MAX_EMAIL, MAX_PASSWORD = 60, 120, 128
MIN_PASSWORD = 8
EMAIL_DOMAIN = "@kbtu.kz"

CODE_TTL = timedelta(minutes=15)      # сколько живёт код
RESEND_AFTER = timedelta(seconds=60)  # не чаще одного письма в минуту
MAX_ATTEMPTS = 5                      # неверных вводов на один код
TS = "%Y-%m-%d %H:%M:%S"


# ---------- пользователь в запросе ----------
@bp.before_app_request
def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        import game
        # пользователь + данные для шапки одним обращением к базе (важно для облачной Turso)
        res = batch(get_db(), [
            ("SELECT id, name, email, role, email_verified, title, frame, created_at FROM users WHERE id = ?",
             (user_id,)),
            *game.client_queries(user_id),
        ])
        g.user = res[0].fetchone()
        if g.user is not None and g.user["role"] == "client":
            g.prefetch = (g.user["id"], [c.fetchall() for c in res[1:]])


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def verified_required(view):
    """Страховка: действия только для подтверждённых аккаунтов."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        if not g.user["email_verified"]:
            session.clear()
            flash("Сначала подтверди почту кодом из письма.", "error")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


# ---------- коды ----------
def _code_hash(email, code):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _now():
    return datetime.now()


def issue_code(conn, email, name, password_hash):
    """Создаёт (или заменяет) код для email и отправляет письмо. Возвращает True, если ушло."""
    code = f"{secrets.randbelow(10 ** 6):06d}"
    now = _now()
    conn.execute(
        "INSERT OR REPLACE INTO signup_codes (email, name, password_hash, code_hash, expires_at, sent_at, attempts) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (email, name, password_hash, _code_hash(email, code),
         (now + CODE_TTL).strftime(TS), now.strftime(TS)))
    sent = mailer.send(email, f"{code} — код для FitnessIT KBTU", "code",
                       name=name, code=code, minutes=int(CODE_TTL.total_seconds() // 60))
    if not sent and not mailer.configured() and current_app.debug:
        flash(f"Почта не настроена. Код для теста: {code}", "info")
    return sent


def _pending():
    email = session.get("signup_email")
    if not email:
        return None
    return get_db().execute("SELECT * FROM signup_codes WHERE email = ?", (email,)).fetchone()


def _validate(name, email, password, confirm):
    if not name or not email or not password:
        return "Заполните все поля."
    if len(name) > MAX_NAME:
        return f"Имя не длиннее {MAX_NAME} символов."
    if len(email) > MAX_EMAIL or not EMAIL_RE.match(email):
        return "Введите корректный email."
    if not email.endswith(EMAIL_DOMAIN):
        return f"Нужен университетский email вида you{EMAIL_DOMAIN}."
    if len(password) < MIN_PASSWORD:
        return f"Пароль — минимум {MIN_PASSWORD} символов."
    if len(password) > MAX_PASSWORD:
        return f"Пароль не длиннее {MAX_PASSWORD} символов."
    if password != confirm:
        return "Пароли не совпадают."
    return None


# ---------- регистрация ----------
@bp.route("/register", methods=("GET", "POST"))
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if g.user:
        return redirect(url_for("home"))

    form = {"name": "", "email": ""}
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        form = {"name": name, "email": email}

        error = _validate(name, email, password, request.form.get("confirm", ""))
        conn = get_db()
        if error is None:
            user = conn.execute("SELECT email_verified FROM users WHERE email = ?", (email,)).fetchone()
            if user is not None and user["email_verified"]:
                error = "Аккаунт с таким email уже существует. Войдите."
        if error is None:
            if issue_code(conn, email, name, generate_password_hash(password)):
                flash(f"Мы отправили 6-значный код на {email}. Проверь и папку «Спам».", "success")
            else:
                flash("Не удалось отправить письмо. Нажми «Отправить код ещё раз».", "error")
            session.clear()
            session["signup_email"] = email
            return redirect(url_for("auth.confirm"))
        flash(error, "error")

    return render_template("register.html", form=form)


@bp.route("/register/confirm", methods=("GET", "POST"))
@limiter.limit("20 per 10 minutes", methods=["POST"])
def confirm():
    import game
    if g.user:
        return redirect(url_for("home"))
    row = _pending()
    if row is None:
        flash("Начни регистрацию заново.", "error")
        return redirect(url_for("auth.register"))

    if request.method == "POST":
        code = re.sub(r"\D", "", request.form.get("code", ""))
        conn = get_db()
        now = _now().strftime(TS)
        if row["expires_at"] < now:
            flash("Код устарел. Нажми «Отправить код ещё раз».", "error")
        elif row["attempts"] >= MAX_ATTEMPTS:
            flash("Слишком много попыток. Запроси новый код.", "error")
        elif len(code) != 6 or not hmac.compare_digest(_code_hash(row["email"], code), row["code_hash"]):
            conn.execute("UPDATE signup_codes SET attempts = attempts + 1 WHERE email = ?", (row["email"],))
            left = MAX_ATTEMPTS - row["attempts"] - 1
            flash(f"Неверный код. Осталось попыток: {left}." if left > 0
                  else "Неверный код. Попытки закончились — запроси новый.", "error")
        else:
            existing = conn.execute("SELECT id, email_verified FROM users WHERE email = ?",
                                    (row["email"],)).fetchone()
            if existing is not None and existing["email_verified"]:
                conn.execute("DELETE FROM signup_codes WHERE email = ?", (row["email"],))
                session.clear()
                flash("Аккаунт уже подтверждён. Войдите.", "success")
                return redirect(url_for("auth.login"))
            try:
                if existing is not None:  # старый неподтверждённый аккаунт
                    conn.execute("UPDATE users SET name = ?, password_hash = ?, email_verified = 1 WHERE id = ?",
                                 (row["name"], row["password_hash"], existing["id"]))
                    user_id = existing["id"]
                else:
                    cur = conn.execute(
                        "INSERT INTO users (name, email, password_hash, email_verified) VALUES (?, ?, ?, 1)",
                        (row["name"], row["email"], row["password_hash"]))
                    user_id = cur.lastrowid
            except sqlite3.IntegrityError:
                flash("Аккаунт с таким email уже существует. Войдите.", "error")
                return redirect(url_for("auth.login"))
            conn.execute("DELETE FROM signup_codes WHERE email = ?", (row["email"],))
            game.give_bonus(conn, user_id, "verify", game.VERIFY_BONUS)
            session.clear()
            session["user_id"] = user_id
            flash(f"Добро пожаловать, {row['name']}! Почта подтверждена: +{game.VERIFY_BONUS} XP 🎉", "levelup")
            return redirect(url_for("home"))

    wait = 0
    sent_at = datetime.strptime(row["sent_at"], TS)
    left = (sent_at + RESEND_AFTER - _now()).total_seconds()
    if left > 0:
        wait = int(left) + 1
    return render_template("confirm.html", email=row["email"], wait=wait,
                           minutes=int(CODE_TTL.total_seconds() // 60))


@bp.route("/register/resend", methods=("POST",))
@limiter.limit("5 per hour")
def resend_code():
    row = _pending()
    if row is None:
        return redirect(url_for("auth.register"))
    if datetime.strptime(row["sent_at"], TS) + RESEND_AFTER > _now():
        flash("Подожди минуту перед повторной отправкой.", "error")
    elif issue_code(get_db(), row["email"], row["name"], row["password_hash"]):
        flash(f"Новый код отправлен на {row['email']}.", "success")
    else:
        flash("Не удалось отправить письмо. Попробуй позже.", "error")
    return redirect(url_for("auth.confirm"))


# ---------- вход / выход ----------
@bp.route("/login", methods=("GET", "POST"))
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if g.user:
        return redirect(url_for("home"))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute(
            "SELECT id, name, password_hash, email_verified FROM users WHERE email = ?", (email,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Неверный email или пароль.", "error")
        elif not user["email_verified"]:
            # аккаунт, созданный до появления кодов: сначала подтверждение
            issue_code(conn, email, user["name"], user["password_hash"])
            session.clear()
            session["signup_email"] = email
            flash(f"Подтверди почту: код отправлен на {email}.", "success")
            return redirect(url_for("auth.confirm"))
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("home"))

    return render_template("login.html", email=email)


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
