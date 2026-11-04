"""로그인 없이 브라우저마다 개인 공간: 자동 접속 · 쿠키로 유지 · 기록 열쇠로 다시 열기."""
from app.auth.models import User
from app.experiences.models import Experience
from app.extensions import db

from .conftest import make_user


def _add(client, title):
    client.post("/experiences/save", data={"title": title, "role": "통관 서류"})


def test_no_login_needed(client):
    assert client.get("/experiences/").status_code == 200
    assert db.session.query(User).count() == 1
    assert client.get("/auth/login").status_code == 404  # 로그인 화면 없음


def test_all_pages_render(client):
    assert client.get("/").status_code == 302  # 첫 화면 = 경험 분석
    for url in ["/experiences/", "/experiences/posting", "/strengths/", "/applications/", "/me/"]:
        assert client.get(url).status_code == 200, url


def test_each_browser_gets_own_space(app):
    a, b = app.test_client(), app.test_client()
    _add(a, "A의 무역 인턴")
    assert "A의 무역 인턴" not in b.get("/experiences/").get_data(as_text=True)
    assert db.session.query(User).count() == 2


def test_records_survive_restart(app, client):
    """세션 쿠키가 사라져도(브라우저·앱을 다시 켬) 오래 가는 쿠키로 같은 공간."""
    _add(client, "무역 인턴")
    client.delete_cookie("session")
    assert "무역 인턴" in client.get("/experiences/").get_data(as_text=True)
    assert db.session.query(User).count() == 1


def test_access_key_reopens_space(app, client):
    _add(client, "무역 인턴")
    page = client.post("/me/", data={"action": "key"}).get_data(as_text=True)
    key = page.split('id="access-key">')[1].split("<")[0]
    other = app.test_client()  # 다른 기기
    other.post("/me/open", data={"key": key})
    assert "무역 인턴" in other.get("/experiences/").get_data(as_text=True)


def test_wrong_key_cannot_open_others_space(app, client):
    b = make_user("b@test.com")
    db.session.add(Experience(user_id=b.id, title="B의 비밀 경험"))
    db.session.commit()
    client.post("/me/open", data={"key": f"{b.id}-추측한값"})
    client.post("/me/open", data={"key": f"{b.id}-"})
    assert "B의 비밀 경험" not in client.get("/experiences/").get_data(as_text=True)


def test_owner_email_only_for_local(app, client):
    me = make_user("me@test.com", "민지")
    app.config["OWNER_EMAIL"] = "me@test.com"
    _add(client, "무역 인턴")
    assert db.session.query(Experience).filter_by(user_id=me.id).count() == 1
    from app.config import BaseConfig, ProdConfig
    assert BaseConfig.OWNER_EMAIL == "" and ProdConfig.OWNER_EMAIL == ""


def test_rename(client):
    client.post("/me/", data={"name": "민지"})
    assert "민지님의" in client.get("/experiences/").get_data(as_text=True)
