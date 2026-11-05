"""면접 준비실: 공고·경험 근거의 예상 질문 · 답변 저장·점검 · AI 질문/피드백 검증 · 복기 · 일정·활용 내역 연동."""
from datetime import date, timedelta

from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db
from app.interview.models import InterviewQuestion, InterviewSession
from app.interview.services import check_ai_questions, check_answer

POSTING = ("자격요건\n- 해외 바이어 응대 경험자\n- 수출 오더 관리 경험\n우대사항\n- 엑셀 리포트 작성 가능자\n"
           "담당업무\n- 수출 오더 관리와 바이어 메일 응대 업무 전반")


def _setup(auth_client, user):
    e = Experience(user_id=user.id, title="LG 호주 법인 인턴", category="인턴·실무",
                   role="현지 바이어 메일 응대와 수출 오더 관리", content="엑셀 리포트 정리, 클레임 갈등을 조율",
                   strengths="", keywords="", reflection="")
    db.session.add(e)
    db.session.commit()
    auth_client.post("/experiences/posting", data={"mode": "text", "posting_text": POSTING, "company": "한빛무역",
                                                   "save_now": "1"})
    return e, db.session.query(PostingAnalysis).one()


def test_rule_questions_have_basis_and_recommended_experiences(auth_client, user):
    e, pa = _setup(auth_client, user)
    page = auth_client.post("/interview/new", data={"posting_id": pa.id}, follow_redirects=True).get_data(as_text=True)
    s = db.session.query(InterviewSession).one()
    assert s.company == "한빛무역" and s.title == "한빛무역 면접"
    qs = {q.question: q for q in s.questions}
    req = qs["공고에 '해외 바이어 응대 경험자'라고 되어 있는데, 이와 관련해 직접 해 본 경험이 있나요?"]
    assert req.category == "직무 역량" and req.basis.startswith("공고 자격요건") and e.id in req.exp_id_list
    assert {q.category for q in s.questions} >= {"직무 역량", "경험", "문제 해결", "지원 동기"}
    assert all(q.basis for q in s.questions)  # 모든 질문에 근거
    assert "근거 · 공고 자격요건" in page and "STAR 뼈대 넣기" in page
    auth_client.post(f"/interview/{s.id}/generate")
    db.session.refresh(s)
    assert len(s.questions) == len(qs)  # 같은 질문은 다시 넣지 않음


def test_need_company_or_posting(auth_client, user):
    r = auth_client.post("/interview/new", data={}, follow_redirects=True)
    assert "회사명을 적거나 공고를 골라" in r.get_data(as_text=True)


def test_save_answer_and_rule_check(auth_client, user):
    e, pa = _setup(auth_client, user)
    auth_client.post("/interview/new", data={"posting_id": pa.id})
    q = db.session.query(InterviewQuestion).filter(InterviewQuestion.category == "경험").first()
    auth_client.post(f"/interview/q/{q.id}", data={"answer": "LG 호주 법인 인턴에서 바이어 메일을 응대했습니다. 그 결과 응답이 빨라졌습니다.",
                                                   "exp_ids": [str(e.id), ""], "asked": "1", "self_note": "꼬리 질문: 어려웠던 점",
                                                   "action": "check"})
    db.session.refresh(q)
    assert q.asked and q.self_note and q.exp_id_list == [e.id]
    items = {i["text"][:6]: i["ok"] for i in q.feedback["rule"]["items"]}
    assert any(k.startswith("길이") for k in items) and q.feedback["rule"]["length"] > 0
    texts = [i["text"] for i in q.feedback["rule"]["items"]]
    assert "내가 직접 한 행동이 드러나요." in texts and "결과·배운 점이 들어 있어요." in texts
    assert any("LG 호주 법인 인턴" in t for t in texts)  # 고른 경험이 답변에 드러남
    edit = auth_client.get(f"/experiences/{e.id}/edit").get_data(as_text=True)
    assert "면접 답변" in edit  # 경험 활용 내역에 연결


def test_check_answer_rules():
    assert not check_answer("", [])["items"][0]["ok"]
    fb = check_answer("열심히 하겠습니다.", [])
    oks = {i["text"]: i["ok"] for i in fb["items"]}
    assert not any(v for k, v in oks.items() if k.startswith("길이"))
    assert any("결과나 배운 점이 없어요" in k and not v for k, v in oks.items())


def test_ai_questions_must_quote_source():
    source = "자격요건\n- 해외 바이어 응대 경험자\n내 경험: 수출 오더 관리"
    kept = check_ai_questions([{"category": "직무 역량", "question": "바이어 응대 경험은?", "basis": "해외 바이어 응대 경험자"},
                               {"category": "경험", "question": "SAP 써 봤나요?", "basis": "SAP 운영 경험"},
                               {"category": "엉뚱", "question": "오더 관리?", "basis": "수출 오더 관리"}], source)
    assert [k["question"] for k in kept] == ["바이어 응대 경험은?", "오더 관리?"] and kept[1]["category"] == "기타"


def test_ai_paths_with_fake_ai(app, auth_client, user, monkeypatch):
    from app.integrations import ai_client
    e, pa = _setup(auth_client, user)
    app.config["OPENAI_API_KEY"] = "test-key"
    monkeypatch.setattr(ai_client, "interview_questions", lambda posting, exps, company, role: [
        {"category": "직무 역량", "question": "엑셀로 어떤 리포트를 만들었나요?", "basis": "엑셀 리포트 작성 가능자"},
        {"category": "경험", "question": "SAP 경험은?", "basis": "SAP 운영 3년"}])
    page = auth_client.post("/interview/new", data={"posting_id": pa.id, "use_ai": "1"}, follow_redirects=True).get_data(as_text=True)
    s = db.session.query(InterviewSession).one()
    ai_qs = [q for q in s.questions if q.source == "ai"]
    assert [q.question for q in ai_qs] == ["엑셀로 어떤 리포트를 만들었나요?"] and "근거 문장을 공고·경험에서 찾을 수 없어 뺐어요" in page
    monkeypatch.setattr(ai_client, "interview_feedback", lambda q, a: {
        "good": [{"quote": "바이어 메일을 응대", "why": "구체적"}],
        "improve": [{"quote": "", "how": "x"}], "follow_up": ["가장 어려운 바이어는?"]})
    q = ai_qs[0]
    auth_client.post(f"/interview/q/{q.id}", data={"answer": "바이어 메일을 응대했습니다.", "action": "check", "use_ai": "1"})
    db.session.refresh(q)
    assert q.feedback["ai"]["follow_up"] == ["가장 어려운 바이어는?"]


def test_review_date_shows_on_schedule(auth_client, user):
    _e, pa = _setup(auth_client, user)
    auth_client.post("/interview/new", data={"posting_id": pa.id})
    s = db.session.query(InterviewSession).one()
    day = date.today() + timedelta(days=2)
    auth_client.post(f"/interview/{s.id}/review", data={"interview_date": day.isoformat(), "review": ""})
    page = auth_client.get(f"/schedule/?m={day.year}-{day.month:02d}").get_data(as_text=True)
    assert "한빛무역 면접" in page and "면접 준비 보기" in page
    auth_client.post(f"/interview/{s.id}/review", data={"interview_date": day.isoformat(), "review": "분위기 좋았음"})
    db.session.refresh(s)
    assert s.review == "분위기 좋았음"


def test_add_and_delete_question_and_session(auth_client, user):
    auth_client.post("/interview/new", data={"company": "A사"})
    s = db.session.query(InterviewSession).one()
    auth_client.post(f"/interview/{s.id}/questions", data={"category": "기타", "question": "최근 무역 이슈는?"})
    q = db.session.query(InterviewQuestion).filter_by(question="최근 무역 이슈는?").one()
    assert q.source == "manual"
    auth_client.post(f"/interview/q/{q.id}/delete")
    assert not db.session.query(InterviewQuestion).filter_by(question="최근 무역 이슈는?").count()
    auth_client.post(f"/interview/{s.id}/delete")
    assert not db.session.query(InterviewSession).count() and not db.session.query(InterviewQuestion).count()
