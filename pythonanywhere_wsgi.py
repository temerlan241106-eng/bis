"""WSGI-файл для PythonAnywhere.

Скопируй содержимое этого файла в WSGI configuration file на вкладке Web
(ссылка вида /var/www/<логин>_pythonanywhere_com_wsgi.py) и замени <логин> на свой.
Подробно — DEPLOY.md.
"""
import sys
from pathlib import Path

PROJECT = Path("/home/<логин>/fitnessit")  # папка проекта на PythonAnywhere
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT / ".env")

from app import app as application  # noqa: E402,F401
