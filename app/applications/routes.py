from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..core.scoping import create_owned, get_owned_or_404, owned
from ..core.trade_roles import ROLE_BY_CODE
from ..experiences.analyzer import role_options
from ..experiences.models import Experience, PostingAnalysis
from ..extensions import db
from . import bp
from .models import STATUSES, ApplicationRecord
from .services import dump_qa, read_qa, used_experiences

FIELDS = ("company", "position", "role_code", "status", "applied_at", "deadline", "url",
          "company_info", "talent", "notes")
LIMITS = {"company": 120, "position": 200, "role_code": 40, "status": 20, "applied_at": 40, "deadline": 40}


def _form_fields() -> dict:
    out = {}
    for f in FIELDS:
        v = (request.form.get(f) or "").strip()
        out[f] = v[:LIMITS[f]] if f in LIMITS else v
    if out["status"] not in STATUSES:
        out["status"] = STATUSES[0]
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
        db.session.commit()
        flash(f"'{rec.company}' 지원 기록을 저장했어요.", "success")
        return redirect(url_for("applications.detail", rec_id=rec.id))
    # 공고 매칭에서 넘어오면 회사·공고 정보를 미리 채움
    posting = _posting_or_none(request.args.get("posting", type=int))
    prefill = {}
    if posting:
        prefill = {"company": posting.company or "", "position": posting.title or "", "url": posting.url or "",
                   "role_code": posting.result.get("main_role", ""), "posting_id": posting.id}
    return render_template("applications/form.html", rec=None, form=prefill, qa=[], **_form_context())


def _form_context() -> dict:
    postings = owned(PostingAnalysis).order_by(PostingAnalysis.created_at.desc()).all()
    return {"statuses": STATUSES, "roles": role_options(), "postings": postings}


@bp.route("/<int:rec_id>")
@login_required
def detail(rec_id):
    rec = get_owned_or_404(ApplicationRecord, rec_id)
    exps = owned(Experience).all()
    used = {i: used_experiences(item.get("a", ""), exps) for i, item in enumerate(rec.qa)}
    all_used = {e.id: e for lst in used.values() for e in lst}
    posting = db.session.get(PostingAnalysis, rec.posting_id) if rec.posting_id else None
    if posting and posting.user_id != rec.user_id:
        posting = None
    return render_template("applications/detail.html", rec=rec, used=used, all_used=list(all_used.values()),
                           posting=posting, role_map=ROLE_BY_CODE)


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
        rec.qa_json = dump_qa(read_qa(request.form))
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
        db.session.commit()
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url)
                    else url_for("applications.detail", rec_id=rec.id))


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
