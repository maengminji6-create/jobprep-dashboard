"""자소서 작성 보조: 문항 유형 · 문항별 경험 추천(근거) · STAR 뼈대 · AI 초안(지어낸 숫자 차단) · 버전 · PDF."""
import json

from app.applications.models import ApplicationRecord, ApplicationVersion
from app.applications.services import check_answer_draft, question_type, star_outline
from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db

from .conftest import login, make_user

POSTING = ("자격요건\n- 해외 바이어 응대 경험자\n- 수출 오더 관리 경험\n우대사항\n- 엑셀 리포트 작성 가능자\n"
           "담당업무\n- 수출 오더 관리와 바이어 메일 응대 업무 전반")


def _exp(user, title="LG 호주 법인 인턴", **kw):
    fields = dict(category="인턴·실무", role="현지 바이어 메일 응대와 수출 오더 관리", content="엑셀 리포트 정리",
                  strengths="", keywords="", reflection="", star_situation="인턴 2개월 차", star_task="재고 보고가 늦음",
                  star_action="엑셀로 주간 리포트를 만들었다", star_result="")
    fields.update(kw)
    e = Experience(user_id=user.id, title=title, **fields)
    db.session.add(e)
    db.session.commit()
    return e


def test_question_type():
    assert question_type("지원 동기와 입사 후 포부를 적어 주세요") == "지원동기·입사 후 포부"
    assert question_type("팀에서 갈등을 해결한 경험") == "협업·갈등 해결"
    assert question_type("가장 큰 도전과 극복 과정") == "도전·성장 경험"
    assert question_type("직무 관련 역량") == "직무역량·전문성"


def test_star_outline_uses_only_my_text(app, user):
    e = _exp(user)
    out = star_outline(e)
    assert out.startswith("[LG 호주 법인 인턴]") and "상황: 인턴 2개월 차" in out
    assert "행동: 엑셀로 주간 리포트를 만들었다" in out and "결과: (여기에 결과를 적어 주세요)" in out


def test_check_answer_draft_drops_invented_numbers():
    text, notes = check_answer_draft("저는 바이어 메일을 응대했습니다. 그 결과 매출이 30% 늘었습니다. 엑셀 리포트를 주 1회 만들었습니다.",
                                     "바이어 메일 응대, 엑셀 리포트 주 1회")
    assert "30%" not in text and "주 1회" in text and any("30" in n for n in notes)


def test_suggest_ranks_by_question_type_and_posting_support(auth_client, user):
    good = _exp(user)
    _exp(user, title="카페 아르바이트", role="음료 제조", content="", star_situation="", star_task="", star_action="")
    auth_client.post("/experiences/posting", data={"mode": "text", "posting_text": POSTING, "company": "한빛무역"})
    pa = db.session.query(PostingAnalysis).one()
    d = auth_client.get(f"/applications/suggest?q=직무 관련 역량을 적어 주세요&posting_id={pa.id}").get_json()
    assert d["type"] == "직무역량·전문성"
    assert d["items"][0]["id"] == good.id and any("공고 요건" in r for r in d["items"][0]["reasons"])
    assert "[LG 호주 법인 인턴]" in d["items"][0]["outline"]
    assert all(x["reasons"] for x in d["items"])  # 근거 없는 경험은 추천하지 않음


def test_chosen_experiences_are_saved_and_counted_as_used(auth_client, user):
    e = _exp(user)
    auth_client.post("/applications/new", data={"company": "한빛무역", "q": ["직무 역량"], "limit": [""],
                                                "a": ["엑셀로 리포트를 만들었습니다."], "exps": [f"{e.id},abc,{e.id}"]})
    rec = db.session.query(ApplicationRecord).one()
    assert rec.qa[0]["exps"] == [e.id]
    page = auth_client.get(f"/applications/{rec.id}").get_data(as_text=True)
    assert "이 자소서에 쓴 경험" in page and "LG 호주 법인 인턴" in page  # 이름이 답변에 없어도 직접 고른 경험
    edit = auth_client.get(f"/experiences/{e.id}/edit").get_data(as_text=True)
    assert "답변에 쓴 자소서 문항" in edit


def test_draft_without_key_and_with_fake_ai(app, auth_client, user, monkeypatch):
    e = _exp(user)
    r = auth_client.post("/applications/draft", data={"q": "직무 역량", "exp_ids": str(e.id)})
    assert r.status_code == 400 and "OPENAI_API_KEY" in r.get_json()["error"]
    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    assert auth_client.post("/applications/draft", data={"q": "직무 역량", "exp_ids": ""}).status_code == 400
    monkeypatch.setattr(ai_client, "draft_answer", lambda q, limit, exps, posting, role, evidence=None: {
        "answer": "저는 현지 바이어 메일을 응대했습니다. 그 결과 응답률이 80% 올랐습니다.", "missing": ["결과"]})
    d = auth_client.post("/applications/draft", data={"q": "직무 역량", "exp_ids": str(e.id)}).get_json()
    assert "바이어 메일" in d["answer"] and "80%" not in d["answer"] and d["notes"] and d["missing"] == ["결과"]
    assert d["basis"] == [] and d["role"] == "해외영업"  # 분석 전: 경험 글만 근거


def test_draft_uses_verified_analysis_and_linked_strengths(app, auth_client, user, monkeypatch):
    """AI 분석에서 확인된 역량·진단 강점 연결을 근거로 함께 넘김. 내용이 바뀐 분석·해제·약한 연결은 넘기지 않음."""
    import json

    from app.analysis.models import ExperienceAnalysis, StrengthLink
    from app.integrations import ai_client
    from app.strengths.models import StrengthProfile
    app.config["OPENAI_API_KEY"] = "test-key"
    e = _exp(user)
    db.session.add(ExperienceAnalysis(user_id=user.id, experience_id=e.id, content_hash=e.content_hash, data_json=json.dumps(
        {"competencies": [{"name": "글로벌 커뮤니케이션", "level": "보통",
                           "quotes": [{"quote": "현지 바이어 메일 응대", "field": "역할", "reason": ""}]}]}, ensure_ascii=False)))
    p = StrengthProfile(user_id=user.id, filename="강점", parsed_json=json.dumps({"strengths": [{"name": "소통"}, {"name": "주도"}]},
                                                                                 ensure_ascii=False))
    db.session.add(p)
    db.session.commit()
    db.session.add_all([StrengthLink(user_id=user.id, profile_id=p.id, strength_name="소통", experience_id=e.id,
                                     quote="현지 바이어 메일 응대", evidence="충분"),
                        StrengthLink(user_id=user.id, profile_id=p.id, strength_name="주도", experience_id=e.id,
                                     quote="현지 바이어", evidence="약함")])
    db.session.commit()
    got = {}

    def fake(q, limit, exps, posting, role, evidence=None):
        got.update(role=role, evidence=evidence)
        return {"answer": "저는 현지 바이어 메일을 응대했습니다.", "missing": []}
    monkeypatch.setattr(ai_client, "draft_answer", fake)
    auth_client.get("/jobfit/?job=trade_admin")  # 직무 연결에서 고른 직무가 기준
    d = auth_client.post("/applications/draft", data={"q": "직무 역량", "exp_ids": str(e.id)}).get_json()
    assert got["role"] == "무역사무" and d["basis"] == ["글로벌 커뮤니케이션", "소통"]
    assert got["evidence"] == [{"id": e.id, "역량": [{"이름": "글로벌 커뮤니케이션", "근거 문장": "현지 바이어 메일 응대"}],
                                "강점": [{"이름": "소통", "근거 문장": "현지 바이어 메일 응대"}]}]  # 약함(주도)은 뺌
    e.content = "내용을 고침"  # 분석 뒤에 경험이 바뀌면 그 분석은 근거로 쓰지 않음
    db.session.commit()
    auth_client.post("/applications/draft", data={"q": "직무 역량", "exp_ids": str(e.id)})
    assert got["evidence"][0]["역량"] == []


def test_versions_and_restore(auth_client, user):
    auth_client.post("/applications/new", data={"company": "A사", "q": ["Q1"], "limit": [""], "a": ["첫 답변"]})
    rec = db.session.query(ApplicationRecord).one()
    auth_client.post(f"/applications/{rec.id}/edit", data={"company": "A사", "q": ["Q1"], "limit": [""], "a": ["둘째 답변"]})
    auth_client.post(f"/applications/{rec.id}/edit", data={"company": "A사", "q": ["Q1"], "limit": [""], "a": ["둘째 답변"]})
    db.session.refresh(rec)
    assert len(rec.versions) == 1  # 답변이 같으면 버전을 또 만들지 않음
    page = auth_client.get(f"/applications/{rec.id}").get_data(as_text=True)
    assert "이전 버전" in page and "첫 답변" in page
    auth_client.post(f"/applications/{rec.id}/versions/{rec.versions[0].id}/restore")
    db.session.refresh(rec)
    assert rec.qa[0]["a"] == "첫 답변" and len(rec.versions) == 2  # 되돌리기 전 답변도 남음


def test_print_view(auth_client, user):
    auth_client.post("/applications/new", data={"company": "A사", "q": ["지원 동기"], "limit": ["500"],
                                                "a": ["첫 문단\n\n둘째 문단"]})
    rec = db.session.query(ApplicationRecord).one()
    page = auth_client.get(f"/applications/{rec.id}/print").get_data(as_text=True)
    assert "A사 자기소개서" in page and "Q1. 지원 동기" in page and "<p>첫 문단</p>" in page and "/ 500자" in page


def test_isolation_for_versions_suggest_and_draft(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    eb = _exp(b, title="B의 비밀 경험")
    rb = ApplicationRecord(user_id=b.id, company="B사", qa_json=json.dumps([{"q": "Q", "a": "B 답변"}]))
    db.session.add(rb)
    db.session.commit()
    vb = ApplicationVersion(user_id=b.id, application_id=rb.id, qa_json="[]")
    db.session.add(vb)
    db.session.commit()
    ra = ApplicationRecord(user_id=a.id, company="A사", qa_json="[]")
    db.session.add(ra)
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/applications/{rb.id}/print").status_code == 404
    assert client.post(f"/applications/{ra.id}/versions/{vb.id}/restore").status_code == 404
    assert "B의 비밀 경험" not in client.get("/applications/suggest?q=역량").get_data(as_text=True)
    app.config["OPENAI_API_KEY"] = "test-key"
    assert client.post("/applications/draft", data={"q": "Q", "exp_ids": str(eb.id)}).status_code == 404
