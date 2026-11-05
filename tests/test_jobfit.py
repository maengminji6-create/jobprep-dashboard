"""직무 연결: 직무마다 요구 역량이 다르고 · 확인됨/태그만/미확인을 나누고 · 점수 없음 · 강점 활용이 직무마다 다름."""
import json

from app.analysis.models import ExperienceAnalysis, StrengthLink
from app.core.competencies import COMPETENCY_NAMES
from app.core.job_competencies import JOBS
from app.experiences.models import Experience
from app.extensions import db
from app.strengths.models import StrengthProfile

from .conftest import login, make_user


def _analyzed(user, title, comps, **kw):
    e = Experience(user_id=user.id, title=title, category="인턴·직장 경험", star_action=f"{title}에서 한 행동", **kw)
    db.session.add(e)
    db.session.commit()
    data = {"competencies": [{"name": n, "level": "보통", "quotes": [{"quote": f"{title}에서 한 행동", "field": "행동", "reason": ""}]}
                             for n in comps]}
    db.session.add(ExperienceAnalysis(user_id=user.id, experience_id=e.id, content_hash=e.content_hash,
                                      data_json=json.dumps(data, ensure_ascii=False)))
    db.session.commit()
    return e


def test_job_table_uses_shared_competency_names():
    assert [j["name"] for j in JOBS] == ["해외영업", "구매", "무역사무", "글로벌 마케팅", "SCM·물류"]
    for j in JOBS:
        assert all(c["name"] in COMPETENCY_NAMES and c["use"] and c["gap"] for c in j["competencies"])


def test_statuses_and_results_change_by_job(auth_client, user):
    _analyzed(user, "호주 법인 인턴", ["데이터 분석", "글로벌 커뮤니케이션"])
    tagged = Experience(user_id=user.id, title="카페 아르바이트", competencies="협상·설득", related_roles="sourcing")
    db.session.add(tagged)
    db.session.commit()

    sales = auth_client.get("/jobfit/?job=overseas_sales").get_data(as_text=True)
    assert "필요 역량 6개 중 <b>1개</b>" in sales  # 글로벌 커뮤니케이션만(데이터 분석은 해외영업 요구 역량 아님)
    assert "“호주 법인 인턴에서 한 행동”" in sales and "일반 기준" in sales
    assert "적합도" not in sales and "점" not in sales.split("필요 역량")[1].split("</p>")[0]  # 점수 없음

    buy = auth_client.get("/jobfit/?job=sourcing").get_data(as_text=True)
    assert "필요 역량 6개 중 <b>1개</b>" in buy  # 구매에서는 데이터 분석이 확인됨
    assert "견적·원가를 비교하고" in buy  # 같은 역량이라도 이 직무에서의 쓰임
    assert "태그만 단 경험" in buy and "카페 아르바이트" in buy  # 협상·설득은 태그뿐 → 확정 안 함
    assert "내가 이 직무와 관련 있다고 표시한 경험" in buy
    # 직무를 기억: 다음에 그냥 열면 구매
    assert "필요 역량 6개 중 <b>1개</b>" in auth_client.get("/jobfit/").get_data(as_text=True)
    assert 'class="chip-link on" aria-current=page>구매' in auth_client.get("/jobfit/").get_data(as_text=True)


def test_strength_usage_differs_by_job(auth_client, user):
    e = _analyzed(user, "무역학회 리서치", ["시장 조사·분석", "데이터 분석"])
    p = StrengthProfile(user_id=user.id, filename="강점.pdf",
                        parsed_json=json.dumps({"strengths": [{"name": "분석력", "rank": 1}, {"name": "주도", "rank": 2}]},
                                               ensure_ascii=False))
    db.session.add(p)
    db.session.commit()
    db.session.add(StrengthLink(user_id=user.id, profile_id=p.id, strength_name="분석력", experience_id=e.id,
                                quote="무역학회 리서치에서 한 행동", evidence="보통"))
    db.session.commit()
    sales = auth_client.get("/jobfit/?job=overseas_sales").get_data(as_text=True)
    buy = auth_client.get("/jobfit/?job=sourcing").get_data(as_text=True)
    sales_s, buy_s = sales[sales.index('id="strengths"'):], buy[buy.index('id="strengths"'):]
    assert "수출 대상 국가와 경쟁사를 조사" in sales_s  # 해외영업: 수출시장 분석
    assert "원자재 시세와 공급 시장 동향" in buy_s and "견적·원가를 비교" in buy_s  # 구매: 원가·공급 시장 분석
    assert "연결된 경험이 없어" in sales_s  # 주도는 연결 없음 → 활용을 말하지 않음


def test_no_analysis_shows_guidance(auth_client, user):
    db.session.add(Experience(user_id=user.id, title="미분석 경험"))
    db.session.commit()
    page = auth_client.get("/jobfit/?job=trade_admin").get_data(as_text=True)
    assert "아직 AI로 분석한 경험이 없어서" in page and "필요 역량 6개 중 <b>0개</b>" in page
    assert "아직 경험에서 확인되지 않아요" in page


def test_jobfit_shows_only_my_data(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    _analyzed(b, "B의 비밀 인턴", ["글로벌 커뮤니케이션"])
    login(client, a.email)
    page = client.get("/jobfit/?job=overseas_sales").get_data(as_text=True)
    assert "B의 비밀 인턴" not in page and "필요 역량 6개 중 <b>0개</b>" in page
