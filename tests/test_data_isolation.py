"""가장 중요한 테스트: 사용자 A는 사용자 B의 데이터를 보거나 고칠 수 없다."""
from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db

from .conftest import login, make_user


def test_user_cannot_access_others_data(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    exp = Experience(user_id=b.id, title="B의 경험", content="비밀")
    pa = PostingAnalysis(user_id=b.id, title="B의 공고", result_json="{}")
    db.session.add_all([exp, pa])
    db.session.commit()

    login(client, a.email)
    assert client.get(f"/experiences/{exp.id}/edit").status_code == 404
    assert client.post(f"/experiences/{exp.id}/delete").status_code == 404
    assert client.get(f"/experiences/posting/{pa.id}").status_code == 404
    # 남의 경험에 내용 덧붙이기 시도
    assert client.post("/experiences/save", data={"target_id": exp.id, "role": "끼워넣기"}).status_code == 404
    # 같은 제목으로 저장해도 남의 경험과 합쳐지지 않고 내 경험이 새로 생김
    client.post("/experiences/save", data={"title": "B의 경험", "role": "내 역할"})
    db.session.refresh(exp)
    assert "내 역할" not in (exp.role or "")

    for url in ("/experiences/", "/experiences/manage"):
        assert "비밀" not in client.get(url).get_data(as_text=True)


def test_user_cannot_touch_others_schedule(app, client):
    from datetime import date

    from app.schedule.models import ScheduleEvent
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    ev = ScheduleEvent(user_id=b.id, title="B의 면접", date=date.today())
    pb = PostingAnalysis(user_id=b.id, title="B의 공고", result_json="{}", deadline=date.today())
    db.session.add_all([ev, pb])
    db.session.commit()
    login(client, a.email)
    assert client.post(f"/schedule/{ev.id}/edit", data={"title": "x", "date": "2026-01-01"}).status_code == 404
    assert client.post(f"/schedule/{ev.id}/check", data={"all": "1"}).status_code == 404
    assert client.post(f"/schedule/{ev.id}/delete").status_code == 404
    assert client.get(f"/schedule/?edit={ev.id}").status_code == 404
    assert client.post(f"/schedule/from-posting/{pb.id}").status_code == 404
    # 남의 공고를 내 일정에 연결할 수 없음
    assert client.post("/schedule/new", data={"title": "x", "date": "2026-01-01", "posting_id": pb.id}).status_code == 404
    page = client.get("/schedule/").get_data(as_text=True)
    assert "B의 면접" not in page and "B의 공고" not in page


def test_user_cannot_touch_others_interview(app, client):
    from app.interview.models import InterviewQuestion, InterviewSession
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    eb = Experience(user_id=b.id, title="B의 경험")
    pb = PostingAnalysis(user_id=b.id, title="B의 공고", result_json="{}")
    sb = InterviewSession(user_id=b.id, title="B의 면접")
    db.session.add_all([eb, pb, sb])
    db.session.commit()
    qb = InterviewQuestion(user_id=b.id, session_id=sb.id, question="B의 질문")
    sa = InterviewSession(user_id=a.id, title="A의 면접")
    db.session.add_all([qb, sa])
    db.session.commit()
    qa = InterviewQuestion(user_id=a.id, session_id=sa.id, question="A의 질문")
    db.session.add(qa)
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/interview/{sb.id}").status_code == 404
    assert client.post(f"/interview/{sb.id}/generate").status_code == 404
    assert client.post(f"/interview/{sb.id}/questions", data={"question": "x"}).status_code == 404
    assert client.post(f"/interview/{sb.id}/review", data={"review": "x"}).status_code == 404
    assert client.post(f"/interview/{sb.id}/delete").status_code == 404
    assert client.post(f"/interview/q/{qb.id}", data={"answer": "x"}).status_code == 404
    assert client.post(f"/interview/q/{qb.id}/delete").status_code == 404
    assert client.post("/interview/new", data={"posting_id": pb.id}).status_code == 404
    # 내 질문 답변에 남의 경험을 연결할 수 없음
    assert client.post(f"/interview/q/{qa.id}", data={"answer": "x", "exp_ids": [str(eb.id)]}).status_code == 404
    assert "B의 면접" not in client.get("/interview/").get_data(as_text=True)


def test_user_cannot_touch_others_analysis_or_links(app, client):
    import json

    from app.analysis.models import ExperienceAnalysis, StrengthLink
    from app.strengths.models import StrengthProfile
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    eb = Experience(user_id=b.id, title="B의 경험", star_action="B만의 비밀 행동")
    pb = StrengthProfile(user_id=b.id, filename="b.pdf",
                         parsed_json=json.dumps({"strengths": [{"name": "주도", "rank": 1}]}))
    ea = Experience(user_id=a.id, title="A의 경험")
    pa = StrengthProfile(user_id=a.id, filename="a.pdf",
                         parsed_json=json.dumps({"strengths": [{"name": "주도", "rank": 1}]}))
    db.session.add_all([eb, pb, ea, pa])
    db.session.commit()
    db.session.add(ExperienceAnalysis(user_id=b.id, experience_id=eb.id, content_hash="x",
                                      data_json=json.dumps({"summary": "B의 분석 요약"}, ensure_ascii=False)))
    lb = StrengthLink(user_id=b.id, profile_id=pb.id, strength_name="주도", experience_id=eb.id, quote="B만의 비밀 행동")
    db.session.add(lb)
    db.session.commit()
    login(client, a.email)
    app.config["OPENAI_API_KEY"] = "test-key"
    for url in (f"/analysis/links/{lb.id}/edit", f"/analysis/links/{lb.id}/remove", f"/analysis/links/{lb.id}/restore"):
        assert client.post(url, data={"reason": "x"}).status_code == 404, url
    assert client.post("/analysis/run", data={"exp_id": eb.id}).status_code == 404
    # 내 강점에 남의 경험을 연결할 수 없음
    assert client.post("/analysis/links/new", data={"strength": "주도", "exp_id": eb.id}).status_code == 404
    page = client.get("/analysis/").get_data(as_text=True)
    assert "B의 분석 요약" not in page and "B만의 비밀 행동" not in page and "B의 경험" not in page


def test_user_cannot_edit_others_strength_profile(app, client):
    import json

    from app.strengths.models import StrengthProfile
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    pb = StrengthProfile(user_id=b.id, filename="b.pdf", extracted_text="B 비밀 결과지",
                         parsed_json=json.dumps({"strengths": [{"name": "비밀강점"}]}, ensure_ascii=False))
    db.session.add(pb)
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/strengths/{pb.id}/edit").status_code == 404
    r = client.post("/strengths/confirm", data={"profile_id": pb.id, "name": ["바꿈"], "summary": [""], "definition": [""],
                                                "orig": [""], "keep": ["1"], "was_edited": ["0"]})
    assert r.status_code == 404
    db.session.refresh(pb)
    assert pb.strengths[0]["name"] == "비밀강점"


def test_user_cannot_open_others_strength_manual(app, client):
    import json

    from app.analysis.models import StrengthManual
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    row = StrengthManual(user_id=b.id, name="B의 설명서", data_json=json.dumps({"strengths": []}))
    db.session.add(row)
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/analysis/manual/{row.id}").status_code == 404
    assert client.post(f"/analysis/manual/{row.id}/delete").status_code == 404
