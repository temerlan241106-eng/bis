# Диаграммы

## Use Case
```mermaid
flowchart LR
  C([Клиент]) --> A1(Регистрация и вход)
  C --> A2(Смотреть расписание с фильтрами)
  C --> A3(Записаться на занятие)
  C --> A4(Отменить запись)
  C --> A5(Мои записи)
  T([Тренер]) --> A1
  T --> A2
  T --> B1(Список записанных на свои занятия)
  AD([Админ]) --> A1
  AD --> A2
  AD --> D1(Создать занятие)
  AD --> D2(Отменить занятие)
  AD --> B2(Видеть записанных)
```

## Процесс бронирования
```mermaid
flowchart TD
  S([Клиент нажал «Записаться»]) --> R{Роль = клиент?}
  R -- нет --> E403[403]
  R -- да --> TX[BEGIN IMMEDIATE]
  TX --> C1{1. Занятие есть и активно?}
  C1 -- нет --> ERR[ROLLBACK + сообщение]
  C1 -- да --> C2{2. Ещё не началось?}
  C2 -- нет --> ERR
  C2 -- да --> C3{3. Нет активной записи?}
  C3 -- нет --> ERR
  C3 -- да --> C4{4. Нет пересечения по времени?}
  C4 -- нет --> ERR
  C4 -- да --> C5{5. Есть свободные места?}
  C5 -- нет --> ERR
  C5 -- да --> OK[INSERT booking + COMMIT]
```

## Процесс отмены
```mermaid
flowchart TD
  S([Клиент нажал «Отменить»]) --> B{Активная запись есть?}
  B -- нет --> ERR[Сообщение об ошибке]
  B -- да --> T{До начала 2 часа или больше?}
  T -- нет --> ERR
  T -- да --> OK[status = cancelled, место освобождено]
```

## ER-диаграмма
```mermaid
erDiagram
  users ||--o{ bookings : делает
  users ||--o{ slots : ведёт
  class_types ||--o{ slots : тип
  halls ||--o{ slots : проходит
  slots ||--o{ bookings : содержит
  users { int id PK
    text name
    text email UK
    text password_hash
    text role "client|trainer|admin" }
  class_types { int id PK
    text name UK
    int duration_min "CHECK > 0"
    int default_capacity "CHECK > 0" }
  halls { int id PK
    text name UK
    text description }
  slots { int id PK
    int class_type_id FK
    int trainer_id FK
    int hall_id FK
    text starts_at
    text ends_at "CHECK > starts_at"
    int capacity "CHECK > 0"
    text status "active|cancelled" }
  bookings { int id PK
    int user_id FK
    int slot_id FK
    text status "booked|cancelled"
    text created_at }
```
Ограничение `UNIQUE(user_id, slot_id)` на `bookings`. Внешние ключи включены через `PRAGMA foreign_keys = ON`.

## Архитектура
```mermaid
flowchart LR
  B[Браузер] -- HTTP, форма + CSRF-токен --> F[Flask: auth / schedule / staff]
  F -- проверка роли --> R[roles.py]
  F -- правила записи --> K[booking.py]
  K -- SQL с параметрами --> D[(SQLite: instance/fitnessit.db)]
  F -- лимиты --> L[Flask-Limiter]
```
Стек: Flask + SQLite. Пароли хранятся хешами (werkzeug). Вход не говорит, что именно неверно: email или пароль.
