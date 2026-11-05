import json

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..applications.models import ApplicationRecord
from ..applications.services import star_outline
from ..core.job_status import parse_date
from ..core.scoping import create_owned, get_owned_or_404, owned
from ..core.trade_roles import ROLE_BY_CODE
from ..experiences.models import Experience, PostingAnalysis
from ..extensions import db
from ..integrations import ai_client
from . import bp
from .models import CATEGORIES, InterviewQuestion, InterviewSession
from .services import check_ai_questions, check_answer, rule_questions


def _role_name(s: InterviewSession) -> str:
    return ROLE_BY_CODE.get(s.role_code, {}).get("name", "지원 직무")


def _add_questions(s: InterviewSession, items: list[dict], source: str) -> int:
    have = {q.question for q in s.questions}
    n = 0
    for it in items:
        if it["question"] in have:
            continue
        create_owned(InterviewQuestion, session_id=s.id, category=it["category"], question=it["question"][:500],
                     basis=it.get("basis", "")[:300], source=source, exp_ids=",".join(map(str, it.get("exp_ids", []))))
        have.add(it["question"])
        n += 1
    return n


def _generate(s: InterviewSession, use_ai: bool) -> tuple[int, str]:
    """규칙 질문(항상) + AI 질문(원하면). (추가한 수, AI 안내 문구)"""
    from ..experiences.analyzer import analyze_all
    exps = owned(Experience).order_by(Experience.created_at).all()
    posting = db.session.get(PostingAnalysis, s.posting_id) if s.posting_id else None
    n = _add_questions(s, rule_questions(s.company, _role_name(s), posting, exps,
                                         {a["id"]: a for a in analyze_all(exps)}), "rule")
    note = ""
    if use_ai:
        if not ai_client.enabled():
            note = "AI 질문은 만들지 않았어요: " + ai_client.unavailable_message() + " 규칙 기반 질문만 넣었어요."
        else:
            try:
                raw = ai_client.interview_questions(posting.posting_text if posting else "", exps, s.company, _role_name(s))
                source = "\n".join([posting.posting_text if posting else ""] + [e.full_text for e in exps])
                kept = check_ai_questions(raw, source)
                n += _add_questions(s, kept, "ai")
                if len(kept) < len(raw):
                    note = f"AI 질문 {len(raw) - len(kept)}개는 근거 문장을 공고·경험에서 찾을 수 없어 뺐어요."
            except ai_client.AiError as exc:
                note = f"AI 질문은 만들지 못했어요: {exc}"
    return n, note


@bp.route("/")
@login_required
def index():
    sessions = owned(InterviewSession).order_by(InterviewSession.created_at.desc()).all()
    postings = owned(PostingAnalysis).filter(PostingAnalysis.is_saved.is_(True)).order_by(PostingAnalysis.saved_at.desc()).all()
    apps = owned(ApplicationRecord).order_by(ApplicationRecord.created_at.desc()).all()
    return render_template("interview/index.html", sessions=sessions, postings=postings, apps=apps,
                           ai_enabled=ai_client.enabled(), posting_pre=request.args.get("posting", type=int))


@bp.route("/new", methods=["POST"])
@login_required
def new():
    posting = get_owned_or_404(PostingAnalysis, request.form.get("posting_id", type=int)) \
        if request.form.get("posting_id") else None
    app_rec = get_owned_or_404(ApplicationRecord, request.form.get("application_id", type=int)) \
        if request.form.get("application_id") else None
    company = (request.form.get("company") or "").strip()[:120] or (posting.company if posting else "") \
        or (app_rec.company if app_rec else "")
    if not company and not posting:
        flash("회사명을 적거나 공고를 골라 주세요.", "error")
        return redirect(url_for("interview.index"))
    role = (posting.role_code if posting else "") or (app_rec.role_code if app_rec else "") or "overseas_sales"
    s = create_owned(InterviewSession, title=f"{company or posting.title} 면접", company=company,
                     role_code=role if role in ROLE_BY_CODE else "overseas_sales",
                     posting_id=posting.id if posting else None, application_id=app_rec.id if app_rec else None,
                     interview_date=parse_date(request.form.get("interview_date")))
    db.session.flush()
    n, note = _generate(s, bool(request.form.get("use_ai")))
    db.session.commit()
    flash(f"예상 질문 {n}개를 만들었어요. 질문마다 추천 경험으로 답변을 준비해 보세요.", "success")
    if note:
        flash(note, "info")
    return redirect(url_for("interview.detail", sid=s.id))


@bp.route("/<int:sid>")
@login_required
def detail(sid):
    s = get_owned_or_404(InterviewSession, sid)
    exps = {e.id: e for e in owned(Experience).all()}
    outlines = {i: star_outline(e) for i, e in exps.items()}
    groups = [(c, [q for q in s.questions if q.category == c]) for c in CATEGORIES]
    posting = db.session.get(PostingAnalysis, s.posting_id) if s.posting_id else None
    return render_template("interview/detail.html", s=s, groups=[g for g in groups if g[1]], exps=exps, outlines=outlines,
                           categories=CATEGORIES, ai_enabled=ai_client.enabled(), role_name=_role_name(s),
                           posting=posting if posting and posting.user_id == s.user_id else None,
                           answered=sum(1 for q in s.questions if q.answer.strip()))


@bp.route("/<int:sid>/generate", methods=["POST"])
@login_required
def generate(sid):
    s = get_owned_or_404(InterviewSession, sid)
    n, note = _generate(s, bool(request.form.get("use_ai")))
    db.session.commit()
    flash(f"새 질문 {n}개를 더했어요." if n else "더할 새 질문이 없어요(이미 있는 질문은 다시 넣지 않아요).", "success" if n else "info")
    if note:
        flash(note, "info")
    return redirect(url_for("interview.detail", sid=s.id))


@bp.route("/<int:sid>/questions", methods=["POST"])
@login_required
def add_question(sid):
    s = get_owned_or_404(InterviewSession, sid)
    text = (request.form.get("question") or "").strip()
    if not text:
        flash("질문을 적어 주세요.", "error")
    else:
        cat = request.form.get("category")
        _add_questions(s, [{"category": cat if cat in CATEGORIES else "기타", "question": text, "basis": "직접 추가"}], "manual")
        db.session.commit()
    return redirect(url_for("interview.detail", sid=s.id, _anchor="add"))


@bp.route("/q/<int:qid>", methods=["POST"])
@login_required
def save_answer(qid):
    """답변 · 쓴 경험 · 실제로 받은 질문인지 · 복기 메모 저장(+ 원하면 점검)."""
    q = get_owned_or_404(InterviewQuestion, qid)
    q.answer = (request.form.get("answer") or "").strip()[:5000]
    ids = [int(x) for x in request.form.getlist("exp_ids") if x.isdigit()]
    q.exp_ids = ",".join(str(get_owned_or_404(Experience, i).id) for i in dict.fromkeys(ids))[:200]
    q.asked = bool(request.form.get("asked"))
    q.self_note = (request.form.get("self_note") or "").strip()[:2000]
    if request.form.get("action") == "check":
        linked = [get_owned_or_404(Experience, i) for i in q.exp_id_list]
        fb = {"rule": check_answer(q.answer, linked)}
        if request.form.get("use_ai") and q.answer:
            if ai_client.enabled():
                try:
                    fb["ai"] = ai_client.interview_feedback(q.question, q.answer)
                except ai_client.AiError as exc:
                    flash(f"AI 피드백은 받지 못했어요: {exc}", "info")
            else:
                flash("AI 피드백은 받지 못했어요: " + ai_client.unavailable_message() + " 규칙 점검만 했어요.", "info")
        q.feedback_json = json.dumps(fb, ensure_ascii=False)
    db.session.commit()
    flash("답변을 저장했어요." + (" 점검 결과를 확인해 보세요." if request.form.get("action") == "check" else ""), "success")
    return redirect(url_for("interview.detail", sid=q.session_id, _anchor=f"q-{q.id}"))


@bp.route("/q/<int:qid>/delete", methods=["POST"])
@login_required
def delete_question(qid):
    q = get_owned_or_404(InterviewQuestion, qid)
    sid = q.session_id
    db.session.delete(q)
    db.session.commit()
    return redirect(url_for("interview.detail", sid=sid))


@bp.route("/<int:sid>/review", methods=["POST"])
@login_required
def save_review(sid):
    s = get_owned_or_404(InterviewSession, sid)
    s.interview_date = parse_date(request.form.get("interview_date"))
    s.review = (request.form.get("review") or "").strip()[:5000]
    db.session.commit()
    flash("면접 일정·복기를 저장했어요." + (" 취업 일정에도 표시돼요." if s.interview_date else ""), "success")
    return redirect(url_for("interview.detail", sid=s.id, _anchor="review"))


@bp.route("/<int:sid>/delete", methods=["POST"])
@login_required
def delete(sid):
    s = get_owned_or_404(InterviewSession, sid)
    db.session.delete(s)
    db.session.commit()
    flash(f"'{s.title}' 면접 준비를 지웠어요.", "info")
    return redirect(url_for("interview.index"))
