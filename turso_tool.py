"""Работа с облачной базой Turso из командной строки.

  python turso_tool.py check          — проверить подключение (TURSO_DATABASE_URL и TURSO_AUTH_TOKEN из .env)
  python turso_tool.py push           — залить локальную базу instance/fitnessit.db в Turso
                                        (схема + все данные; облачная база должна быть пустой)
  python turso_tool.py push --force   — сначала очистить облачную базу, потом залить
  python turso_tool.py pull           — скачать облачную базу в instance/turso_backup.db (резервная копия)
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

import turso  # noqa: E402
from db import SCHEMA  # noqa: E402

TABLES = ["users", "class_types", "halls", "slots", "bookings", "subscriptions", "bonus_xp"]
LOCAL = BASE / "instance" / "fitnessit.db"
CHUNK = 150
URL, TOKEN = os.environ.get("TURSO_DATABASE_URL", ""), os.environ.get("TURSO_AUTH_TOKEN", "")


def remote():
    if not URL or not TOKEN:
        sys.exit("✗ В .env нет TURSO_DATABASE_URL и/или TURSO_AUTH_TOKEN. См. DEPLOY.md, шаг 1.")
    return turso.Connection(URL, TOKEN, timeout=60)


def local_conn():
    """Локальная база, приведённая к актуальной схеме (как при запуске сайта)."""
    os.environ["TURSO_DATABASE_URL"] = ""  # чтобы app поднялся на локальном файле
    from app import create_app
    from db import get_db
    app = create_app({"TURSO_DATABASE_URL": ""})
    with app.app_context():
        get_db()  # схема и миграции уже применены в create_app
    conn = sqlite3.connect(LOCAL)
    conn.row_factory = sqlite3.Row
    return conn


def count(conn, table):
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def check():
    r = remote()
    t = time.time()
    r.execute("SELECT 1")
    ms = int((time.time() - t) * 1000)
    print(f"✓ Turso отвечает ({ms} мс)")
    for table in TABLES:
        print(f"  {table:<14} {count(r, table)}")


def push(force=False):
    src = local_conn()
    r = remote()
    r.executescript(SCHEMA)
    from db import migrate
    migrate(r)
    if any(count(r, t) for t in TABLES):
        if not force:
            sys.exit("✗ В облачной базе уже есть данные. Чтобы перезаписать: python turso_tool.py push --force")
        print("Очищаю облачную базу…")
        r.batch([(f"DELETE FROM {t}", ()) for t in reversed(TABLES)])
    for table in TABLES:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  {table:<14} 0")
            continue
        cols = rows[0].keys()
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        for i in range(0, len(rows), CHUNK):
            r.batch([(sql, tuple(row)) for row in rows[i:i + CHUNK]])
            print(f"\r  {table:<14} {min(i + CHUNK, len(rows))}/{len(rows)}", end="", flush=True)
        print()
    print("✓ Готово: данные в Turso. Сайт будет работать с облаком, пока в .env задан TURSO_DATABASE_URL.")


def pull():
    r = remote()
    out = BASE / "instance" / "turso_backup.db"
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        out.unlink()
    dst = sqlite3.connect(out)
    dst.executescript(SCHEMA)
    for table in TABLES:
        rows = r.execute(f"SELECT * FROM {table}").fetchall()
        if rows:
            cols = rows[0].keys()
            dst.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [tuple(x) for x in rows])
        print(f"  {table:<14} {len(rows)}")
    dst.commit()
    dst.close()
    print(f"✓ Резервная копия: {out}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        check()
    elif cmd == "push":
        push(force="--force" in sys.argv)
    elif cmd == "pull":
        pull()
    else:
        print(__doc__)
