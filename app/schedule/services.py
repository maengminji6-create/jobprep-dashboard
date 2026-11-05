"""취업 일정 모으기: 내가 추가한 일정 + 공고 마감일 + 지원 기록의 마감일·제출일(자동, 따로 저장하지 않음)."""
import calendar
from datetime import date, timedelta

from ..core.job_status import DONE, d_day, parse_date, urgency
from ..core.scoping import owned
from .models import ScheduleEvent


def _event_view(ev: ScheduleEvent, today: date) -> dict:
    items = ev.checklist
    left = d_day(ev.date, today)
    hot = "" if ev.done else ("over" if left < 0 else ("soon" if left <= 3 else ("week" if left <= 7 else "")))
    return {"source": "event", "id": ev.id, "date": ev.date, "time": ev.time or "", "title": ev.title, "kind": ev.kind,
            "memo": ev.memo or "", "done": ev.done, "checklist": items, "checked": sum(1 for i in items if i.get("done")),
            "posting_id": ev.posting_id, "d_day": left, "urgency": hot, "status": ""}


def collect_events(start: date, end: date, today: date | None = None) -> list[dict]:
    """start~end(포함) 사이의 일정. 같은 공고에 직접 만든 일정이 같은 날 있으면 자동 마감 일정은 뺌."""
    from ..applications.models import ApplicationRecord
    from ..experiences.models import PostingAnalysis
    today = today or date.today()
    stored = owned(ScheduleEvent).filter(ScheduleEvent.date >= start, ScheduleEvent.date <= end).all()
    out = [_event_view(ev, today) for ev in stored]
    covered = {(ev.posting_id, ev.date) for ev in stored if ev.posting_id}

    posting_days = {}
    for pa in owned(PostingAnalysis).filter(PostingAnalysis.deadline.isnot(None),
                                            PostingAnalysis.deadline >= start, PostingAnalysis.deadline <= end).all():
        posting_days[pa.id] = pa.deadline
        if (pa.id, pa.deadline) in covered:
            continue
        out.append({"source": "posting", "id": pa.id, "date": pa.deadline, "time": "", "kind": "공고 마감",
                    "title": f"{pa.company or pa.title} 마감", "memo": pa.title if pa.company else "",
                    "done": pa.status in DONE, "checklist": [], "checked": 0, "posting_id": pa.id,
                    "d_day": d_day(pa.deadline, today), "urgency": urgency(pa.deadline, pa.status, today),
                    "status": pa.status or ""})

    for rec in owned(ApplicationRecord).all():
        for field, kind in (("deadline", "서류 마감"), ("applied_at", "제출 완료")):
            day = parse_date(getattr(rec, field))
            if not day or not (start <= day <= end):
                continue
            if kind == "서류 마감" and (posting_days.get(rec.posting_id) == day or (rec.posting_id, day) in covered):
                continue  # 연결한 공고 마감과 같은 날이면 한 번만
            out.append({"source": "application", "id": rec.id, "date": day, "time": "", "kind": kind,
                        "title": f"{rec.company} {kind}", "memo": rec.position or "", "done": kind == "제출 완료" or rec.status in DONE,
                        "checklist": [], "checked": 0, "posting_id": rec.posting_id, "d_day": d_day(day, today),
                        "urgency": "" if kind == "제출 완료" else urgency(day, rec.status, today), "status": rec.status})
    from ..interview.models import InterviewSession
    for s in owned(InterviewSession).filter(InterviewSession.interview_date.isnot(None),
                                            InterviewSession.interview_date >= start,
                                            InterviewSession.interview_date <= end).all():
        if any(ev.kind == "면접" and ev.date == s.interview_date and ev.posting_id and ev.posting_id == s.posting_id
               for ev in stored):
            continue  # 같은 공고로 직접 만든 면접 일정이 있으면 한 번만
        left = d_day(s.interview_date, today)
        out.append({"source": "interview", "id": s.id, "date": s.interview_date, "time": "", "kind": "면접",
                    "title": s.title, "memo": f"예상 질문 {len(s.questions)}개 · 답변 {sum(1 for q in s.questions if q.answer.strip())}개",
                    "done": bool(s.review), "checklist": [], "checked": 0, "posting_id": s.posting_id, "d_day": left,
                    "urgency": "" if s.review else ("over" if left < 0 else ("soon" if left <= 3 else ("week" if left <= 7 else ""))),
                    "status": ""})
    out.sort(key=lambda e: (e["date"], e["time"] or "99", e["kind"]))
    return out


def month_grid(year: int, month: int, events: list[dict], today: date | None = None) -> list[list[dict]]:
    """월 달력(일요일 시작): 주마다 7칸, 칸마다 그날 일정."""
    today = today or date.today()
    by_day = {}
    for e in events:
        by_day.setdefault(e["date"], []).append(e)
    weeks = []
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):
        weeks.append([{"date": d, "in_month": d.month == month, "today": d == today, "events": by_day.get(d, [])}
                      for d in week])
    return weeks


def month_range(year: int, month: int) -> tuple[date, date]:
    """달력에 보이는 첫날~마지막 날(앞뒤 달 일부 포함)."""
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    return weeks[0][0], weeks[-1][-1]


def upcoming(today: date | None = None, days: int = 14) -> list[dict]:
    """끝나지 않은 일정 중 오늘부터 days일 안의 것 + 지난 7일 안에 마감됐는데 아직 지원하지 않은 공고."""
    today = today or date.today()
    items = collect_events(today - timedelta(days=7), today + timedelta(days=days), today)
    return [e for e in items if not e["done"] and (e["date"] >= today or e["urgency"] == "over")]


def read_checklist(text: str, keep: list[dict] | None = None) -> list[dict]:
    """한 줄에 하나씩 적은 할 일 → [{"text", "done"}]. 이미 있던 항목은 체크 상태를 유지."""
    done = {i["text"]: i.get("done", False) for i in (keep or [])}
    out = []
    for ln in (text or "").splitlines():
        t = ln.strip(" -•·☐☑✓\t")[:200]
        if t and t not in [i["text"] for i in out]:
            out.append({"text": t, "done": done.get(t, False)})
    return out[:30]
