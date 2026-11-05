"""공고 관리: 지원 상태 8단계 · 마감일(D-day) · 같은 공고 중복 확인 · 지원 기록과 상태 연동."""
import io
from datetime import date, timedelta

from app.applications.models import ApplicationRecord
from app.core.job_status import normalize, urgency
from app.experiences.models import PostingAnalysis
from app.experiences.posting_extract import guess_deadline, normalize_url
from app.extensions import db

from .conftest import login, make_user
from .test_posting_inputs import _exp

POSTING = ("한빛무역 해외영업 신입 채용\n담당업무\n- 해외 바이어 발굴 및 수출 오더 관리\n자격요건\n- 비즈니스 영어 가능자\n"
           "우대사항\n- 무역영어 자격 보유자\n접수기간: 2026.10.20 ~ 2026.11.13")


def _text(client, text=POSTING, **extra):
    return client.post("/experiences/posting", data={"mode": "text", "posting_text": text, "company": "한빛무역", **extra},
                       follow_redirects=True)


def test_status_and_legacy_mapping():
    assert normalize("작성 중", "서류 준비 중") == "서류 준비 중" and normalize("제출 완료") == "지원 완료"
    assert normalize("이상한 값", "서류 준비 중") == "서류 준비 중"
    today = date(2026, 11, 5)
    assert urgency(today + timedelta(days=2), "관심 공고", today) == "soon"
    assert urgency(today + timedelta(days=6), "지원 예정", today) == "week"
    assert urgency(today - timedelta(days=1), "서류 준비 중", today) == "over"
    assert urgency(today + timedelta(days=1), "지원 완료", today) == ""  # 이미 낸 공고는 마감 알림 없음


def test_deadline_guess_and_url_normalize():
    assert guess_deadline(POSTING, date(2026, 11, 5)) == date(2026, 11, 13)
    assert guess_deadline("서류 마감 ~11/3(월) 18:00", date(2026, 10, 1)) == date(2026, 11, 3)
    assert guess_deadline("근무시간 9:00~18:00, 주 5일", date(2026, 10, 1)) is None
    assert normalize_url("https://Job.com/v/1/?utm_source=a#x") == normalize_url("https://job.com/v/1")


def test_text_duplicate_opens_existing(auth_client, user):
    _exp(user)
    _text(auth_client)
    page = _text(auth_client, POSTING.replace("\n", "\n  ")).get_data(as_text=True)  # 띄어쓰기만 다른 같은 공고
    assert db.session.query(PostingAnalysis).count() == 1 and "이미 넣은 공고예요" in page
    _text(auth_client, allow_dup="1")
    assert db.session.query(PostingAnalysis).count() == 2  # 원하면 따로 저장


def test_review_shows_duplicate_and_prefills_deadline(auth_client, user, monkeypatch):
    import app.experiences.posting_extract as pex

    from .test_posting_images import submit_review
    _exp(user)
    monkeypatch.setattr(pex, "fetch_posting_full", lambda url: {"title": "해외영업", "text": POSTING, "images": []})
    first = auth_client.post("/experiences/posting", data={"mode": "url", "url": "https://job.com/v/1"}).get_data(as_text=True)
    assert 'value="2026-11-13"' in first and "이미 넣은 공고" not in first  # 공고에서 찾은 마감일을 미리 채움
    submit_review(auth_client, first)
    pa = db.session.query(PostingAnalysis).one()
    assert pa.deadline == date(2026, 11, 13)

    again = auth_client.post("/experiences/posting", data={"mode": "url", "url": "https://job.com/v/1/?utm_source=kakao"})
    review = again.get_data(as_text=True)
    assert "이미 넣은 공고 같아요" in review and f"/experiences/posting/{pa.id}" in review
    submit_review(auth_client, review)  # '그래도 새로 분석'을 고르지 않으면 기존 공고로
    assert db.session.query(PostingAnalysis).count() == 1


def test_status_deadline_and_sync_with_application(auth_client, user):
    _exp(user)
    _text(auth_client)
    pa = db.session.query(PostingAnalysis).one()
    assert not pa.is_saved and pa.status == ""
    auth_client.post(f"/experiences/posting/{pa.id}/status", data={"status": "지원 예정", "deadline": "2026-11-13"})
    db.session.refresh(pa)
    assert pa.is_saved and pa.status == "지원 예정" and pa.deadline == date(2026, 11, 13)  # 상태를 정하면 ★ 저장

    # 이 공고로 지원 기록 만들기 → 공고 상태·마감일이 미리 채워지고, 지원 기록 상태를 바꾸면 공고도 따라감
    form = auth_client.get(f"/applications/new?posting={pa.id}").get_data(as_text=True)
    assert "2026.11.13" in form
    auth_client.post("/applications/new", data={"company": "한빛무역", "status": "지원 예정", "posting_id": pa.id})
    rec = db.session.query(ApplicationRecord).one()
    auth_client.post(f"/applications/{rec.id}/status", data={"status": "지원 완료"})
    db.session.refresh(pa)
    assert pa.status == "지원 완료"
    auth_client.post(f"/experiences/posting/{pa.id}/status", data={"status": "서류 합격"})
    db.session.refresh(rec)
    assert rec.status == "서류 합격"

    page = auth_client.get("/experiences/posting?st=서류 합격").get_data(as_text=True)
    assert "서류 합격 <b>1</b>" in page


def test_unsave_clears_status(auth_client, user):
    _exp(user)
    _text(auth_client, save_now="1")
    pa = db.session.query(PostingAnalysis).one()
    assert pa.is_saved and pa.status == "관심 공고"
    auth_client.post(f"/experiences/posting/{pa.id}/save")
    db.session.refresh(pa)
    assert not pa.is_saved and pa.status == ""


def test_legacy_status_in_old_backup_is_mapped(auth_client, user):
    import json
    data = {"format": "growly-backup", "version": 1, "experiences": [], "certificates": [],
            "applications": [{"company": "예전 회사", "status": "제출 완료"}]}
    auth_client.post("/experiences/data/import", data={"file": (io.BytesIO(json.dumps(data).encode()), "b.json")},
                     content_type="multipart/form-data")
    from app.experiences.models import Snapshot
    snap = db.session.query(Snapshot).one()
    auth_client.post(f"/experiences/data/{snap.id}/load", data={"parts": ["applications"]})
    assert db.session.query(ApplicationRecord).one().status == "지원 완료"


def test_cannot_change_others_posting_status(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    pb = PostingAnalysis(user_id=b.id, title="B의 공고", posting_text="B", result_json="{}")
    db.session.add(pb)
    db.session.commit()
    rec = ApplicationRecord(user_id=a.id, company="A사", status="서류 준비 중", posting_id=pb.id)  # 남의 공고 id를 억지로 연결
    db.session.add(rec)
    db.session.commit()
    login(client, a.email)
    assert client.post(f"/experiences/posting/{pb.id}/status", data={"status": "최종 합격"}).status_code == 404
    client.post(f"/applications/{rec.id}/status", data={"status": "최종 합격"})
    db.session.refresh(pb)
    assert pb.status in ("", None)  # 내 지원 기록 상태를 바꿔도 남의 공고는 그대로
