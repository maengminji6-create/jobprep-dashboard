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


def test_manage_groups_by_type_and_flags_heading_like_titles(auth_client, user):
    from app.extensions import db as _db
    _db.session.add_all([
        Experience(user_id=user.id, title="카페 아르바이트", category="아르바이트", content="종류: 디저트 카페/알바\n음료 제조와 재고 관리"),
        Experience(user_id=user.id, title="1순위", category="인턴·직장 경험", period="2025.04~2025.08"),
        Experience(user_id=user.id, title="한국 대기업 제조사 지원 맞춤 핵심 경험 추천 가이드", category="기타"),
        Experience(user_id=user.id, title="버디", category="기타", content="1명"),
    ])
    _db.session.commit()
    page = auth_client.get("/experiences/manage").get_data(as_text=True)
    # 유형별 묶음이 기준표 순서(인턴 → … → 아르바이트 → … → 기타)로
    assert page.index('data-group="인턴·직장 경험"') < page.index('data-group="아르바이트"') < page.index('data-group="기타"')
    assert '<span class="kind">디저트 카페/알바</span>' in page  # 원래 적은 종류
    assert "음료 제조와 재고 관리" in page  # 내용 첫 줄 미리보기('종류:' 줄은 뺌)
    assert page.count('data-review="1"') == 2 and "확인 필요 <b>2</b>" in page  # 1순위 · 가이드 (버디는 아님)
    assert "아직 적은 내용이 없어요" in page
