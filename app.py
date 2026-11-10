import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

import auth
import db
import userpage
import schedule
import staff
from extensions import csrf, limiter

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent


def create_app(test_config=None):
    app = Flask(__name__)

    if os.environ.get("BEHIND_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    secret = os.environ.get("SECRET_KEY")
    if not secret or secret == "change-me":
        # Для разработки: временный ключ (сессии сбросятся при перезапуске).
        secret = secrets.token_hex(32)
        print("⚠ SECRET_KEY не задан — используется временный ключ. См. .env.example")

    app.config.update(
        SECRET_KEY=secret,
        DATABASE=str(BASE_DIR / "instance" / "fitnessit.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",  # включить за HTTPS
        MAX_CONTENT_LENGTH=64 * 1024,
    )

    if test_config:
        app.config.update(test_config)

    csrf.init_app(app)
    limiter.init_app(app)
    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(schedule.bp)
    app.register_blueprint(staff.bp)
    app.register_blueprint(userpage.bp)

    ICONS = {"Йога": "🧘", "Кроссфит": "🔥", "Силовая тренировка": "🏋️", "Кардио": "🏃",
             "Пилатес": "🤸", "Стретчинг": "🌿", "Бокс": "🥊", "Зумба": "💃", "HIIT": "⚡"}
    HUES = {"Йога": 160, "Кроссфит": 15, "Силовая тренировка": 265, "Кардио": 195,
            "Пилатес": 320, "Стретчинг": 130, "Бокс": 0, "Зумба": 330, "HIIT": 45}

    app.jinja_env.filters["cicon"] = lambda n: ICONS.get(n, "💪")
    app.jinja_env.filters["chue"] = lambda n: HUES.get(n, 20)

    @app.route("/")
    @auth.login_required
    def home():
        return schedule.render_schedule()

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, text="Нет доступа к этой странице."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, text="Страница не найдена."), 404

    @app.errorhandler(429)
    def too_many(_e):
        return render_template(
            "error.html", code=429, text="Слишком много попыток. Подождите минуту."
        ), 429

    @app.errorhandler(400)
    def bad_request(_e):
        return render_template(
            "error.html", code=400, text="Некорректный запрос или устаревшая форма."
        ), 400

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500, text="Что-то пошло не так."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
