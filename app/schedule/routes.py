import json
from datetime import date

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..core.job_status import parse_date
from ..core.scoping import create_owned, get_owned_or_404, owned
from ..experiences.models import PostingAnalysis
from ..extensions import db
from . import bp
from .models import DEFAULT_CHECKLIST, KINDS, ScheduleEvent
from .services import collect_events, month_grid, month_range, read_checklist, upcoming


def _month() -> tuple[int, int]:
    """?m=2026-11 → (2026, 11). 없거나 틀리면 이번 달."""
    try:
        y, m = (int(x) for x in (request.args.get("m") or "").split("-"))
        if 2000 <= y <= 2100 and 1 <= m <= 12:
            return y, m
    except ValueError:
        pass
    today = date.today()
    return today.year, today.month


def _back(ev=None):
    m = request.form.get("m") or (f"{ev.date.year}-{ev.date.month:02d}" if ev else "")
    return redirect(url_for("schedule.index", m=m or None))


@bp.route("/")
@login_required
def index():
    year, month = _month()
    start, end = month_range(year, month)
    events = collect_events(start, end)
    prev_m = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    next_m = f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"
    postings = owned(PostingAnalysis).filter(PostingAnalysis.is_saved.is_(True)).order_by(PostingAnalysis.saved_at.desc()).all()
    edit = get_owned_or_404(ScheduleEvent, request.args.get("edit", type=int)) if request.args.get("edit") else None
    month_events = [e for e in events if e["date"].year == year and e["date"].month == month]
    return render_template("schedule/index.html", weeks=month_grid(year, month, events), year=year, month=month,
                           month_events=month_events,
                           prev_m=prev_m, next_m=next_m, this_m=f"{year}-{month:02d}", upcoming=upcoming(),
                           kinds=KINDS, postings=postings, edit=edit, today=date.today())


def _fill(ev: ScheduleEvent) -> str | None:
    """폼 → 일정. 문제가 있으면 안내 문구를 돌려줌."""
    title = (request.form.get("title") or "").strip()[:200]
    day = parse_date(request.form.get("date"))
    if not title or not day:
        return "일정 이름과 날짜를 넣어 주세요."
    kind = request.form.get("kind")
    pid = request.form.get("posting_id", type=int)
    ev.title, ev.date = title, day
    ev.kind = kind if kind in KINDS else "개인 일정"
    ev.time = (request.form.get("time") or "").strip()[:10]
    ev.memo = (request.form.get("memo") or "").strip()[:2000]
    ev.posting_id = get_owned_or_404(PostingAnalysis, pid).id if pid else None
    ev.checklist_json = json.dumps(read_checklist(request.form.get("checklist", ""), ev.checklist), ensure_ascii=False)
    return None


@bp.route("/new", methods=["POST"])
@login_required
def new():
    ev = ScheduleEvent(title="", date=date.today())
    error = _fill(ev)
    if error:
        flash(error, "error")
        return _back()
    created = create_owned(ScheduleEvent, title=ev.title, date=ev.date, kind=ev.kind, time=ev.time, memo=ev.memo,
                           posting_id=ev.posting_id, checklist_json=ev.checklist_json)
    db.session.commit()
    flash(f"'{created.title}' 일정을 추가했어요.", "success")
    return _back(created)


@bp.route("/<int:ev_id>/edit", methods=["POST"])
@login_required
def edit(ev_id):
    ev = get_owned_or_404(ScheduleEvent, ev_id)
    error = _fill(ev)
    if error:
        flash(error, "error")
        return redirect(url_for("schedule.index", edit=ev.id))
    db.session.commit()
    flash("일정을 고쳤어요.", "success")
    return _back(ev)


@bp.route("/<int:ev_id>/check", methods=["POST"])
@login_required
def check(ev_id):
    """체크리스트 한 항목 끝냄/되돌림 · 일정 전체 끝냄."""
    ev = get_owned_or_404(ScheduleEvent, ev_id)
    if request.form.get("all") == "1":
        ev.done = not ev.done
    else:
        items = ev.checklist
        i = request.form.get("i", type=int)
        if i is not None and 0 <= i < len(items):
            items[i]["done"] = not items[i].get("done")
            ev.checklist_json = json.dumps(items, ensure_ascii=False)
    db.session.commit()
    return _back(ev)


@bp.route("/<int:ev_id>/delete", methods=["POST"])
@login_required
def delete(ev_id):
    ev = get_owned_or_404(ScheduleEvent, ev_id)
    db.session.delete(ev)
    db.session.commit()
    flash(f"'{ev.title}' 일정을 지웠어요.", "info")
    return _back(ev)


@bp.route("/from-posting/<int:pa_id>", methods=["POST"])
@login_required
def from_posting(pa_id):
    """공고 마감일 → 기본 체크리스트가 담긴 '서류 제출' 일정(자동 마감 일정 대신 보임)."""
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    if not pa.deadline:
        flash("공고에 마감일이 없어요. 공고 매칭 화면에서 마감일을 먼저 넣어 주세요.", "error")
        return redirect(url_for("experiences.posting_detail", pa_id=pa.id))
    ev = owned(ScheduleEvent).filter(ScheduleEvent.posting_id == pa.id, ScheduleEvent.date == pa.deadline).first()
    if not ev:
        ev = create_owned(ScheduleEvent, title=f"{pa.company or pa.title} 서류 제출", kind="서류 제출", date=pa.deadline,
                          posting_id=pa.id,
                          checklist_json=json.dumps([{"text": t, "done": False} for t in DEFAULT_CHECKLIST], ensure_ascii=False))
        db.session.commit()
        flash("마감일에 준비 체크리스트를 만들었어요.", "success")
    return redirect(url_for("schedule.index", m=f"{ev.date.year}-{ev.date.month:02d}", _anchor=f"ev-{ev.id}"))
