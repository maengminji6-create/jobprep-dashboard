"""비밀번호 찾기: 메일(가짜)로 링크 → 새 비밀번호 · 1회용 · 만료 · 위조 · 가입 여부 비공개 · Host 헤더 무시."""
import re

import pytest

from app.auth import routes as auth_routes
from app.auth.services import make_reset_token
from app.integrations import mailer

from .conftest import login, make_user


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body: sent.append((to, subject, body)) or True)
    auth_routes._reset_email_at.clear()
    auth_routes._reset_ip_hits.clear()
    return sent


def _link(body):
    return re.search(r"https://growly\.test(/auth/reset/\S+)", body).group(1)


def test_login_page_links_to_forgot(client):
    assert "/auth/forgot" in client.get("/auth/login").get_data(as_text=True)


def test_reset_flow_and_link_is_single_use(app, client, outbox):
    make_user("me@test.com")
    r = client.post("/auth/forgot", data={"email": " ME@test.com "}, follow_redirects=True)
    assert "재설정 링크를 보냈어요" in r.get_data(as_text=True)
    assert len(outbox) == 1 and outbox[0][0] == "me@test.com"
    path = _link(outbox[0][2])

    assert "새 비밀번호" in client.get(path).get_data(as_text=True)
    r = client.post(path, data={"password": "short", "password2": "short"}, follow_redirects=True)
    assert "8자 이상" in r.get_data(as_text=True)
    r = client.post(path, data={"password": "newpass123", "password2": "different1"}, follow_redirects=True)
    assert "서로 달라요" in r.get_data(as_text=True)
    r = client.post(path, data={"password": "newpass123", "password2": "newpass123"}, follow_redirects=True)
    assert "비밀번호를 바꿨어요" in r.get_data(as_text=True)

    assert "올바르지 않습니다" in login(client, "me@test.com", "password123").get_data(as_text=True)
    assert "올바르지 않습니다" not in login(client, "me@test.com", "newpass123").get_data(as_text=True)
    client.post("/auth/logout")
    # 같은 링크로 다시 바꾸기 불가(비밀번호가 바뀌면 이전 링크 무효)
    r = client.post(path, data={"password": "hacked1234", "password2": "hacked1234"}, follow_redirects=True)
    assert "만료됐거나 이미 사용" in r.get_data(as_text=True)
    assert "올바르지 않습니다" not in login(client, "me@test.com", "newpass123").get_data(as_text=True)


def test_unknown_email_gets_same_message_and_no_mail(client, outbox):
    make_user("me@test.com")
    unknown = client.post("/auth/forgot", data={"email": "nobody@test.com"}, follow_redirects=True).get_data(as_text=True)
    assert "가입된 이메일이라면" in unknown and outbox == []


def test_forged_expired_and_other_users_token(app, client, outbox, monkeypatch):
    a = make_user("a@test.com")
    make_user("b@test.com")
    token = make_reset_token(a)
    assert "만료됐거나" in client.get(f"/auth/reset/{token[:-3]}xyz", follow_redirects=True).get_data(as_text=True)
    app.config["PASSWORD_RESET_MAX_AGE"] = -1
    assert "만료됐거나" in client.get(f"/auth/reset/{token}", follow_redirects=True).get_data(as_text=True)
    app.config["PASSWORD_RESET_MAX_AGE"] = 1800
    # 다른 SECRET_KEY 로 만든 토큰은 무효
    app.config["SECRET_KEY"], old = "other-secret", app.config["SECRET_KEY"]
    forged = make_reset_token(a)
    app.config["SECRET_KEY"] = old
    assert "만료됐거나" in client.get(f"/auth/reset/{forged}", follow_redirects=True).get_data(as_text=True)


def test_link_ignores_host_header_and_rate_limits(client, outbox):
    make_user("me@test.com")
    client.post("/auth/forgot", data={"email": "me@test.com"}, headers={"Host": "evil.example"})
    assert "evil.example" not in outbox[0][2] and "https://growly.test/auth/reset/" in outbox[0][2]
    client.post("/auth/forgot", data={"email": "me@test.com"})  # 60초 안에 또 → 메일 안 보냄
    assert len(outbox) == 1
