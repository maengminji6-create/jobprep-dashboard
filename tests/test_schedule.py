"""취업 일정: 공고 마감·지원 기록 자동 반영 · 직접 추가 · 체크리스트 · 준비 체크리스트 · 다가오는 일정."""
from datetime import date, timedelta

from app.applications.models import ApplicationRecord
from app.experiences.models import PostingAnalysis
from app.extensions import db
from app.schedule.models import ScheduleEvent
from app.schedule.services import collect_events, month_grid, read_checklist, upcoming


def _posting(user, days=2, status="관심 공고", company="한빛무역"):
    pa = PostingAnalysis(user_id=user.id, company=company, title="해외영업", posting_text="x", result_json="{}",
                         is_saved=True, status=status, deadline=date.today() + timedelta(days=days))
    db.session.add(pa)
    db.session.commit()
    return pa


def test_auto_events_from_posting_and_application(auth_client, user):
    pa = _posting(user)
    db.session.add(ApplicationRecord(user_id=user.id, company="코스알엑스", status="지원 완료",
                                     applied_at=(date.today() - timedelta(days=1)).strftime("%Y.%m.%d"),
                                     deadline=(date.today() + timedelta(days=5)).strftime("%Y.%m.%d")))
    db.session.add(ApplicationRecord(user_id=user.id, company="한빛무역", posting_id=pa.id,
                                     deadline=pa.deadline.strftime("%Y.%m.%d")))  # 연결한 공고 마감과 같은 날
    db.session.commit()
    page = auth_client.get("/schedule/").get_data(as_text=True)
    assert "한빛무역 마감" in page and "코스알엑스 제출 완료" in page and "코스알엑스 서류 마감" in page
    assert "한빛무역 서류 마감" not in page  # 같은 날 공고 마감과 겹치면 한 번만
    assert 'class="dday soon"' in page  # 2일 남은 공고는 임박 강조


def test_add_event_with_checklist_and_toggle(auth_client, user):
    day = date.today() + timedelta(days=3)
    auth_client.post("/schedule/new", data={"title": "1차 면접", "kind": "면접", "date": day.isoformat(), "time": "14:00",
                                            "checklist": "예상 질문 정리\n- 회사 뉴스 읽기\n예상 질문 정리"})
    ev = db.session.query(ScheduleEvent).one()
    assert ev.kind == "면접" and ev.time == "14:00" and [c["text"] for c in ev.checklist] == ["예상 질문 정리", "회사 뉴스 읽기"]
    auth_client.post(f"/schedule/{ev.id}/check", data={"i": "1"})
    db.session.refresh(ev)
    assert ev.checklist[1]["done"] and not ev.checklist[0]["done"]
    # 고쳐도 끝낸 항목은 그대로
    auth_client.post(f"/schedule/{ev.id}/edit", data={"title": "1차 면접", "kind": "면접", "date": day.isoformat(),
                                                      "checklist": "예상 질문 정리\n회사 뉴스 읽기\n복장 준비"})
    db.session.refresh(ev)
    assert [c["done"] for c in ev.checklist] == [False, True, False]
    auth_client.post(f"/schedule/{ev.id}/check", data={"all": "1"})
    db.session.refresh(ev)
    assert ev.done
    page = auth_client.get(f"/schedule/?m={day.year}-{day.month:02d}").get_data(as_text=True)
    assert "1차 면접" in page and "1/3 완료" in page


def test_invalid_event_is_rejected(auth_client, user):
    r = auth_client.post("/schedule/new", data={"title": "", "date": "어제"}, follow_redirects=True)
    assert "일정 이름과 날짜" in r.get_data(as_text=True) and not db.session.query(ScheduleEvent).count()


def test_prep_checklist_from_posting_replaces_auto_deadline(auth_client, user):
    pa = _posting(user, days=6)
    auth_client.post(f"/schedule/from-posting/{pa.id}")
    auth_client.post(f"/schedule/from-posting/{pa.id}")  # 두 번 눌러도 하나만
    ev = db.session.query(ScheduleEvent).one()
    assert ev.kind == "서류 제출" and ev.date == pa.deadline and len(ev.checklist) == 4
    page = auth_client.get(f"/schedule/?m={pa.deadline.year}-{pa.deadline.month:02d}").get_data(as_text=True)
    assert "한빛무역 서류 제출" in page and "한빛무역 마감" not in page


def test_posting_without_deadline_cannot_make_checklist(auth_client, user):
    pa = PostingAnalysis(user_id=user.id, company="A사", posting_text="x", result_json="{}")
    db.session.add(pa)
    db.session.commit()
    r = auth_client.post(f"/schedule/from-posting/{pa.id}", follow_redirects=True)
    assert "마감일이 없어요" in r.get_data(as_text=True)


def test_upcoming_and_month_grid(app, auth_client, user):
    _posting(user, days=1)
    _posting(user, days=-2, company="지난공고")                  # 지났는데 아직 관심 공고 → 놓친 마감으로 보여 줌
    _posting(user, days=-2, status="지원 완료", company="낸공고")  # 이미 지원 → 안 보임
    with app.test_request_context():
        from flask_login import login_user
        login_user(user)
        names = [e["title"] for e in upcoming()]
        assert "한빛무역 마감" in names and "지난공고 마감" in names and "낸공고 마감" not in names
        t = date.today()
        weeks = month_grid(t.year, t.month, collect_events(t.replace(day=1), t.replace(day=28)))
        assert all(len(w) == 7 for w in weeks) and any(d["today"] for w in weeks for d in w)


def test_read_checklist_keeps_done_state():
    old = [{"text": "A", "done": True}]
    assert read_checklist("A\nB", old) == [{"text": "A", "done": True}, {"text": "B", "done": False}]


def test_nav_has_schedule(auth_client):
    page = auth_client.get("/schedule/").get_data(as_text=True)
    assert 'href="/schedule/" class="active"' in page
