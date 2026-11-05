from flask import flash, redirect, render_template, request, session, url_for
from flask_login import login_required

from ..core.scoping import create_owned, get_owned_or_404, owned
from ..experiences.models import Experience
from ..extensions import db
from ..integrations import ai_client
from ..strengths.services import latest_profile
from . import bp
from .models import EVIDENCE_LEVELS, LINK_ORIGINS, StrengthLink, StrengthManual
from .services import (BATCH, generate_links, integrated, links_of, locate, overview, pending, run_analysis,
                       saved_analyses)


def _exps():
    return owned(Experience).order_by(Experience.created_at).all()


@bp.route("/")
@login_required
def index():
    exps = _exps()
    saved = saved_analyses()
    view = overview(exps, saved)
    profile = latest_profile()
    links, result = [], None
    if profile:
        links = links_of(profile)
        result = integrated(profile, links, view, exps)
    return render_template("analysis/index.html", exps=exps, saved=saved, view=view, waiting=pending(exps, saved),
                           profile=profile, links=links, result=result, exp_by_id={e.id: e for e in exps},
                           levels=EVIDENCE_LEVELS, origins=LINK_ORIGINS, batch=BATCH, ai_enabled=ai_client.enabled())


@bp.route("/run", methods=["POST"])
@login_required
def run():
    """고른 경험(또는 분석 전·갱신 필요 경험 앞에서부터 BATCH개)을 AI로 분석."""
    back = url_for("analysis.index", _anchor="experiences")
    if not ai_client.enabled():
        flash(ai_client.unavailable_message(), "info")
        return redirect(back)
    ids = [int(i) for i in request.form.getlist("exp_id") if i.isdigit()]
    targets = [get_owned_or_404(Experience, i) for i in ids] if ids else pending(_exps(), saved_analyses())
    if not targets:
        flash("새로 분석할 경험이 없어요. 경험을 고치면 '다시 분석'이 나타나요.", "info")
        return redirect(back)
    try:
        n = run_analysis(targets)
    except ai_client.AiError as exc:
        db.session.rollback()
        flash(f"분석하지 못했어요. {exc}", "error")
        return redirect(back)
    db.session.commit()
    left = len(pending(_exps(), saved_analyses()))
    flash(f"경험 {n}개를 분석했어요." + (f" 남은 경험 {left}개는 한 번 더 눌러 주세요." if left else ""), "success")
    return redirect(back)


# ── C. 강점 × 경험 연결 ──────────────────────────────────────────

def _back():
    return redirect(url_for("analysis.index", _anchor="links"))


@bp.route("/links/generate", methods=["POST"])
@login_required
def links_generate():
    profile = latest_profile()
    if not profile or not profile.strengths:
        flash("먼저 강점 진단 결과를 등록해 주세요.", "error")
        return _back()
    exps = _exps()
    if not exps:
        flash("연결할 경험이 아직 없어요. 경험 관리에서 먼저 등록해 주세요.", "error")
        return _back()
    use_ai = request.form.get("mode") == "ai"
    if use_ai and not ai_client.enabled():
        flash(ai_client.unavailable_message() + " '단어 단서로 연결'은 키 없이 쓸 수 있어요.", "info")
        return _back()
    try:
        n = generate_links(profile, exps, use_ai)
    except ai_client.AiError as exc:
        db.session.rollback()
        flash(f"연결하지 못했어요. {exc}", "error")
        return _back()
    db.session.commit()
    flash(f"연결 {n}개를 새로 만들었어요. 직접 고치거나 해제한 연결은 그대로 뒀어요.", "success")
    return _back()


def _link_fields(exp):
    """폼의 근거 행동·이유·충분성. 근거 행동은 경험 원문에 있어야 함(출처 추적)."""
    quote = (request.form.get("quote") or "").strip()
    reason = (request.form.get("reason") or "").strip()[:300]
    evidence = request.form.get("evidence") if request.form.get("evidence") in EVIDENCE_LEVELS else "약함"
    if quote and not locate(quote, exp):
        return None, "근거 행동은 경험에 적힌 문장 그대로 넣어 주세요. 없는 내용이라면 경험에 먼저 적어 주세요."
    if not quote:
        evidence = "약함"  # 근거 문장 없이 연결하면 확정하지 않음
    return {"quote": quote[:300], "reason": reason, "evidence": evidence}, None


@bp.route("/links/new", methods=["POST"])
@login_required
def link_new():
    profile = latest_profile()
    name = (request.form.get("strength") or "").strip()
    if not profile or name not in {s["name"] for s in profile.strengths}:
        flash("연결할 강점을 골라 주세요.", "error")
        return _back()
    exp = get_owned_or_404(Experience, request.form.get("exp_id", type=int) or 0)
    fields, err = _link_fields(exp)
    if err:
        flash(err, "error")
        return _back()
    lk = owned(StrengthLink).filter(StrengthLink.profile_id == profile.id, StrengthLink.strength_name == name,
                                    StrengthLink.experience_id == exp.id).first()
    if lk:
        for k, v in fields.items():
            setattr(lk, k, v)
        lk.removed, lk.edited = False, True
    else:
        create_owned(StrengthLink, profile_id=profile.id, strength_name=name[:40], experience_id=exp.id,
                     origin="user", content_hash=exp.content_hash, **fields)
    db.session.commit()
    flash(f"'{name}' 강점에 '{exp.title}'을(를) 연결했어요.", "success")
    return _back()


@bp.route("/links/<int:link_id>/edit", methods=["POST"])
@login_required
def link_edit(link_id):
    lk = get_owned_or_404(StrengthLink, link_id)
    exp = get_owned_or_404(Experience, lk.experience_id)
    fields, err = _link_fields(exp)
    if err:
        flash(err, "error")
        return _back()
    for k, v in fields.items():
        setattr(lk, k, v)
    lk.edited = True
    db.session.commit()
    flash("연결을 고쳤어요. 다시 자동 연결해도 이 내용은 그대로 남아요.", "success")
    return _back()


@bp.route("/links/<int:link_id>/remove", methods=["POST"])
@login_required
def link_remove(link_id):
    lk = get_owned_or_404(StrengthLink, link_id)
    lk.removed = True
    db.session.commit()
    flash("연결을 해제했어요. 다시 자동 연결해도 되살아나지 않아요.", "info")
    return _back()


@bp.route("/links/<int:link_id>/restore", methods=["POST"])
@login_required
def link_restore(link_id):
    lk = get_owned_or_404(StrengthLink, link_id)
    lk.removed = False
    db.session.commit()
    flash("연결을 되살렸어요.", "success")
    return _back()


# ── 나의 강점 사용 설명서 ─────────────────────────────────────────

def _manual_job() -> str:
    from ..core.job_competencies import JOB_BY_CODE, JOBS
    code = request.values.get("job")
    if code in JOB_BY_CODE:
        session["job_role"] = code  # 직무 연결 화면과 같은 기억 공유
        return code
    return session.get("job_role") if session.get("job_role") in JOB_BY_CODE else JOBS[0]["code"]


def _live_manual(job_code: str) -> dict:
    from .manual import build_manual
    profile = latest_profile()
    return build_manual(_exps(), saved_analyses(), profile, links_of(profile) if profile else [], job_code)


@bp.route("/manual")
@login_required
def manual():
    from ..core.job_competencies import JOBS
    code = _manual_job()
    return render_template("analysis/manual.html", m=_live_manual(code), saved_copy=None, jobs=JOBS, code=code,
                           history=owned(StrengthManual).order_by(StrengthManual.created_at.desc()).all())


@bp.route("/manual/save", methods=["POST"])
@login_required
def manual_save():
    import json
    code = _manual_job()
    m = _live_manual(code)
    if not m["strengths"]:
        flash("아직 담을 강점이 없어요. 경험을 AI로 분석하거나 강점 진단 결과를 등록해 주세요.", "error")
        return redirect(url_for("analysis.manual"))
    name = (request.form.get("name") or "").strip()[:120] or f"{m['generated_at']} · {m['job']['name']}"
    create_owned(StrengthManual, name=name, job_code=code, data_json=json.dumps(m, ensure_ascii=False))
    db.session.commit()
    flash(f"'{name}'(으)로 저장했어요. 데이터가 바뀌어도 이 저장본은 그대로예요.", "success")
    return redirect(url_for("analysis.manual", _anchor="history"))


@bp.route("/manual/<int:manual_id>")
@login_required
def manual_saved(manual_id):
    from ..core.job_competencies import JOBS
    row = get_owned_or_404(StrengthManual, manual_id)
    return render_template("analysis/manual.html", m=row.data, saved_copy=row, jobs=JOBS, code=row.job_code,
                           history=owned(StrengthManual).order_by(StrengthManual.created_at.desc()).all())


@bp.route("/manual/<int:manual_id>/delete", methods=["POST"])
@login_required
def manual_delete(manual_id):
    row = get_owned_or_404(StrengthManual, manual_id)
    db.session.delete(row)
    db.session.commit()
    flash(f"'{row.name}' 저장본을 지웠어요.", "info")
    return redirect(url_for("analysis.manual", _anchor="history"))
