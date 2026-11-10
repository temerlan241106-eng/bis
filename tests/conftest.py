import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from db import get_db  # noqa: E402
import seed  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app({
        "DATABASE": str(tmp_path / "test.db"),
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with app.app_context():
        seed.seed_if_empty(get_db())
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password):
    return client.post("/login", data={"email": email, "password": password})


@pytest.fixture()
def as_client(client):
    login(client, "client@kbtu.kz", "Client12345")
    return client
