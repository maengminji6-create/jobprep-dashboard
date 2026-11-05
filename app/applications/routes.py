from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from ..core.job_status import normalize
from ..core.scoping import create_owned, get_owned_or_404, owned
from ..core.trade_roles import ROLE_BY_CODE
from ..experiences.analyzer import role_options
from ..experiences.models import Experience, PostingAnalysis
from ..extensions import db
from . import bp
from .models import STATUSES, ApplicationRecord, ApplicationVersion
from .services import (check_answer_draft, dump_qa, read_qa, save_version, suggest_for_question, sync_from_application,
                       used_experiences)

FIELDS = ("company", "position", "role_code", "status", "applied_at", "deadline", "url",
          "company_info", "talent", "notes")
LIMITS = {"company": 120, "position": 200, "role_code": 40, "status": 20, "applied_at": 40, "deadline": 40}


def _form_fields() -> dict:
    out = {}
    for f in FIELDS:
        v = (request.form.get(f) or "").strip()
        out[f] = v[:LIMITS[f]] if f in LIMITS else v
    out["status"] = normalize(out["status"], "서류 준비 중")
    if out["role_code"] not in ROLE_BY_CODE:
        out["role_code"] = ""
    return out


def _posting_or_none(pid):
    return get_owned_or_404(PostingAnalysis, pid) if pid else None


@bp.route("/")
@login_required
def index():
    status = request.args.get("status", "")
    q = (request.args.get("q") or "").strip()
    rows = owned(ApplicationRecord).order_by(ApplicationRecord.created_at.desc())
    if status in STATUSES:
        rows = rows.filter(ApplicationRecord.status == status)
    if q:
        like = f"%{q}%"
        rows = rows.filter(db.or_(ApplicationRecord.company.ilike(like), ApplicationRecord.position.ilike(like),
                                  ApplicationRecord.qa_json.ilike(like), ApplicationRecord.notes.ilike(like)))
    records = rows.all()
    counts = {s: owned(ApplicationRecord).filter(ApplicationRecord.status == s).count() for s in STATUSES}
    return render_template("applications/index.html", records=records, statuses=STATUSES, status=status, q=q,
                           counts=counts, total=sum(counts.values()), role_map=ROLE_BY_CODE)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        fields = _form_fields()
        if not fields["company"]:
            flash("회사명을 적어 주세요.", "error")
            return render_template("applications/form.html", rec=None, form=request.form, qa=read_qa(request.form),
                                   **_form_context())
        posting = _posting_or_none(request.form.get("posting_id", type=int))
        rec = create_owned(ApplicationRecord, posting_id=posting.id if posting else None, qa_json=dump_qa(read_qa(request.form)),
                           **fields)
        sync_from_application(rec)
        db.session.commit()
        flash(f"'{rec.company}' 지원 기록을 저장했어요.", "success")
        return redirect(url_for("applications.detail", rec_id=rec.id))
    # 공고 매칭에서 넘어오면 회사·공고 정보를 미리 채움
    posting = _posting_or_none(request.args.get("posting", type=int))
    prefill = {}
    if posting:
        prefill = {"company": posting.company or "", "position": posting.title or "", "url": posting.url or "",
                   "role_code": posting.result.get("main_role", ""), "posting_id": posting.id,
                   "status": posting.status or "서류 준비 중",
                   "deadline": posting.deadline.strftime("%Y.%m.%d") if posting.deadline else ""}
    return render_template("applications/form.html", rec=None, form=prefill, qa=[], **_form_context())


def _form_context() -> dict:
    postings = owned(PostingAnalysis).order_by(PostingAnalysis.created_at.desc()).all()
    from ..integrations import ai_client
    return {"statuses": STATUSES, "roles": role_options(), "postings": postings, "ai_enabled": ai_client.enabled()}


@bp.route("/<int:rec_id>")
@login_required
def detail(rec_id):
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    exps = owned(Experience).all()
    used = {i: used_experiences(item.get("a", ""), exps, item.get("exps")) for i, item in enumerate(rec.qa)}
    all_used = {e.id: e for lst in used.values() for e in lst}
    posting = db.session.get(PostingAnalysis, rec.posting_id) if rec.posting_id else None
    if posting and posting.user_id != rec.user_id:
        posting = None
    return render_template("applications/detail.html", rec=rec, used=used, all_used=list(all_used.values()),
                           posting=posting, role_map=ROLE_BY_CODE, statuses=STATUSES)


@bp.route("/<int:rec_id>/edit", methods=["GET", "POST"])
@login_required
def edit(rec_id):
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    if request.method == "POST":
        fields = _form_fields()
        if not fields["company"]:
            flash("회사명을 적어 주세요.", "error")
            return redirect(url_for("applications.edit", rec_id=rec.id))
        for k, v in fields.items():
            setattr(rec, k, v)
        posting = _posting_or_none(request.form.get("posting_id", type=int))
        rec.posting_id = posting.id if posting else None
        new_qa = dump_qa(read_qa(request.form))
        if new_qa != rec.qa_json:
            save_version(rec)  # 바뀌기 전 문항·답변을 남겨 둠
        rec.qa_json = new_qa
        sync_from_application(rec)
        db.session.commit()
        flash("저장했어요.", "success")
        return redirect(url_for("applications.detail", rec_id=rec.id))
    form = {f: getattr(rec, f) or "" for f in FIELDS}
    form["posting_id"] = rec.posting_id
    return render_template("applications/form.html", rec=rec, form=form, qa=rec.qa, **_form_context())


@bp.route("/<int:rec_id>/status", methods=["POST"])
@login_required
def set_status(rec_id):
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    status = request.form.get("status")
    if status in STATUSES:
        rec.status = status
        sync_from_application(rec)
        db.session.commit()
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url)
                    else url_for("applications.detail", rec_id=rec.id))


@bp.route("/<int:rec_id>/versions/<int:ver_id>/restore", methods=["POST"])
@login_required
def restore_version(rec_id, ver_id):
    """이전 버전으로 되돌리기. 지금 답변도 버전으로 남겨서 다시 돌아올 수 있음."""
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    ver = get_owned_or_404(ApplicationVersion, ver_id)
    if ver.application_id != rec.id:
        abort(404)
    save_version(rec)
    rec.qa_json = ver.qa_json
    db.session.commit()
    flash("이전 버전으로 되돌렸어요. 되돌리기 전 답변도 버전에 남아 있어요.", "success")
    return redirect(url_for("applications.detail", rec_id=rec.id))


@bp.route("/<int:rec_id>/print")
@login_required
def print_view(rec_id):
    """자소서 PDF: 브라우저의 'PDF로 저장'으로 내보내기(이력 PDF와 같은 방식)."""
    from datetime import date
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    return render_template("applications/print.html", rec=rec, today=date.today(), role_map=ROLE_BY_CODE)


@bp.route("/suggest")
@login_required
def suggest():
    """문항에 맞는 내 경험 추천(JSON). 공고를 고르면 그 공고 요건을 받쳐 주는 경험을 앞에 둠."""
    from ..experiences.analyzer import analyze_all
    exps = owned(Experience).order_by(Experience.created_at).all()
    posting = _posting_or_none(request.args.get("posting_id", type=int))
    data = suggest_for_question(request.args.get("q", ""), exps, {a["id"]: a for a in analyze_all(exps)}, posting)
    return jsonify(data)


@bp.route("/draft", methods=["POST"])
@login_required
def draft():
    """✦ AI 답변 초안(JSON): 고른 경험만 근거로. 원문에 없는 숫자가 든 문장은 빼고 알려 줌. 저장은 사용자가."""
    from ..integrations import ai_client
    if not ai_client.enabled():
        return jsonify({"error": ai_client.unavailable_message() + " 'STAR 뼈대 넣기'로 직접 써 볼 수도 있어요."}), 400
    ids = [int(x) for x in (request.form.get("exp_ids") or "").split(",") if x.strip().isdigit()][:3]
    exps = [get_owned_or_404(Experience, i) for i in ids]
    if not exps:
        return jsonify({"error": "먼저 '경험 추천'에서 이 문항에 쓸 경험을 골라 주세요."}), 400
    posting = _posting_or_none(request.form.get("posting_id", type=int))
    question = (request.form.get("q") or "").strip()[:500]
    role = (posting.role_code if posting and posting.role_code in ROLE_BY_CODE else "") or "overseas_sales"
    try:
        data = ai_client.draft_answer(question, request.form.get("limit", ""), exps,
                                      posting.posting_text if posting else "", ROLE_BY_CODE[role]["name"])
    except ai_client.AiError as exc:
        return jsonify({"error": str(exc)}), 502
    source = "\n".join([question, request.form.get("limit", "")] + [e.full_text for e in exps]
                        + [posting.posting_text if posting else ""])
    answer, notes = check_answer_draft(data.get("answer", ""), source)
    return jsonify({"answer": answer, "notes": notes, "missing": data.get("missing", []),
                    "exp_ids": [e.id for e in exps]})


@bp.route("/<int:rec_id>/delete", methods=["POST"])
@login_required
def delete(rec_id):
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    db.session.delete(rec)
    db.session.commit()
    flash(f"'{rec.company}' 지원 기록을 지웠어요.", "info")
    return redirect(url_for("applications.index"))


@bp.route("/compare")
@login_required
def compare():
    ids = [int(i) for i in request.args.getlist("ids") if i.isdigit()][:3]
    if len(ids) < 2:
        flash("비교할 지원 기록을 2~3개 골라 주세요.", "error")
        return redirect(url_for("applications.index"))
    recs = [get_owned_or_404(ApplicationRecord, i) for i in ids]
    exps = owned(Experience).all()
    used = {r.id: used_experiences("\n".join(i.get("a", "") for i in r.qa), exps) for r in recs}
    # 여러 지원서에 같이 쓴 경험(재사용) 찾기
    counter = {}
    for r in recs:
        for e in used[r.id]:
            counter.setdefault(e.id, [e, 0])[1] += 1
    shared = [e for e, n in counter.values() if n >= 2]
    rows = max((len(r.qa) for r in recs), default=0)
    return render_template("applications/compare.html", recs=recs, used=used, shared=shared, rows=rows,
                           role_map=ROLE_BY_CODE)
