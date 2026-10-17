"""추천 직무 · 이력 PDF(인쇄) 페이지 · 강점 연결 · 새 직무."""
import io

from app.experiences.models import Experience
from app.extensions import db
from app.strengths.models import StrengthProfile
from app.strengths.services import link_strengths, parse_strengths

from .conftest import login, make_user

REPORT = """TOP 5 강점 DNA
1 신중함 잘못될 일을 미리 살핍니다 2 효과성 덜 들이고 더 얻는 방법을 찾습니다
3 주도 먼저 나서서 이끕니다
9WAY MATRIX
DNA 세부 가이드 Top1. 신중함
정의
신중함은 일을 시작하기 전에 문제를 살피는 DNA입니다.
"""


def _add(user, title, role="", keywords="", category="프로젝트"):
    e = Experience(user_id=user.id, title=title, category=category, role=role, content="", strengths="",
                   keywords=keywords, reflection="")
    db.session.add(e)
    db.session.commit()
    return e


def test_new_roles_exist():
    from app.core.trade_roles import ROLE_BY_CODE
    for code in ("hr", "sales_support", "biz_support", "overseas_marketing"):
        assert code in ROLE_BY_CODE
    assert "글로벌마케팅" in ROLE_BY_CODE["overseas_marketing"]["name"]


def test_recommended_role_is_used_when_not_chosen(auth_client, user):
    _add(user, "인사팀 인턴", role="채용 공고 작성, 면접 일정 조율, 온보딩 교육 운영", keywords="인사, 채용")
    page = auth_client.get("/experiences/").get_data(as_text=True)
    assert "나에게 맞는 직무" in page and "추천 1" in page
    assert "인사(HR) TOP 3 경험" in page and "(자동 추천)" in page
    # 직접 고르면 기억하고, '추천 1위로 돌아가기'로 되돌림
    assert "해외영업 TOP 3 경험" in auth_client.get("/experiences/?role=overseas_sales").get_data(as_text=True)
    assert "해외영업 TOP 3 경험" in auth_client.get("/experiences/").get_data(as_text=True)
    assert "인사(HR) TOP 3 경험" in auth_client.get("/experiences/?auto=1").get_data(as_text=True)


def test_category_filter_and_report(auth_client, user):
    _add(user, "카페 아르바이트", role="재고 관리", category="아르바이트")
    from app.experiences.models import Certificate
    db.session.add(Certificate(user_id=user.id, name="TOEIC", score="900"))
    db.session.commit()
    page = auth_client.get("/experiences/").get_data(as_text=True)
    assert 'data-filter="아르바이트"' in page and 'data-filter="자격증·어학"' not in page
    rep = auth_client.get("/experiences/report").get_data(as_text=True)
    assert "이력 정리" in rep and "카페 아르바이트" in rep and "TOEIC" in rep and "window.print()" in rep


def test_parse_and_link_strengths(user):
    parsed = parse_strengths(REPORT)
    assert [s["name"] for s in parsed["strengths"]] == ["신중함", "효과성", "주도"]
    assert parsed["strengths"][0]["summary"] == "잘못될 일을 미리 살핍니다"
    assert parsed["strengths"][0]["definition"].startswith("신중함은")
    e = _add(user, "AX마스터 팀장", role="팀장, 회의 진행, 일정관리 체크리스트")
    linked = {s["name"]: s for s in link_strengths(parsed["strengths"], [e])}
    assert linked["주도"]["matches"][0]["id"] == e.id and "팀장" in linked["주도"]["matches"][0]["words"]
    assert linked["신중함"]["matches"][0]["words"] == ["체크"]


def test_strength_upload_page_and_ai(app, auth_client, user, monkeypatch):
    _add(user, "AX마스터 팀장", role="팀장, 의견 취합, 일정 관리")
    r = auth_client.post("/strengths/upload", data={"file": (io.BytesIO(REPORT.encode()), "강점.txt")},
                         content_type="multipart/form-data", follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "강점 3개를 찾았어요" in page and "강점 × 경험 연결 지도" in page and "AX마스터 팀장" in page

    # 다시 올리면 새 결과지가 '사용 중'이 되고, 이전 결과지는 저장본으로 남음
    auth_client.post("/strengths/upload", data={"pasted": REPORT}, follow_redirects=True)
    rows = db.session.query(StrengthProfile).filter_by(user_id=user.id).order_by(StrengthProfile.id).all()
    assert len(rows) == 2 and [r.is_active for r in rows] == [False, True]

    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    exp_id = db.session.query(Experience).filter_by(user_id=user.id).one().id

    def fake(report_text, names, exps, role_name):
        return ({"headline": "신중하게 판단하고 빠르게 움직이는 사람", "core_message": "핵심 메시지",
                 "strengths": [{"name": "주도", "summary": "먼저 이끕니다",
                                "experiences": [{"id": exp_id, "how": "팀장으로 회의를 이끔"}, {"id": 999, "how": "x"}],
                                "essay_tip": "팁"}]}, False)
    monkeypatch.setattr(ai_client, "link_strengths_ai", fake)
    page = auth_client.post("/strengths/ai", follow_redirects=True).get_data(as_text=True)
    assert "신중하게 판단하고 빠르게 움직이는 사람" in page and "팀장으로 회의를 이끔" in page

    # 예전 결과지 불러오기 → 그 결과지가 사용 중
    page = auth_client.post(f"/strengths/{rows[0].id}/activate", follow_redirects=True).get_data(as_text=True)
    assert "결과지를 불러왔어요" in page
    db.session.expire_all()
    assert db.session.get(StrengthProfile, rows[0].id).is_active
    auth_client.post("/strengths/delete")
    assert db.session.query(StrengthProfile).count() == 0


def test_strength_profile_is_private(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    db.session.add(StrengthProfile(user_id=b.id, filename="b.pdf", extracted_text="비밀 결과지",
                                   parsed_json='{"strengths": [{"name": "비밀강점", "summary": "", "rank": 1}]}'))
    db.session.commit()
    login(client, a.email)
    page = client.get("/strengths/").get_data(as_text=True)
    assert "비밀강점" not in page and "내 강점 결과지를 올려 주세요" in page
    client.post("/strengths/delete")
    assert db.session.query(StrengthProfile).filter_by(user_id=b.id).count() == 1
