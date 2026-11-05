"""AI 사용량: 운영자 키로 개인 공간마다 무료 N회 · 하루 상한 · 이미지 차감 → 그 뒤엔 내 OpenAI 키(암호화 저장)."""
from types import SimpleNamespace

import openai
import pytest

from app.auth.models import AiDailyUsage, User
from app.core import ai_quota
from app.core.secret_box import mask, open_, seal
from app.extensions import db
from app.integrations import ai_client

from .conftest import login, make_user


class FakeOpenAI:
    """openai.OpenAI 대신: 어떤 키로 불렀는지 기록하고 정해 둔 JSON을 돌려줌."""
    calls = []
    fail = False

    def __init__(self, api_key, timeout=None):
        self.api_key = api_key
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: [])

    def _create(self, **kw):
        FakeOpenAI.calls.append(self.api_key)
        if FakeOpenAI.fail:
            raise openai.APIConnectionError(request=None)
        msg = SimpleNamespace(refusal=None, content='{"ok": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


@pytest.fixture
def quota(app, monkeypatch):
    """배포처럼: 운영자 키 있음, 무료 5회, 하루 50회, 이미지 3회."""
    app.config.update(OPENAI_API_KEY="sk-operator-key-0000000000", AI_FREE_PER_USER=5, AI_FREE_DAILY_CAP=50,
                      AI_VISION_COST=3, TESTING=False)
    FakeOpenAI.calls, FakeOpenAI.fail = [], False
    monkeypatch.setattr(ai_client.openai, "OpenAI", FakeOpenAI)
    return app


def _call():
    return ai_client._call("s", "p", {"type": "object"}, "t")


def test_five_free_calls_then_blocked(quota, user):
    with quota.test_request_context():
        from flask_login import login_user
        login_user(user)
        for _ in range(5):
            assert _call() == {"ok": True}
        assert user.ai_free_used == 5 and FakeOpenAI.calls == ["sk-operator-key-0000000000"] * 5
        assert not ai_client.enabled()
        with pytest.raises(ai_client.AiError) as e:
            _call()
        assert "무료 AI 5회" in str(e.value) and "내 공간" in str(e.value)
        assert len(FakeOpenAI.calls) == 5  # 막힌 뒤로는 운영자 키를 부르지 않음


def test_failed_call_is_not_charged(quota, user):
    with quota.test_request_context():
        from flask_login import login_user
        login_user(user)
        FakeOpenAI.fail = True
        with pytest.raises(ai_client.AiError):
            _call()
        assert user.ai_free_used == 0


def test_own_key_has_no_limit_and_is_used(quota, user):
    user.ai_free_used = 5
    user.openai_key_enc = seal("sk-my-own-key-1234567890")
    db.session.commit()
    with quota.test_request_context():
        from flask_login import login_user
        login_user(user)
        assert ai_client.enabled()
        for _ in range(7):
            _call()
        assert set(FakeOpenAI.calls) == {"sk-my-own-key-1234567890"} and user.ai_free_used == 5


def test_daily_cap_and_vision_cost(quota, user):
    quota.config["AI_FREE_DAILY_CAP"] = 4
    with quota.test_request_context():
        from flask_login import login_user
        login_user(user)
        assert ai_quota.available(3) and not ai_quota.available(6)  # 남은 5회 → 이미지(3) 가능
        _call()
        _call()
        _call()
        assert not ai_quota.available(3)  # 하루 4회 중 3회 사용 → 이미지(3회)는 넘침
        assert ai_quota.available(1)
        _call()
        assert not ai_quota.available(1)
        assert "오늘 무료 AI 사용량" in ai_quota.unavailable_message()
        assert db.session.query(AiDailyUsage).one().count == 4


def test_local_without_limit_and_messages(app, user):
    app.config.update(OPENAI_API_KEY="", AI_FREE_PER_USER=0)
    with app.test_request_context():
        assert not ai_quota.available()
        assert ".env 에 OPENAI_API_KEY" in ai_quota.unavailable_message()  # 로컬(테스트) 안내
    app.config.update(OPENAI_API_KEY="sk-operator", AI_FREE_PER_USER=0)
    with app.test_request_context():
        assert ai_quota.available() and ai_quota.free_left() is None  # 제한 없음


def test_secret_box():
    from flask import Flask
    a = Flask(__name__)
    a.config.update(SECRET_KEY="one", ENCRYPTION_KEY="")
    with a.app_context():
        token = seal("sk-abc-1234567890")
        assert token and "sk-abc" not in token and open_(token) == "sk-abc-1234567890"
        assert mask("sk-abc-1234567890") == "sk-…7890"
    a.config["SECRET_KEY"] = "two"
    with a.app_context():
        assert open_(token) == ""  # 암호화 키가 바뀌면 풀지 못함 → 다시 넣게 함


def test_save_key_on_me_page(quota, auth_client, user, monkeypatch):
    checked = []
    monkeypatch.setattr(ai_client, "check_key", lambda k: checked.append(k))
    page = auth_client.get("/me/").get_data(as_text=True)
    assert "무료 AI <b>5</b>회 남았어요" in page
    r = auth_client.post("/me/ai-key", data={"api_key": "not-a-key"}, follow_redirects=True)
    assert "sk-" in r.get_data(as_text=True) and not checked
    r = auth_client.post("/me/ai-key", data={"api_key": "sk-proj-abcdefghij1234567890"}, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert checked == ["sk-proj-abcdefghij1234567890"] and "sk-…7890" in page and "횟수 제한 없음" in page
    db.session.refresh(user)
    assert "abcdefghij" not in user.openai_key_enc  # 원래 값은 저장하지 않음
    assert "sk-proj-abcdefghij1234567890" not in page
    auth_client.post("/me/ai-key", data={"action": "delete"})
    db.session.refresh(user)
    assert user.openai_key_enc == ""


def test_invalid_key_is_not_saved(quota, auth_client, user, monkeypatch):
    def bad(_k):
        raise ai_client.AiError("키가 올바르지 않아요.")
    monkeypatch.setattr(ai_client, "check_key", bad)
    r = auth_client.post("/me/ai-key", data={"api_key": "sk-wrong-1234567890abcdef"}, follow_redirects=True)
    assert "키가 올바르지 않아요" in r.get_data(as_text=True)
    db.session.refresh(user)
    assert not user.openai_key_enc


def test_others_key_is_never_used(quota, app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    b.openai_key_enc = seal("sk-b-secret-key-1234567890")
    db.session.commit()
    login(client, a.email)
    page = client.get("/me/").get_data(as_text=True)
    assert "sk-…7890" not in page and "무료 AI <b>5</b>회" in page
    with app.test_request_context():
        from flask_login import login_user
        login_user(db.session.get(User, a.id))
        assert ai_quota.own_key() == ""
