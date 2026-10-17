"""자소서 보관함: 저장·수정·검색·상태·공고에서 만들기·쓴 경험 찾기·비교·저장본 포함·다른 사람 접근 차단."""
import json

from app.applications.models import ApplicationRecord
from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db

from .conftest import login, make_user


def _exp(user, title, org=""):
    db.session.add(Experience(user_id=user.id, title=title, organization=org, category="인턴·실무", role="", content="",
                              strengths="", keywords="", reflection=""))
    db.session.commit()


def _new(client, company, answer, **extra):
    data = {"company": company, "position": "해외영업", "status": "제출 완료", "role_code": "overseas_sales",
            "company_info": "화장품 수출", "talent": "도전", "q": ["지원 동기", "직무 역량"], "limit": ["700", ""],
            "a": [answer, "엑셀 리포트 자동화"], **extra}
    return client.post("/applications/new", data=data, follow_redirects=True)


def test_create_view_edit_and_filter(auth_client, user):
    _exp(user, "LG 호주 법인 · 인턴(BOP CE)", "LG 호주 법인")
    r = _new(auth_client, "한빛무역", "LG 호주 법인에서 S&OP 회의에 참여하며 재고를 관리했습니다.")
    page = r.get_data(as_text=True)
    assert "한빛무역" in page and "지원 동기" in page and "이 자소서에 쓴 경험" in page and "LG 호주 법인" in page
    rec = db.session.query(ApplicationRecord).filter_by(user_id=user.id).one()
    assert [q["q"] for q in rec.qa] == ["지원 동기", "직무 역량"] and rec.qa[0]["limit"] == "700"
    assert rec.total_chars > 20

    auth_client.post(f"/applications/{rec.id}/status", data={"status": "서류 합격"})
    db.session.refresh(rec)
    assert rec.status == "서류 합격"
    assert "한빛무역" in auth_client.get("/applications/?status=서류 합격").get_data(as_text=True)
    assert "한빛무역" not in auth_client.get("/applications/?status=불합격").get_data(as_text=True).split("app-grid")[-1]
    assert "한빛무역" in auth_client.get("/applications/?q=재고").get_data(as_text=True)

    auth_client.post(f"/applications/{rec.id}/edit", data={"company": "한빛무역", "status": "면접 진행", "q": ["새 문항"],
                                                           "limit": [""], "a": ["새 답변"]})
    db.session.refresh(rec)
    assert rec.status == "면접 진행" and rec.qa == [{"q": "새 문항", "limit": "", "a": "새 답변"}]


def test_new_from_posting_prefills(auth_client, user):
    pa = PostingAnalysis(user_id=user.id, company="코스알엑스", title="글로벌 영업", url="https://example.com/p",
                         posting_text="x", result_json=json.dumps({"main_role": "overseas_sales"}))
    db.session.add(pa)
    db.session.commit()
    page = auth_client.get(f"/applications/new?posting={pa.id}").get_data(as_text=True)
    assert 'value="코스알엑스"' in page and 'value="https://example.com/p"' in page
    assert f'<option value="{pa.id}" selected' in page


def test_compare_shows_shared_experiences(auth_client, user):
    _exp(user, "AX마스터2기")
    _exp(user, "RISE")
    _new(auth_client, "A사", "AX마스터2기에서 팀장으로 일정 관리를 맡았습니다.")
    _new(auth_client, "B사", "AX마스터2기 프로젝트와 RISE 논문 경험을 살려")
    ids = [r.id for r in db.session.query(ApplicationRecord).order_by(ApplicationRecord.id)]
    page = auth_client.get(f"/applications/compare?ids={ids[0]}&ids={ids[1]}").get_data(as_text=True)
    assert "여러 지원서에 같이 쓴 경험" in page and "A사" in page and "B사" in page
    shared = page.split("여러 지원서에 같이 쓴 경험")[1].split("compare-grid")[0]
    assert "AX마스터2기" in shared and "RISE" not in shared
    r = auth_client.get(f"/applications/compare?ids={ids[0]}", follow_redirects=True)
    assert "2~3개 골라" in r.get_data(as_text=True)


def test_backup_includes_applications(auth_client, user):
    _new(auth_client, "보관할 회사", "답변")
    data = json.loads(auth_client.get("/experiences/data/export").get_data(as_text=True))
    assert data["applications"][0]["company"] == "보관할 회사"
    auth_client.post("/experiences/data/save", data={"name": "v1"})
    from app.experiences.models import Snapshot
    snap = db.session.query(Snapshot).filter_by(user_id=user.id).one()
    db.session.query(ApplicationRecord).delete()
    db.session.commit()
    auth_client.post(f"/experiences/data/{snap.id}/load", data={"parts": ["applications"]})
    assert [a.company for a in db.session.query(ApplicationRecord).filter_by(user_id=user.id)] == ["보관할 회사"]


def test_applications_are_private(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    rec = ApplicationRecord(user_id=b.id, company="B의 회사", qa_json="[]")
    other = ApplicationRecord(user_id=a.id, company="A의 회사", qa_json="[]")
    pa = PostingAnalysis(user_id=b.id, title="B 공고", posting_text="x", result_json="{}")
    db.session.add_all([rec, other, pa])
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/applications/{rec.id}").status_code == 404
    assert client.get(f"/applications/{rec.id}/edit").status_code == 404
    for url in ("edit", "status", "delete"):
        assert client.post(f"/applications/{rec.id}/{url}", data={"company": "x"}).status_code == 404, url
    assert client.get(f"/applications/compare?ids={other.id}&ids={rec.id}").status_code == 404
    assert client.get(f"/applications/new?posting={pa.id}").status_code == 404
    assert "B의 회사" not in client.get("/applications/").get_data(as_text=True)
