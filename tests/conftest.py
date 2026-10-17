import pytest

from app import create_app
from app.auth.models import User
from app.extensions import db as _db


@pytest.fixture
def app():
    app = create_app("test")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(email, name="테스터", password="password123"):
    u = User(email=email, name=name)
    u.set_password(password)
    _db.session.add(u)
    _db.session.commit()
    return u


def login(client, email, password="password123"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


@pytest.fixture
def user(app):
    return make_user("a@test.com", "사용자A")


@pytest.fixture
def auth_client(client, user):
    login(client, user.email)
    return client
