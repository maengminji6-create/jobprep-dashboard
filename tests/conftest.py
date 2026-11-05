import pytest

from app import create_app
from app.auth.models import User
from app.extensions import db as _db


@pytest.fixture
def app():
    app = create_app("test")

    # 테스트는 앱 컨텍스트를 계속 열어 두므로, 요청마다 새로 뜨는 실제 서버처럼 로그인 캐시를 비움
    @app.teardown_request
    def _forget_cached_user(_exc):
        from flask import g
        g.pop("_login_user", None)

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


def login(client, email):
    """로그인 화면이 없으므로 세션에 직접 넣어 그 사용자로 바꿉니다(데이터 분리 테스트용)."""
    uid = _db.session.query(User).filter_by(email=email).one().id
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True


@pytest.fixture
def user(app):
    return make_user("a@test.com", "사용자A")


@pytest.fixture
def auth_client(client, user):
    login(client, user.email)
    return client
