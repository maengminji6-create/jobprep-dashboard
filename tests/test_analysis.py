"""AI 분석: 경험 분석(원문 인용 검증 · 5개 묶음 · 오류 안내 · 갱신 필요) · 강점 × 경험 연결(수정·해제 유지) · 통합 결과."""
import json

import pytest

from app.analysis.models import ExperienceAnalysis, StrengthLink
from app.analysis.services import clean_analysis
from app.experiences.models import Experience
from app.extensions import db
from app.integrations import ai_client
from app.strengths.models import StrengthProfile


def _exp(user, title="LG 호주 법인 인턴", **kw):
    fields = dict(category="인턴·직장 경험", organization="LG 호주 법인",
                  role="현지 바이어 영문 메일 응대와 수출 오더 관리",
                  star_action="매주 재고 리포트를 엑셀로 정리해 팀 회의에 공유했다",
                  star_result="리포트 작성 시간이 2시간에서 30분으로 줄었다", content="", strengths="", keywords="",
                  reflection="")
    fields.update(kw)
    e = Experience(user_id=user.id, title=title, **fields)
    db.session.add(e)
    db.session.commit()
    return e


def _raw(exp_id, **kw):
    raw = {"id": exp_id, "summary": "호주 법인에서 바이어 응대와 재고 리포트를 맡은 인턴 경험",
           "actions": [{"text": "재고 리포트를 매주 정리", "quote": "매주 재고 리포트를 엑셀로 정리해 팀 회의에 공유했다"}],
           "problem_solving": {"text": "", "quote": ""},
           "results": [{"text": "작성 시간 단축", "quote": "리포트 작성 시간이 2시간에서 30분으로 줄었다"}],
           "competencies": [{"name": "데이터 분석", "quote": "재고 리포트를 엑셀로 정리", "reason": "엑셀로 데이터를 정리"},
                            {"name": "글로벌 커뮤니케이션", "quote": "현지 바이어 영문 메일 응대", "reason": "영문 응대"}],
           "needs_info": []}
    raw.update(kw)
    return raw


@pytest.fixture
def ai_on(app):
    app.config["OPENAI_API_KEY"] = "test-key"
    return app


def test_clean_keeps_only_quoted_items_and_blocks_invented_numbers(app, user):
    e = _exp(user)
    raw = _raw(e.id, summary="매출 15% 증가에 기여한 인턴",  # 원문에 없는 15 → 요약을 비움
               actions=[{"text": "재고 정리", "quote": "매주 재고 리포트를 엑셀로 정리해 팀 회의에 공유했다"},
                        {"text": "신규 바이어 10곳 발굴", "quote": "신규 바이어 10곳을 발굴했다"}],  # 원문에 없음 → 뺌
               results=[{"text": "작성 시간이 75% 줄었다", "quote": "리포트 작성 시간이 2시간에서 30분으로 줄었다"}],
               competencies=[{"name": "데이터 분석", "quote": "재고 리포트를 엑셀로 정리", "reason": ""},
                             {"name": "데이터 분석", "quote": "매주 재고 리포트", "reason": ""},
                             {"name": "없는 역량", "quote": "현지 바이어", "reason": ""}])
    d = clean_analysis(raw, e)
    assert d["summary"] == ""
    assert [a["field"] for a in d["actions"]] == ["행동·해결 과정 (A)"]
    assert d["results"][0]["text"] == "리포트 작성 시간이 2시간에서 30분으로 줄었다"  # 75%는 원문에 없어 인용으로 대체
    assert d["competencies"] == [{"name": "데이터 분석", "level": "충분", "quotes": [
        {"quote": "재고 리포트를 엑셀로 정리", "field": "행동·해결 과정 (A)", "reason": ""},
        {"quote": "매주 재고 리포트", "field": "행동·해결 과정 (A)", "reason": ""}]}]
    assert d["dropped"] == 3  # 요약 · 없는 행동 · 목록에 없는 역량


def test_missing_result_is_marked_needs_info(app, user):
    e = _exp(user, star_result="")
    d = clean_analysis(_raw(e.id, results=[]), e)
    assert any("결과 정보 필요" in n for n in d["needs_info"])


def test_run_analyzes_five_at_a_time_and_marks_stale(ai_on, auth_client, user, monkeypatch):
    exps = [_exp(user, title=f"경험 {i}") for i in range(7)]
    calls = []

    def fake(batch, names):
        calls.append([e.id for e in batch])
        assert "데이터 분석" in names
        return {e.id: _raw(e.id) for e in batch}
    monkeypatch.setattr(ai_client, "analyze_experiences", fake)
    page = auth_client.post("/analysis/run", follow_redirects=True).get_data(as_text=True)
    assert len(calls[0]) == 5 and "경험 5개를 분석했어요" in page and "남은 경험 2개" in page
    auth_client.post("/analysis/run")
    assert len(calls[1]) == 2 and db.session.query(ExperienceAnalysis).count() == 7

    page = auth_client.get("/analysis/").get_data(as_text=True)
    assert "“매주 재고 리포트를 엑셀로 정리해 팀 회의에 공유했다”" in page and "분석 완료 <b>7</b>" in page
    assert "데이터 분석" in page and "근거 보통" in page  # 인용 1개 → 보통(2개 이상이어야 충분)

    exps[0].star_action = "바뀐 행동 내용으로 다시 적었다"  # 내용이 바뀌면 '갱신 필요', 다시 누르면 그 경험만
    db.session.commit()
    assert "내용이 바뀌었어요" in auth_client.get("/analysis/").get_data(as_text=True)
    auth_client.post("/analysis/run")
    assert calls[2] == [exps[0].id]


def test_ai_error_is_shown_and_nothing_saved(ai_on, auth_client, user, monkeypatch):
    _exp(user)

    def boom(batch, names):
        raise ai_client.AiError("요청이 많아 잠시 막혔어요.")
    monkeypatch.setattr(ai_client, "analyze_experiences", boom)
    page = auth_client.post("/analysis/run", follow_redirects=True).get_data(as_text=True)
    assert "분석하지 못했어요. 요청이 많아 잠시 막혔어요." in page
    assert db.session.query(ExperienceAnalysis).count() == 0


def test_without_ai_key_page_says_so(auth_client, user):
    _exp(user)
    page = auth_client.post("/analysis/run", follow_redirects=True).get_data(as_text=True)
    assert "OPENAI_API_KEY" in page and db.session.query(ExperienceAnalysis).count() == 0


def _profile(user, names=("신중함", "주도", "창의성")):
    parsed = {"strengths": [{"name": n, "summary": f"{n} 설명", "rank": i + 1} for i, n in enumerate(names)]}
    p = StrengthProfile(user_id=user.id, filename="강점.pdf", parsed_json=json.dumps(parsed, ensure_ascii=False))
    db.session.add(p)
    db.session.commit()
    return p


def test_rule_links_then_edit_and_remove_survive_regenerate(auth_client, user):
    e = _exp(user, title="AX마스터 팀장", star_action="팀장으로 회의를 이끌고 마감 전 체크리스트로 꼼꼼하게 점검했다")
    p = _profile(user)
    page = auth_client.post("/analysis/links/generate", data={"mode": "rule"}, follow_redirects=True).get_data(as_text=True)
    links = {lk.strength_name: lk for lk in db.session.query(StrengthLink).all()}
    assert set(links) >= {"신중함", "주도"} and all(lk.origin == "rule" for lk in links.values())
    assert all(lk.evidence in ("보통", "약함") for lk in links.values())  # 단어 단서로는 '충분'을 주지 않음
    assert "단어 단서" in page and "연결된 경험 없음" in page  # 창의성은 근거 없음

    careful, lead = links["신중함"], links["주도"]
    r = auth_client.post(f"/analysis/links/{careful.id}/edit",
                         data={"quote": "없는 문장을 넣음", "reason": "x", "evidence": "충분"}, follow_redirects=True)
    assert "경험에 적힌 문장 그대로" in r.get_data(as_text=True)  # 원문에 없는 근거는 저장 안 함
    auth_client.post(f"/analysis/links/{careful.id}/edit",
                     data={"quote": "마감 전 체크리스트로 꼼꼼하게 점검했다", "reason": "마감 전 점검", "evidence": "충분"})
    auth_client.post(f"/analysis/links/{lead.id}/remove")
    auth_client.post("/analysis/links/generate", data={"mode": "rule"})
    db.session.expire_all()
    careful, lead = db.session.get(StrengthLink, careful.id), db.session.get(StrengthLink, lead.id)
    assert careful.edited and careful.reason == "마감 전 점검" and careful.evidence == "충분"
    assert lead.removed  # 해제한 연결은 다시 자동 연결해도 되살아나지 않음
    page = auth_client.get("/analysis/").get_data(as_text=True)
    assert "되살리기" in page
    auth_client.post(f"/analysis/links/{lead.id}/restore")
    db.session.refresh(lead)
    assert not lead.removed
    assert p.id == careful.profile_id


def test_ai_links_drop_unquoted_and_integrated_result(ai_on, auth_client, user, monkeypatch):
    e1 = _exp(user, title="AX마스터 팀장", star_action="팀장으로 회의를 이끌었다")
    e2 = _exp(user, title="카페 아르바이트", star_action="손님 클레임을 차분히 응대했다", star_result="", role="")
    _profile(user)
    db.session.add(ExperienceAnalysis(user_id=user.id, experience_id=e2.id, content_hash=e2.content_hash,
                                      data_json=json.dumps({"competencies": [{"name": "고객 응대", "level": "보통", "quotes": [
                                          {"quote": "손님 클레임을 차분히 응대했다", "field": "행동", "reason": ""}]}],
                                          "needs_info": ["결과 정보 필요"], "results": []}, ensure_ascii=False)))
    db.session.commit()

    def fake(strengths, exps):
        return [{"strength": "주도", "experience_id": e1.id, "quote": "팀장으로 회의를 이끌었다", "reason": "회의를 이끔",
                 "evidence": "충분"},
                {"strength": "신중함", "experience_id": e1.id, "quote": "지어낸 문장", "reason": "", "evidence": "충분"},
                {"strength": "없는강점", "experience_id": e1.id, "quote": "팀장으로", "reason": "", "evidence": "보통"},
                {"strength": "창의성", "experience_id": 999, "quote": "팀장으로", "reason": "", "evidence": "보통"}]
    monkeypatch.setattr(ai_client, "link_strengths_to_experiences", fake)
    auth_client.post("/analysis/links/generate", data={"mode": "ai"})
    links = db.session.query(StrengthLink).all()
    assert [(lk.strength_name, lk.origin, lk.evidence) for lk in links] == [("주도", "ai", "충분")]

    page = auth_client.get("/analysis/").get_data(as_text=True)
    integrated = page[page.index('id="integrated"'):]
    assert "주도" in integrated.split("진단에는 있지만")[0]  # 일치
    assert "신중함" in integrated and "창의성" in integrated  # 근거 부족
    assert "고객 응대" in integrated and "카페 아르바이트" in integrated  # 진단과 연결 안 된 경험 역량 · 구체화할 경험


def test_manual_link_needs_quote_from_experience(auth_client, user):
    e = _exp(user)
    _profile(user)
    auth_client.post("/analysis/links/new", data={"strength": "주도", "exp_id": e.id, "quote": "", "reason": "직접",
                                                  "evidence": "충분"})
    lk = db.session.query(StrengthLink).one()
    assert lk.origin == "user" and lk.evidence == "약함"  # 근거 문장 없이 만든 연결은 확정하지 않음
    r = auth_client.post("/analysis/links/new", data={"strength": "없는강점", "exp_id": e.id}, follow_redirects=True)
    assert "연결할 강점을 골라 주세요" in r.get_data(as_text=True)


def test_deleting_experience_removes_its_analysis_and_links(auth_client, user):
    e = _exp(user)
    p = _profile(user)
    db.session.add(ExperienceAnalysis(user_id=user.id, experience_id=e.id, content_hash=e.content_hash, data_json="{}"))
    db.session.add(StrengthLink(user_id=user.id, profile_id=p.id, strength_name="주도", experience_id=e.id))
    db.session.commit()
    auth_client.post(f"/experiences/{e.id}/delete")
    assert db.session.query(ExperienceAnalysis).count() == 0 and db.session.query(StrengthLink).count() == 0
