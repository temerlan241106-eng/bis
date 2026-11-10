"""Тестовые данные: пользователи, 5 залов, 9 типов занятий, 7 тренеров,
расписание на неделю вперёд.

Запуск вручную:
  python seed.py           — заполнить пустую базу
  python seed.py --extend  — добавить залы, тренеров и занятия в уже существующую
                             базу (записи и аккаунты не трогаются)
"""
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

import booking

USERS = [
    ("Админ", "admin@kbtu.kz", "Admin12345", "admin"),
    ("Тренер Алия", "trainer@kbtu.kz", "Trainer12345", "trainer"),
    ("Клиент Данияр", "client@kbtu.kz", "Client12345", "client"),
    ("Тренер Мадина", "trainer2@kbtu.kz", "Trainer12345", "trainer"),
    ("Тренер Ерлан", "trainer3@kbtu.kz", "Trainer12345", "trainer"),
    ("Тренер Арман", "trainer4@kbtu.kz", "Trainer12345", "trainer"),
    ("Тренер Нурлан", "trainer5@kbtu.kz", "Trainer12345", "trainer"),
    ("Тренер Дана", "trainer6@kbtu.kz", "Trainer12345", "trainer"),
    ("Тренер Тимур", "trainer7@kbtu.kz", "Trainer12345", "trainer"),
]

# (название, описание, длительность в минутах, вместимость по умолчанию)
# Первые четыре остаются на своих местах: на них ссылаются тесты (id 1 = Йога).
CLASS_TYPES = [
    ("Йога", "Растяжка, дыхание, баланс", 60, 12),
    ("Кроссфит", "Функциональная тренировка высокой интенсивности", 60, 10),
    ("Силовая тренировка", "Работа со свободными весами", 75, 8),
    ("Кардио", "Бег, велотренажёры, интервалы", 45, 15),
    ("Пилатес", "Контроль корпуса, осанка, гибкость", 55, 12),
    ("Стретчинг", "Мягкая растяжка всего тела", 40, 15),
    ("Бокс", "Техника ударов и работа на мешках", 60, 10),
    ("Зумба", "Танцевальная кардио-программа", 50, 20),
    ("HIIT", "Короткие интервальные тренировки", 40, 12),
]

HALLS = [
    ("Студия йоги", "Тихий зал с зеркалами и матами"),
    ("Функциональный зал", "Петли, гири, канаты, площадка для кроссфита"),
    ("Тренажёрный зал", "Свободные веса и силовые тренажёры"),
    ("Кардио-зона", "Беговые дорожки, велотренажёры, эллипсы"),
    ("Зал единоборств", "Ринг, груши и лапы"),
    ("Зал групповых программ", "Большой зал для танцев и групповых занятий"),
]

# Где проходит какое занятие
CLASS_HALL = {
    "Йога": "Студия йоги",
    "Пилатес": "Студия йоги",
    "Стретчинг": "Студия йоги",
    "Кроссфит": "Функциональный зал",
    "HIIT": "Функциональный зал",
    "Силовая тренировка": "Тренажёрный зал",
    "Кардио": "Кардио-зона",
    "Бокс": "Зал единоборств",
    "Зумба": "Зал групповых программ",
}

# Кто что ведёт (по email)
TRAINER_SKILLS = {
    "trainer@kbtu.kz": ["Йога", "Пилатес", "Стретчинг"],
    "trainer2@kbtu.kz": ["Йога", "Стретчинг", "Зумба", "Пилатес"],
    "trainer3@kbtu.kz": ["Кроссфит", "HIIT", "Силовая тренировка"],
    "trainer4@kbtu.kz": ["Силовая тренировка", "Кроссфит", "Кардио"],
    "trainer5@kbtu.kz": ["Бокс", "HIIT", "Кардио"],
    "trainer6@kbtu.kz": ["Зумба", "Кардио", "Пилатес"],
    "trainer7@kbtu.kz": ["Бокс", "Силовая тренировка", "Кроссфит"],
}

# Ежедневный шаблон: (час, минута, занятие). Зал берётся из CLASS_HALL.
DAY_PLAN = [
    # Студия йоги
    (8, 0, "Йога"), (9, 30, "Пилатес"), (12, 0, "Стретчинг"),
    (17, 30, "Йога"), (19, 0, "Пилатес"),
    # Функциональный зал
    (7, 30, "HIIT"), (12, 0, "Кроссфит"), (18, 0, "Кроссфит"), (19, 30, "HIIT"),
    # Тренажёрный зал
    (9, 0, "Силовая тренировка"), (13, 30, "Силовая тренировка"),
    (17, 0, "Силовая тренировка"), (20, 0, "Силовая тренировка"),
    # Кардио-зона
    (8, 0, "Кардио"), (11, 0, "Кардио"), (15, 0, "Кардио"), (18, 30, "Кардио"),
    # Зал единоборств
    (16, 0, "Бокс"), (18, 0, "Бокс"), (19, 30, "Бокс"),
    # Зал групповых программ
    (10, 30, "Зумба"), (14, 0, "Зумба"), (19, 0, "Зумба"),
]
SUNDAY_FROM, SUNDAY_TO = 10, 18  # в воскресенье зал работает короче


def _overlaps(intervals, start, end):
    return any(s < end and e > start for s, e in intervals)


def seed(conn):
    """Идемпотентно добавляет пользователей, залы, типы и занятия."""
    for name, email, pwd, role in USERS:
        conn.execute(
            "INSERT OR IGNORE INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(pwd), role),
        )
    for row in CLASS_TYPES:
        conn.execute(
            "INSERT OR IGNORE INTO class_types (name, description, duration_min, default_capacity) "
            "VALUES (?, ?, ?, ?)", row)
    for row in HALLS:
        conn.execute("INSERT OR IGNORE INTO halls (name, description) VALUES (?, ?)", row)

    types = {r["name"]: r for r in conn.execute("SELECT * FROM class_types")}
    halls = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM halls")}
    trainers = {r["email"]: r["id"] for r in conn.execute(
        "SELECT id, email FROM users WHERE role = 'trainer'")}

    # Старые занятия без зала привязываем к залу по типу занятия
    for name, hall in CLASS_HALL.items():
        conn.execute(
            "UPDATE slots SET hall_id = ? WHERE hall_id IS NULL AND class_type_id = ?",
            (halls[hall], types[name]["id"]))

    # Что уже занято, чтобы не создавать пересечения у тренера и в зале
    busy_trainer, busy_hall = {}, {}
    for r in conn.execute(
            "SELECT trainer_id, hall_id, starts_at, ends_at FROM slots "
            "WHERE status = 'active' AND starts_at > ?", (booking.now_str(),)):
        busy_trainer.setdefault(r["trainer_id"], []).append((r["starts_at"], r["ends_at"]))
        busy_hall.setdefault(r["hall_id"], []).append((r["starts_at"], r["ends_at"]))

    for d in range(1, 8):
        day = date.today() + timedelta(days=d)
        for i, (hour, minute, class_name) in enumerate(DAY_PLAN):
            if day.weekday() == 6 and not SUNDAY_FROM <= hour < SUNDAY_TO:
                continue
            ct = types[class_name]
            hall_id = halls[CLASS_HALL[class_name]]
            start = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
            end = start + timedelta(minutes=ct["duration_min"])
            s, e = start.strftime(booking.FMT), end.strftime(booking.FMT)
            if _overlaps(busy_hall.get(hall_id, []), s, e):
                continue
            # тренеры, которые ведут это занятие; по кругу, чтобы нагрузка делилась
            pool = [trainers[em] for em, skills in TRAINER_SKILLS.items()
                    if class_name in skills and em in trainers]
            if not pool:
                continue
            shift = (d + i) % len(pool)
            pool = pool[shift:] + pool[:shift]
            trainer_id = next(
                (t for t in pool if not _overlaps(busy_trainer.get(t, []), s, e)), None)
            if trainer_id is None:
                continue
            conn.execute(
                "INSERT INTO slots (class_type_id, trainer_id, hall_id, starts_at, ends_at, capacity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ct["id"], trainer_id, hall_id, s, e, ct["default_capacity"]),
            )
            busy_hall.setdefault(hall_id, []).append((s, e))
            busy_trainer.setdefault(trainer_id, []).append((s, e))


def seed_if_empty(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
        return True
    return False


if __name__ == "__main__":
    from app import app
    from db import get_db
    with app.app_context():
        if "--extend" in sys.argv:
            seed(get_db())
            print("Залы, тренеры и занятия добавлены")
        else:
            print("Данные добавлены" if seed_if_empty(get_db()) else
                  "База не пуста — пропуск (для добавления: python seed.py --extend)")
