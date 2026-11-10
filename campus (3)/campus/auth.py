import re
import sqlite3
from functools import wraps

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db
from extensions import limiter

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME, MAX_EMAIL, MAX_PASSWORD = 60, 120, 128
MIN_PASSWORD = 8


@bp.before_app_request
def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("home"))

    form = {"name": "", "email": ""}
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        form = {"name": name, "email": email}

        error = None
        if not name or not email or not password:
            error = "Заполните все поля."
        elif len(name) > MAX_NAME:
            error = f"Имя не длиннее {MAX_NAME} символов."
        elif len(email) > MAX_EMAIL or not EMAIL_RE.match(email):
            error = "Введите корректный университетский email."
        elif len(password) < MIN_PASSWORD:
            error = f"Пароль — минимум {MIN_PASSWORD} символов."
        elif len(password) > MAX_PASSWORD:
            error = f"Пароль не длиннее {MAX_PASSWORD} символов."
        elif password != confirm:
            error = "Пароли не совпадают."

        if error is None:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)),
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "Аккаунт с таким email уже существует."
            else:
                flash("Аккаунт создан! Теперь войдите.", "success")
                return redirect(url_for("auth.login"))

        flash(error, "error")

    return render_template("register.html", form=form)


@bp.route("/login", methods=("GET", "POST"))
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if g.user:
        return redirect(url_for("home"))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Неверный email или пароль.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("home"))

    return render_template("login.html", email=email)


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
