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


def test_comment_role_is_recommended_until_chosen(auth_client, user):
    """경험 관리의 자소서 코멘트 기준 직무: 고르지 않으면 추천 1위, 고르면 기억, ?auto=1 로 되돌림."""
    _add(user, "인사팀 인턴", role="채용 공고 작성, 면접 일정 조율, 온보딩 교육 운영", keywords="인사, 채용")
    page = auth_client.get("/experiences/manage").get_data(as_text=True)
    assert '<option value="hr" selected>' in page and "(자동 추천)" in page
    auth_client.get("/experiences/manage?role=overseas_sales")
    page = auth_client.get("/experiences/manage").get_data(as_text=True)
    assert '<option value="overseas_sales" selected>' in page and "(자동 추천)" not in page
    assert '<option value="hr" selected>' in auth_client.get("/experiences/manage?auto=1").get_data(as_text=True)

def test_category_filter_and_report(auth_client, user):
    _add(user, "카페 아르바이트", role="재고 관리", category="아르바이트")
    from app.experiences.models import Certificate
    db.session.add(Certificate(user_id=user.id, name="TOEIC", score="900"))
    db.session.commit()
    page = auth_client.get("/experiences/manage").get_data(as_text=True)
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


def _confirm(client, page_names, **extra):
    """미리보기에서 그대로 '확인하고 저장'을 누른 것과 같은 폼."""
    data = {"source": "paste", "source_text": REPORT, "filename": "강점.txt", "name": page_names,
            "summary": [""] * len(page_names), "definition": [""] * len(page_names),
            "orig": [f"{n}||" for n in page_names], "keep": ["1"] * len(page_names),
            "was_edited": ["0"] * len(page_names)}
    data.update(extra)
    return client.post("/strengths/confirm", data=data, follow_redirects=True)


def test_strength_upload_previews_then_saves(app, auth_client, user):
    r = auth_client.post("/strengths/upload", data={"file": (io.BytesIO(REPORT.encode()), "강점.txt")},
                         content_type="multipart/form-data")
    page = r.get_data(as_text=True)
    assert "추출 결과 확인" in page and "신중함" in page and "결과지 속 위치" in page
    assert db.session.query(StrengthProfile).count() == 0  # 확인 전에는 저장하지 않음

    page = _confirm(auth_client, ["신중함", "효과성", "주도"]).get_data(as_text=True)
    assert "강점 3개를 저장했어요" in page and "경험과 연결하기" in page
    # 다시 저장하면 새 결과지가 '사용 중'이 되고, 이전 결과지는 저장본으로 남음
    _confirm(auth_client, ["신중함"])
    rows = db.session.query(StrengthProfile).filter_by(user_id=user.id).order_by(StrengthProfile.id).all()
    assert len(rows) == 2 and [r.is_active for r in rows] == [False, True]
    assert rows[0].parsed["source"] == "paste" and rows[0].extracted_text == REPORT  # 출처·원문 보관

    page = auth_client.post(f"/strengths/{rows[0].id}/activate", follow_redirects=True).get_data(as_text=True)
    assert "결과지를 불러왔어요" in page
    db.session.expire_all()
    assert db.session.get(StrengthProfile, rows[0].id).is_active
    auth_client.post("/strengths/delete")
    assert db.session.query(StrengthProfile).count() == 0


def test_preview_edits_are_marked_and_unknown_names_flagged(auth_client, user):
    _confirm(auth_client, ["신중함", "주도", "지어낸강점"],
             summary=["고친 설명", "", ""], keep=["1", "0", "1"])  # 주도는 빼기
    prof = db.session.query(StrengthProfile).one()
    got = {s["name"]: s for s in prof.strengths}
    assert list(got) == ["신중함", "지어낸강점"]
    assert got["신중함"]["edited"] and got["신중함"]["in_source"]
    assert not got["지어낸강점"]["in_source"]  # 결과지 글에 없는 이름은 표시
    page = auth_client.get("/strengths/").get_data(as_text=True)
    assert "직접 고침" in page and "결과지에 없는 이름" in page


def test_unknown_format_warns_it_is_a_guess(auth_client, user):
    text = "저는 분석력이 좋다는 말을 들어요. 분석력 점수가 높았고 협업도 좋아요. 협업 상황에서 빛나요."
    page = auth_client.post("/strengths/upload", data={"pasted": text}).get_data(as_text=True)
    assert "결과지 형식을 알아보지 못했어요" in page and "추정" in page


def test_editing_profile_drops_links_of_removed_strengths(auth_client, user):
    from app.analysis.models import StrengthLink
    _confirm(auth_client, ["신중함", "주도"])
    prof = db.session.query(StrengthProfile).one()
    e = _add(user, "AX마스터 팀장", role="팀장")
    db.session.add_all([StrengthLink(user_id=user.id, profile_id=prof.id, strength_name=n, experience_id=e.id)
                        for n in ("신중함", "주도")])
    db.session.commit()
    assert "추출 결과" not in auth_client.get(f"/strengths/{prof.id}/edit").get_data(as_text=True)
    page = _confirm(auth_client, ["신중함"], profile_id=prof.id).get_data(as_text=True)
    assert "빠진 강점의 경험 연결 1개를 지웠어요" in page
    assert [lk.strength_name for lk in db.session.query(StrengthLink)] == ["신중함"]
    assert db.session.query(StrengthProfile).count() == 1


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
