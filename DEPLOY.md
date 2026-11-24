# FitnessIT: облачная база, почта и деплой на PythonAnywhere

Все сервисы ниже **бесплатные**. Займёт около 20–30 минут.

| Что | Сервис | Зачем |
|---|---|---|
| База данных | **Turso** (облачный SQLite) | Данные хранятся в облаке, а не в файле на компьютере |
| Почта | **Gmail SMTP** | Письмо с подтверждением при регистрации |
| Хостинг | **PythonAnywhere** (бесплатный тариф) | Сайт открывается по ссылке из интернета |

> Почему Turso, а не Supabase/Neon: бесплатный PythonAnywhere разрешает только HTTPS-запросы к сайтам
> из белого списка. Turso работает по HTTPS и есть в этом списке (`.turso.io`), обычный Postgres — нет.

Все ключи хранятся **только в файле `.env`**. Не отправляй их в чат и не заливай на GitHub
(`.env` уже есть в `.gitignore`).

---

## Шаг 1. Облачная база Turso

1. Зайди на **https://app.turso.tech** и войди через GitHub или Google.
2. **Create Database**:
   - Name: `fitnessit`
   - Region: выбери ближайший к хостингу.
     Обычный аккаунт PythonAnywhere (www.pythonanywhere.com) работает в США: бери **AWS US East (Virginia)**.
     Если аккаунт на eu.pythonanywhere.com, то **AWS EU (Frankfurt)**.
3. Открой созданную базу:
   - скопируй **URL** вида `libsql://fitnessit-логин.turso.io`;
   - нажми **Create Token** (или *Generate Token*), права **Read & Write**, срок **Never**, и скопируй токен.
4. Допиши в `.env` (в папке проекта):
   ```
   TURSO_DATABASE_URL=libsql://fitnessit-логин.turso.io
   TURSO_AUTH_TOKEN=eyJhbGciOi...очень-длинный-токен
   ```
5. Сначала освежи локальные данные: занятия на ближайшую неделю и демо-студенты с историей и Premium.
   Временно закомментируй строку `TURSO_DATABASE_URL` в `.env` и выполни:
   ```
   py seed.py --extend
   py demo_data.py
   ```
   Потом раскомментируй её обратно, проверь подключение и перенеси всё в облако:
   ```
   py turso_tool.py check
   py turso_tool.py push
   ```
   Команда `push` берёт локальный `instance/fitnessit.db` и копирует всё в облако.

Готово. Теперь `start.bat` / `python run.py` работает с облачной базой: при запуске в консоли будет строка
`База: Turso (облако)`. Таблицы можно смотреть и править в панели Turso, вкладка **Edit Data / Shell**.

- Вернуться на локальный файл: закомментируй `TURSO_DATABASE_URL` в `.env` (`#` в начале строки).
- Резервная копия облака в файл: `py turso_tool.py pull` (сохраняется в `instance/turso_backup.db`).
- Расписание на неделю вперёд прямо в облаке: `py seed.py --extend` при включённом Turso.
  Это займёт около минуты, потому что каждое занятие отправляется отдельным запросом.

---

## Шаг 2. Почта через Gmail

Обычный пароль от Gmail **не подойдёт**: нужен «пароль приложения».

1. Включи двухэтапную аутентификацию: https://myaccount.google.com/security, раздел *Двухэтапная аутентификация*.
2. Открой **https://myaccount.google.com/apppasswords**.
3. Название приложения: `FitnessIT`, нажми **Создать** и скопируй 16 букв (вида `abcd efgh ijkl mnop`).
4. Допиши в `.env`:
   ```   
   MAIL_USERNAME=твой.адрес@gmail.com
   MAIL_PASSWORD=abcd efgh ijkl mnop
   ```
5. Запусти сайт и зарегистрируй аккаунт на свою почту `@kbtu.kz`: письмо придёт в течение минуты.
   **Проверь папку «Спам»**: университетская почта часто кладёт туда письма с Gmail.

Пока почта не настроена, сайт не падает: текст письма со ссылкой печатается в консоли, где запущен сайт.

Ограничение Gmail: около 500 писем в день. Для учебного проекта хватит с запасом.

---

## Шаг 3. Хостинг на PythonAnywhere

1. Зарегистрируйся на **https://www.pythonanywhere.com** (тариф *Beginner*, бесплатный).
   Адрес сайта будет `https://ЛОГИН.pythonanywhere.com`.
2. Загрузи проект. Проще всего через GitHub: вкладка **Consoles → Bash**, затем
   ```bash
   git clone https://github.com/ТВОЙ/РЕПОЗИТОРИЙ.git fitnessit
   ```
   Без GitHub: заархивируй папку проекта в zip **без** `.env`, `instance`, `__pycache__`, загрузи через
   **Files → Upload a file** и распакуй в консоли: `unzip bis-main.zip -d fitnessit`.
3. В той же Bash-консоли поставь зависимости:
   ```bash
   cd ~/fitnessit
   pip3.10 install --user -r requirements.txt
   ```
4. Создай `.env` на сервере (**Files** → папка `fitnessit` → *New file* `.env`):
   ```
   SECRET_KEY=сюда-длинную-случайную-строку
   TURSO_DATABASE_URL=libsql://fitnessit-логин.turso.io
   TURSO_AUTH_TOKEN=eyJ...
   MAIL_USERNAME=твой.адрес@gmail.com
   MAIL_PASSWORD=abcd efgh ijkl mnop
   BEHIND_PROXY=1
   COOKIE_SECURE=1
   URL_SCHEME=https
   ```
   Случайную строку можно получить в консоли: `python3 -c "import secrets; print(secrets.token_hex(32))"`.
   `BEHIND_PROXY=1` обязателен: иначе ссылка в письме будет начинаться с `http://` вместо `https://`.
5. Вкладка **Web → Add a new web app → Manual configuration → Python 3.10**.
6. Там же, в разделе **Code**, открой **WSGI configuration file**, удали всё содержимое и вставь
   содержимое файла `pythonanywhere_wsgi.py` из проекта. Замени `<логин>` на свой логин и сохрани.
7. Раздел **Static files**: URL `/static/`, Directory `/home/ЛОГИН/fitnessit/static`.
8. Раздел **Security**: включи **Force HTTPS**.
9. Нажми зелёную кнопку **Reload** и открой `https://ЛОГИН.pythonanywhere.com`.

Если что-то не работает: вкладка **Web → Log files → error log**, там будет текст ошибки.

Особенности бесплатного тарифа:
- сайт нужно продлевать раз в 3 месяца кнопкой *Run until 3 months from today* на вкладке Web;
- внешние запросы идут через прокси PythonAnywhere. Turso и Gmail SMTP разрешены, больше ничего настраивать не нужно.

---

## Как обновлять сайт

Локально поменял код → `git push` → на PythonAnywhere в Bash-консоли:
```bash
cd ~/fitnessit && git pull
```
→ **Web → Reload**. База живёт в Turso, поэтому при обновлении кода данные не теряются.
