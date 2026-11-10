"""Запуск FitnessIT одной командой:  python run.py
Сам ставит зависимости, создаёт .env с ключом, стартует сервер и открывает браузер."""
import importlib.util
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", 5000))


def ensure_deps():
    needed = ["flask", "flask_wtf", "flask_limiter", "dotenv"]
    if all(importlib.util.find_spec(m) for m in needed):
        return
    print("Устанавливаю зависимости (один раз)...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    )


def ensure_env():
    env = BASE / ".env"
    if not env.exists():
        env.write_text(f"SECRET_KEY={secrets.token_hex(32)}\n", encoding="utf-8")
        print("Создан файл .env с новым SECRET_KEY")


def main():
    ensure_deps()
    ensure_env()

    from app import app  # импорт после установки зависимостей
    import seed
    from db import get_db

    with app.app_context():
        if seed.seed_if_empty(get_db()):
            print("Добавлены тестовые данные (аккаунты — в README)")

    url = f"http://{HOST}:{PORT}"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  FitnessIT запущен: {url}\n  Остановить: Ctrl+C\n")
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
