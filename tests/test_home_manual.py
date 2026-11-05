"""홈 대시보드(실제 데이터 · 점수 없음) · 나의 강점 사용 설명서(근거만 엮기 · 저장·다시 열기) · 상황별 활용."""
import json

from app.analysis.models import ExperienceAnalysis, StrengthLink, StrengthManual
from app.experiences.models import Experience
from app.extensions import db
from app.strengths.models import StrengthProfile

from .conftest import login, make_user


def _exp(user, title, comps=(), analyzed=True, period="2025.03 ~ 2025.06", **kw):
    e = Experience(user_id=user.id, title=title, category=kw.pop("category", "인턴·직장 경험"), period=period,
                   star_action=f"{title}에서 직접 한 행동", **kw)
    db.session.add(e)
    db.session.commit()
    if analyzed:
        data = {"competencies": [{"name": n, "level": "충분", "quotes": [{"quote": f"{title}에서 직접 한 행동", "field": "행동",
                                                                         "reason": ""}]} for n in comps],
                "results": [], "needs_info": [], "problem_solving": None}
        db.session.add(ExperienceAnalysis(user_id=user.id, experience_id=e.id, content_hash=e.content_hash,
                                          data_json=json.dumps(data, ensure_ascii=False)))
        db.session.commit()
    return e


def _profile(user, names):
    p = StrengthProfile(user_id=user.id, filename="강점.pdf",
                        parsed_json=json.dumps({"strengths": [{"name": n, "summary": f"{n} 설명", "rank": i + 1}
                                                              for i, n in enumerate(names)]}, ensure_ascii=False))
    db.session.add(p)
    db.session.commit()
    return p


def test_home_shows_real_counts_without_scores(auth_client, user):
    _exp(user, "호주 법인 인턴", ["글로벌 커뮤니케이션", "데이터 분석"])
    _exp(user, "카페 아르바이트", analyzed=False, category="아르바이트", period="")
    page = auth_client.get("/experiences/").get_data(as_text=True)
    assert "커리어 대시보드" in page and "<b>2</b>개" in page and "<b>1</b>/ 2" in page  # 경험 2 · 분석 1/2
    assert "인턴·직장 경험" in page and "아르바이트" in page  # 유형별 현황
    assert "2025 · 1개" in page and "기간 미입력 · 1개" in page  # 연도별
    assert "글로벌 커뮤니케이션 <b>1</b>" in page  # 발견된 핵심 역량
    assert "카페 아르바이트" in page.split("분석이 필요한 경험")[1]  # 아직 분석하지 않은 경험
    jobs = page[page.index('id="jobs"'):]
    assert "1 / 6" in jobs  # 해외영업: 글로벌 커뮤니케이션 확인
    assert "적합도" not in page and "TOP 3" not in page and "radarChart" not in page  # 키워드 점수는 쓰지 않음


def test_home_empty_state(auth_client):
    page = auth_client.get("/experiences/").get_data(as_text=True)
    assert "아직 등록된 경험이 없어요" in page


def test_report_has_no_scores(auth_client, user):
    _exp(user, "호주 법인 인턴", ["글로벌 커뮤니케이션"])
    rep = auth_client.get("/experiences/report").get_data(as_text=True)
    assert "직무별 확인된 역량" in rep and "점수가 아니에요" in rep and "<small>점</small>" not in rep


def test_manual_combines_diagnosis_and_experience_evidence(auth_client, user):
    e1 = _exp(user, "무역학회 리서치", ["시장 조사·분석", "데이터 분석"])
    _exp(user, "카페 아르바이트", ["고객 응대", "협업·조율"], category="아르바이트")
    p = _profile(user, ["분석력", "창의성"])
    db.session.add(StrengthLink(user_id=user.id, profile_id=p.id, strength_name="분석력", experience_id=e1.id,
                                quote="무역학회 리서치에서 직접 한 행동", reason="시장을 조사함", evidence="충분"))
    db.session.commit()
    page = auth_client.get("/analysis/manual?job=sourcing").get_data(as_text=True)
    strengths = page[page.index('id="strengths"'):page.index('id="situations"')]
    assert strengths.index("분석력") < strengths.index("고객 응대") < strengths.index("창의성")  # 일치 → 경험 기반 → 부족
    assert "진단 · 경험 일치" in strengths and "경험 기반" in strengths and "진단 · 경험 근거 부족" in strengths
    assert "“무역학회 리서치에서 직접 한 행동”" in strengths  # 근거는 원문 인용
    assert "원자재 시세와 공급 시장 동향" in strengths  # 연결 직무(구매)에서의 쓰임
    assert "경험 근거 없음" in strengths  # 창의성 보완점
    situ = page[page.index('id="situations"'):]
    assert "구매에 필요한 역량이 드러난 경험" in situ and "협업·갈등 해결 문항" in situ and "1분 자기소개 조합" in situ
    assert "카페 아르바이트" in situ.split("협업·갈등 해결 문항")[1].split("문제 해결")[0]


def test_manual_save_and_reopen_keeps_snapshot(auth_client, user):
    e = _exp(user, "호주 법인 인턴", ["글로벌 커뮤니케이션"])
    r = auth_client.post("/analysis/manual/save", data={"job": "overseas_sales", "name": "11월 해외영업용"},
                         follow_redirects=True)
    assert "11월 해외영업용&#39;(으)로 저장했어요" in r.get_data(as_text=True)
    row = db.session.query(StrengthManual).one()
    assert row.job_code == "overseas_sales" and row.data["strengths"][0]["name"] == "글로벌 커뮤니케이션"
    e.title = "제목을 바꾼 인턴"  # 저장 뒤에 데이터가 바뀌어도 저장본은 그대로
    db.session.commit()
    page = auth_client.get(f"/analysis/manual/{row.id}").get_data(as_text=True)
    assert "저장본 <b>11월 해외영업용</b>" in page and "호주 법인 인턴" in page and "제목을 바꾼 인턴" not in page
    auth_client.post(f"/analysis/manual/{row.id}/delete")
    assert db.session.query(StrengthManual).count() == 0


def test_manual_empty_cannot_be_saved(auth_client, user):
    _exp(user, "미분석", analyzed=False)
    page = auth_client.post("/analysis/manual/save", follow_redirects=True).get_data(as_text=True)
    assert "아직 담을 강점이 없어요" in page and db.session.query(StrengthManual).count() == 0


def test_manual_is_private(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    row = StrengthManual(user_id=b.id, name="B의 설명서", data_json=json.dumps({"strengths": []}))
    db.session.add(row)
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/analysis/manual/{row.id}").status_code == 404
    assert client.post(f"/analysis/manual/{row.id}/delete").status_code == 404
    assert "B의 설명서" not in client.get("/analysis/manual").get_data(as_text=True)
