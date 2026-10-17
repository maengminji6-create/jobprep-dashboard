"""자격증 추가와 자소서 어필 코멘트(AI는 가짜로 대체 — 테스트에서 실제 API를 부르지 않음)."""
from app.experiences.models import Experience, ExperienceComment
from app.extensions import db

from .conftest import login, make_user


def _exp(user, **kw):
    e = Experience(user_id=user.id, title=kw.pop("title", "포워딩 인턴"), category="인턴·실무",
                   role="FCL 부킹과 선적 스케줄 관리", content="운임 견적 비교", strengths="", keywords="꼼꼼함",
                   reflection="", **kw)
    db.session.add(e)
    db.session.commit()
    return e


def test_add_and_update_certificate(auth_client, user):
    auth_client.post("/experiences/certificate", data={"cert_name": "TOEIC", "cert_score": "880", "cert_date": "2025.01"})
    auth_client.post("/experiences/certificate", data={"cert_name": "toeic", "cert_score": "920", "cert_date": "2025.06"})
    from app.experiences.models import Certificate
    certs = db.session.query(Certificate).filter_by(user_id=user.id).all()
    assert len(certs) == 1
    assert certs[0].acquired == "2025.06" and certs[0].score == "920"
    assert db.session.query(Experience).filter_by(user_id=user.id).count() == 0  # 경험과 따로 저장
    page = auth_client.get("/experiences/?role=overseas_sales").get_data(as_text=True)
    assert "자격증·어학" in page and "TOEIC" in page and "외국어 능력" in page


def test_rule_comment_without_api_key(auth_client, user):
    e = _exp(user)
    page = auth_client.get("/experiences/?role=forwarding").get_data(as_text=True)
    assert "기본 코멘트" in page and "AI 코멘트 받기" not in page
    r = auth_client.post("/experiences/comments", data={"exp_id": e.id, "role": "forwarding"}, follow_redirects=True)
    assert "OPENAI_API_KEY" in r.get_data(as_text=True)
    assert db.session.query(ExperienceComment).count() == 0


def test_ai_comment_saved_and_marked_stale(app, auth_client, user, monkeypatch):
    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    calls = []

    def fake(items, role_name):
        calls.append((len(items), role_name))
        return {exp.id: {"id": exp.id, "summary": "포워딩 실무와 바로 연결돼요", "appeal_points": ["부킹 흐름 이해"],
                         "essay_question": "직무 역량", "opening_sentence": "저는 FCL 부킹을…",
                         "improve": "처리 건수를 적어 보세요"} for exp, _ in items}
    monkeypatch.setattr(ai_client, "comment_experiences", fake)

    e = _exp(user)
    r = auth_client.post("/experiences/comments", data={"exp_id": e.id, "role": "forwarding"}, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert calls == [(1, "국제물류·포워딩")]
    assert "AI 코멘트 1개" in page and "포워딩 실무와 바로 연결돼요" in page and "AI 코멘트" in page
    c = db.session.query(ExperienceComment).one()
    assert c.role_code == "forwarding" and c.data["appeal_points"] == ["부킹 흐름 이해"]

    # 다시 받으면 같은 행을 갱신(중복 저장 없음)
    auth_client.post("/experiences/comments", data={"exp_id": e.id, "role": "forwarding"})
    assert db.session.query(ExperienceComment).count() == 1

    # 경험을 고치면 '바뀌었어요' 표시
    auth_client.post("/experiences/save", data={"target_id": e.id, "strengths": "운임 8% 절감"})
    page = auth_client.get("/experiences/?role=forwarding").get_data(as_text=True)
    assert "경험 내용이 바뀌었어요" in page

    # 경험을 지우면 코멘트도 함께 삭제
    auth_client.post(f"/experiences/{e.id}/delete")
    assert db.session.query(ExperienceComment).count() == 0


def test_cannot_request_comment_for_others_experience(app, client, monkeypatch):
    app.config["OPENAI_API_KEY"] = "test-key"
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    e = _exp(b)
    login(client, a.email)
    assert client.post("/experiences/comments", data={"exp_id": e.id, "role": "forwarding"}).status_code == 404


def _upload_xlsx(client, rows, name="a.xlsx"):
    import io
    from openpyxl import Workbook
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return client.post("/experiences/upload", data={"file": (io.BytesIO(buf.getvalue()), name)},
                       content_type="multipart/form-data", follow_redirects=True)


def test_delete_upload_and_reset_all(auth_client, user):
    from app.experiences.models import ExperienceUpload
    _upload_xlsx(auth_client, [["경험명", "나의 역할"], ["포워딩 인턴", "FCL 부킹"], ["무역사무 알바", "인보이스 작성"]])
    _exp(user, title="직접 넣은 경험")
    up = db.session.query(ExperienceUpload).filter_by(user_id=user.id).one()
    page = auth_client.get("/experiences/").get_data(as_text=True)
    assert "a.xlsx" in page and "지금 남은 경험 2개" in page

    auth_client.post(f"/experiences/uploads/{up.id}/delete")
    titles = [e.title for e in db.session.query(Experience).filter_by(user_id=user.id)]
    assert titles == ["직접 넣은 경험"]
    assert db.session.query(ExperienceUpload).count() == 0

    r = auth_client.post("/experiences/reset", data={"confirm": "아니"}, follow_redirects=True)
    assert "라고 적어야 지울 수 있어요" in r.get_data(as_text=True)
    assert db.session.query(Experience).count() == 1
    auth_client.post("/experiences/reset", data={"confirm": "삭제"})
    assert db.session.query(Experience).count() == 0


def test_cannot_delete_others_upload_or_reset_theirs(app, client):
    from app.experiences.models import ExperienceUpload
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    up = ExperienceUpload(user_id=b.id, filename="b.xlsx", item_count=1)
    db.session.add(up)
    db.session.commit()
    _exp(b, upload_id=up.id)
    login(client, a.email)
    assert client.post(f"/experiences/uploads/{up.id}/delete").status_code == 404
    client.post("/experiences/reset", data={"confirm": "삭제"})
    assert db.session.query(Experience).filter_by(user_id=b.id).count() == 1


def test_signup_can_be_closed(app, client):
    app.config["ALLOW_SIGNUP"] = False
    assert "회원가입" not in client.get("/auth/login").get_data(as_text=True)
    r = client.post("/auth/register", data={"email": "x@test.com", "name": "x", "password": "password123"})
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    from app.auth.models import User
    assert db.session.query(User).filter_by(email="x@test.com").count() == 0
