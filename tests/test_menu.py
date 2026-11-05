"""리뉴얼 메뉴: 홈 · 경험 관리 · 강점 연결 · 자소서 보관함. 공고 매칭·면접·일정은 LEGACY_FEATURES 가 꺼지면 숨기고 막음."""
import pytest

from app import create_app
from app.experiences.models import Experience
from app.extensions import db as _db
from tests.conftest import login, make_user


@pytest.fixture
def off_client():
    """쉬는 기능을 끈 실제 배포와 같은 상태."""
    app = create_app("test")
    app.config["LEGACY_FEATURES"] = False
    with app.app_context():
        _db.create_all()
        client = app.test_client()
        u = make_user("off@test.com")
        _db.session.add(Experience(user_id=u.id, title="포워딩 인턴", role="FCL 부킹"))
        _db.session.commit()
        login(client, u.email)
        yield client
        _db.session.remove()
        _db.drop_all()


def test_nav_hides_legacy_menus(off_client):
    page = off_client.get("/experiences/").get_data(as_text=True)
    for label in ("홈", "경험 관리", "AI 분석", "직무 연결", "자소서 보관함"):
        assert f">{label}</a>" in page
    for label in ("공고 매칭", "면접 준비", "취업 일정", "다가오는 일정", "최근 분석한 공고"):
        assert label not in page


def test_legacy_urls_return_404(off_client):
    for url in ("/experiences/posting", "/interview/", "/schedule/"):
        assert off_client.get(url).status_code == 404, url


def test_manage_page_lists_experiences(off_client):
    page = off_client.get("/experiences/manage").get_data(as_text=True)
    assert "포워딩 인턴" in page and 'id="tab-exp"' in page and 'id="certs"' in page


def test_legacy_menus_back_when_enabled(auth_client):
    page = auth_client.get("/experiences/").get_data(as_text=True)
    assert ">공고 매칭</a>" in page
    assert auth_client.get("/schedule/").status_code == 200


def test_new_experience_opens_star_then_updates_return_to_manage(auth_client):
    r = auth_client.post("/experiences/save", data={"title": "새 경험", "role": "역할"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/edit#star")
    r = auth_client.post("/experiences/save", data={"title": "새 경험", "content": "덧붙인 내용"})
    assert r.headers["Location"].endswith("/experiences/manage")
