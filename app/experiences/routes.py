import json
from datetime import datetime

from flask import Response, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required

from ..core.scoping import create_owned, get_owned_or_404, owned
from ..core.trade_roles import GROUP_BY_CODE, ROLE_BY_CODE, ROLE_GROUPS, TRADE_ROLES
from ..extensions import db
from ..integrations import ai_client
from . import bp
from .analyzer import analyze_all, essay_question_for, recommend_roles, role_options, role_profile
from .backup import MAX_FILE_BYTES, build_data, restore, save_snapshot, validate
from .models import (CATEGORIES, Certificate, Experience, ExperienceUpload, PostingAnalysis, Snapshot,
                     TopExclusion)
from .parser import allowed, extract_text, is_spreadsheet, parse_spreadsheet, split_experiences
from .posting import PostingFetchError, analyze_posting, clean_posting_text, fetch_posting, has_body
from .services import (certificate_from_item, excluded_ids, generate_comments, rule_comment, saved_comments,
                       upsert_certificate, upsert_experience)

CERT_CATEGORY = "자격증·어학"
EXP_CATEGORIES = [c for c in CATEGORIES if c != CERT_CATEGORY]  # 경험 분류(자격증은 따로 관리)


def _selected_role(default: str):
    """주소의 ?role= → 지난번 고른 직무(세션) → 추천 1위 직무 순으로 정합니다. (그룹, 직무, 자동으로 골랐는지)"""
    role = request.args.get("role")
    group = request.args.get("group")
    if role not in ROLE_BY_CODE and group in GROUP_BY_CODE:
        role = next((r["code"] for r in TRADE_ROLES if r["group"] == group), None)
    auto = False
    if role not in ROLE_BY_CODE:
        role = session.get("exp_role")
    if role not in ROLE_BY_CODE:
        role, auto = default, True
    else:
        session["exp_role"] = role
    return ROLE_BY_CODE[role]["group"], role, auto


def _rank(analyses: list[dict], role: str) -> list[dict]:
    return sorted(analyses, key=lambda a: (a["roles"][role]["score"], a["strength"]), reverse=True)


def _top3(analyses: list[dict], role: str, skip: set[int]) -> list[dict]:
    """'TOP 3에서 빼기'한 경험은 건너뛰고 다음 순위를 올립니다."""
    return [a for a in _rank(analyses, role) if a["roles"][role]["score"] > 0 and a["id"] not in skip][:3]


def _cert_views(certs, role: str) -> list[dict]:
    views = []
    for c in certs:
        ev = c.evaluation
        top = sorted(ev["roles"].items(), key=lambda kv: kv[1], reverse=True)[:3]
        views.append({"c": c, "rel": ev["roles"].get(role, 0), "reason": ev["reason"], "known": ev["known"],
                      "top": [(ROLE_BY_CODE[k]["name"], v) for k, v in top if v > 0]})
    return sorted(views, key=lambda v: v["rel"], reverse=True)


@bp.route("/")
@login_required
def index():
    exps = owned(Experience).order_by(Experience.created_at).all()
    certs = owned(Certificate).order_by(Certificate.created_at).all()
    analyses = analyze_all(exps)
    by_id = {a["id"]: a for a in analyses}
    recs = recommend_roles(analyses, certs=certs)
    if request.args.get("auto"):  # '추천 1위로 돌아가기' → 직접 고른 직무 기억을 지움
        session.pop("exp_role", None)
    group, role, auto = _selected_role(recs[0]["code"] if recs else "overseas_sales")
    skip = excluded_ids(role)
    top3 = _top3(analyses, role, skip)
    for a in top3:
        a["question"] = essay_question_for(a)
    excluded = [by_id[i] for i in skip if i in by_id]
    ranked = _rank(analyses, role)

    prof = role_profile(analyses, certs)
    chart = {
        "radar_labels": [r["name"].split("(")[0] for r in TRADE_ROLES],
        "radar_values": [prof[r["code"]] for r in TRADE_ROLES],
        "radar_selected": [r["code"] for r in TRADE_ROLES].index(role),
        "bar_labels": [a["title"] if len(a["title"]) <= 22 else a["title"][:21] + "…" for a in ranked],
        "bar_fit": [a["roles"][role]["score"] for a in ranked],
        "bar_strength": [a["strength"] for a in ranked],
    }
    uploads = owned(ExperienceUpload).order_by(ExperienceUpload.created_at.desc()).all()
    upload_counts = {u.id: sum(1 for e in exps if e.upload_id == u.id) for u in uploads}
    role_name = ROLE_BY_CODE[role]["name"]
    comments = _comment_views(exps, by_id, role, role_name)
    cat_counts = {c: sum(1 for e in exps if e.category == c) for c in EXP_CATEGORIES}
    cat_counts = {c: n for c, n in cat_counts.items() if n}
    snapshots = owned(Snapshot).order_by(Snapshot.created_at.desc()).all()
    return render_template("experiences/index.html", exps=exps, analyses=by_id, top3=top3, excluded=excluded,
                           role=role, group=group, role_name=role_name, group_name=GROUP_BY_CODE[group]["name"],
                           groups=ROLE_GROUPS, roles=role_options(), chart=chart, uploads=uploads,
                           categories=EXP_CATEGORIES, comments=comments, certs=_cert_views(certs, role),
                           ai_enabled=ai_client.enabled(), upload_counts=upload_counts, recs=recs, auto_role=auto,
                           cat_counts=cat_counts, snapshots=snapshots)


@bp.route("/report")
@login_required
def report():
    """내 이력 정리 인쇄용 페이지. 브라우저의 'PDF로 저장'으로 PDF를 만듭니다(한글 글꼴 문제 없음)."""
    from datetime import date

    from ..strengths.services import latest_profile
    exps = owned(Experience).order_by(Experience.created_at).all()
    certs = owned(Certificate).order_by(Certificate.created_at).all()
    analyses = analyze_all(exps)
    by_id = {a["id"]: a for a in analyses}
    recs = recommend_roles(analyses, certs=certs)
    role = request.args.get("role")
    if role not in ROLE_BY_CODE:
        role = session.get("exp_role") if session.get("exp_role") in ROLE_BY_CODE else (
            recs[0]["code"] if recs else "overseas_sales")
    role_name = ROLE_BY_CODE[role]["name"]
    top3 = _top3(analyses, role, excluded_ids(role))
    comments = _comment_views(exps, by_id, role, role_name)
    groups = [(c, [e for e in exps if e.category == c]) for c in EXP_CATEGORIES]
    return render_template("experiences/report.html", recs=recs, role=role, role_name=role_name, top3=top3,
                           comments=comments, certs=_cert_views(certs, role), groups=[g for g in groups if g[1]],
                           analyses=by_id, today=date.today(), strength_profile=latest_profile(), exp_count=len(exps))


def _comment_views(exps, analyses: dict, role: str, role_name: str) -> dict:
    """{경험 id: {"data": 코멘트, "ai": AI가 쓴 것인지, "fresh": 경험 내용이 바뀌지 않았는지}}"""
    saved = saved_comments(role)
    views = {}
    for e in exps:
        c = saved.get(e.id)
        if c:
            views[e.id] = {"data": c.data, "ai": True, "fresh": c.content_hash == e.content_hash}
        else:
            views[e.id] = {"data": rule_comment(analyses[e.id], role, role_name), "ai": False, "fresh": True}
    return views


# ── 이력 올리기·추가 ────────────────────────────────────────────────

@bp.route("/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("업로드할 파일을 선택해 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-file"))
    if not allowed(f.filename):
        flash("xlsx, xls, csv, docx, pdf, txt, md 파일만 올릴 수 있어요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-file"))
    try:
        data = f.read()
        if is_spreadsheet(f.filename):
            text, items = parse_spreadsheet(f.filename, data)
        else:
            text = extract_text(f.filename, data)
            items = split_experiences(text)
    except ImportError as exc:
        current_app.logger.exception("경험정리 업로드: 라이브러리 없음")
        flash(f"이 파일 형식을 읽는 라이브러리({exc.name})가 설치돼 있지 않아요. "
              "VS Code 터미널에서 'pip install -r requirements.txt'를 실행한 뒤 서버를 다시 켜 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-file"))
    except Exception as exc:
        current_app.logger.exception("경험정리 업로드 실패: %s", f.filename)
        flash(f"파일을 읽지 못했어요({exc.__class__.__name__}). 암호가 걸려 있거나 손상된 파일인지 확인해 주세요. "
              "엑셀이라면 .xlsx로 다시 저장해서 올려 보세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-file"))
    if not items:
        flash("파일에서 경험 내용을 찾지 못했어요. 스캔 이미지 PDF라면 텍스트 파일로 바꿔 올려 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-file"))
    up = create_owned(ExperienceUpload, filename=f.filename[:255], extracted_text=text[:200000], item_count=len(items))
    db.session.flush()
    added = updated = cert_n = 0
    for it in items:
        if it.get("category") == CERT_CATEGORY:  # 자격증·어학 행은 경험이 아니라 자격증으로
            upsert_certificate(**certificate_from_item(it))
            cert_n += 1
            continue
        _exp, created = upsert_experience(it, source="upload", upload_id=up.id)
        db.session.flush()  # 같은 파일 안의 같은 제목도 하나로 합쳐지도록
        added += created
        updated += not created
    db.session.commit()
    msg = f"'{f.filename}'에서 {len(items)}개를 읽었어요. 새 경험 {added}개"
    msg += f", 기존 경험 업데이트 {updated}개" if updated else ""
    msg += f", 자격증·어학 {cert_n}개" if cert_n else ""
    flash(msg + ". 분석에 바로 반영했어요.", "success")
    return redirect(url_for("experiences.index"))


def _form_fields() -> dict:
    get = lambda k: (request.form.get(k) or "").strip()  # noqa: E731
    cat = get("category")
    return {"title": get("title")[:200], "category": cat if cat in EXP_CATEGORIES else "",
            "organization": get("organization")[:120], "period": get("period")[:60],
            **{f: get(f) for f in Experience.TEXT_FIELDS}}


@bp.route("/save", methods=["POST"])
@login_required
def save():
    """새 경험 추가 또는 기존 경험에 내용 덧붙이기(파일 없이)."""
    fields = _form_fields()
    target_id = request.form.get("target_id", type=int)
    target = get_owned_or_404(Experience, target_id) if target_id else None
    if not target and not fields["title"]:
        flash("새 경험이라면 경험 이름을 적어 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-exp"))
    if not any(fields[f] for f in Experience.TEXT_FIELDS) and not target and not fields["organization"]:
        flash("역할·내용·강점·키워드·느낀점 중 하나 이상을 적어 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-exp"))
    exp, created = upsert_experience(fields, target=target)
    db.session.commit()
    flash(f"'{exp.title}' 경험을 {'추가' if created else '업데이트'}했어요. 분석에 바로 반영됐어요.", "success")
    return redirect(url_for("experiences.index"))


# ── 자격증·어학 ─────────────────────────────────────────────────────

@bp.route("/certificate", methods=["POST"])
@login_required
def add_certificate():
    """자격증·어학 추가(같은 이름이면 업데이트)."""
    get = lambda k: (request.form.get(k) or "").strip()  # noqa: E731
    if not get("cert_name"):
        flash("자격증·어학 시험 이름을 적어 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-cert"))
    cert, created = upsert_certificate(get("cert_name"), get("cert_score"), get("cert_issuer"),
                                       get("cert_date"), get("cert_note"))
    db.session.commit()
    flash(f"자격증 '{cert.name}'을(를) {'추가' if created else '업데이트'}했어요.", "success")
    return redirect(url_for("experiences.index", _anchor="certs"))


@bp.route("/certificate/<int:cert_id>/edit", methods=["GET", "POST"])
@login_required
def edit_certificate(cert_id):
    cert = get_owned_or_404(Certificate, cert_id)
    if request.method == "POST":
        get = lambda k: (request.form.get(k) or "").strip()  # noqa: E731
        cert.name = get("cert_name")[:120] or cert.name
        cert.score, cert.acquired = get("cert_score")[:60], get("cert_date")[:40]
        cert.issuer, cert.note = get("cert_issuer")[:120], get("cert_note")
        db.session.commit()
        flash("자격증을 수정했어요.", "success")
        return redirect(url_for("experiences.index", _anchor="certs"))
    return render_template("experiences/cert_edit.html", cert=cert)


@bp.route("/certificate/<int:cert_id>/delete", methods=["POST"])
@login_required
def delete_certificate(cert_id):
    cert = get_owned_or_404(Certificate, cert_id)
    db.session.delete(cert)
    db.session.commit()
    flash(f"자격증 '{cert.name}'을(를) 지웠어요.", "info")
    return redirect(url_for("experiences.index", _anchor="certs"))


# ── TOP 3 에서 빼기 / 되돌리기 ───────────────────────────────────────

def _role_from_form() -> str:
    for role in (request.form.get("role"), session.get("exp_role")):
        if role in ROLE_BY_CODE:
            return role
    return "overseas_sales"


@bp.route("/<int:exp_id>/exclude", methods=["POST"])
@login_required
def exclude(exp_id):
    exp = get_owned_or_404(Experience, exp_id)
    role = _role_from_form()
    if exp.id not in excluded_ids(role):
        create_owned(TopExclusion, experience_id=exp.id, role_code=role)
        db.session.commit()
    flash(f"'{exp.title}'을(를) {ROLE_BY_CODE[role]['name']} TOP 3에서 뺐어요. 다음 순위 경험이 올라왔어요.", "info")
    return redirect(url_for("experiences.index", role=role, _anchor="top3"))


@bp.route("/<int:exp_id>/include", methods=["POST"])
@login_required
def include(exp_id):
    exp = get_owned_or_404(Experience, exp_id)
    role = _role_from_form()
    for x in owned(TopExclusion).filter(TopExclusion.experience_id == exp.id, TopExclusion.role_code == role):
        db.session.delete(x)
    db.session.commit()
    flash(f"'{exp.title}'을(를) 다시 순위에 넣었어요.", "success")
    return redirect(url_for("experiences.index", role=role, _anchor="top3"))


# ── AI 코멘트 ──────────────────────────────────────────────────────

@bp.route("/comments", methods=["POST"])
@login_required
def make_comments():
    """선택한 경험(또는 TOP 3)에 지금 직무 기준 AI 자소서 코멘트를 받습니다."""
    role = request.form.get("role")
    if role not in ROLE_BY_CODE:
        role = session.get("exp_role") if session.get("exp_role") in ROLE_BY_CODE else "overseas_sales"
    back = url_for("experiences.index", role=role, _anchor=request.form.get("anchor") or "top3")
    if not ai_client.enabled():
        flash("AI 코멘트를 받으려면 .env 파일에 OPENAI_API_KEY 를 넣고 서버를 다시 켜 주세요. "
              "지금은 규칙 기반 기본 코멘트를 보여 드려요.", "info")
        return redirect(back)
    ids = [int(i) for i in request.form.getlist("exp_id") if i.isdigit()]
    exps = [get_owned_or_404(Experience, i) for i in ids]
    if not exps:
        flash("코멘트를 받을 경험을 골라 주세요.", "error")
        return redirect(back)
    analyses = {a["id"]: a for a in analyze_all(exps)}
    try:
        n = generate_comments(exps, analyses, role, ROLE_BY_CODE[role]["name"])
    except ai_client.AiError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(back)
    db.session.commit()
    flash(f"{ROLE_BY_CODE[role]['name']} 기준 AI 코멘트 {n}개를 받았어요.", "success")
    return redirect(back)


@bp.route("/<int:exp_id>/edit", methods=["GET", "POST"])
@login_required
def edit(exp_id):
    exp = get_owned_or_404(Experience, exp_id)
    if request.method == "POST":
        fields = _form_fields()
        exp.title = fields["title"] or exp.title
        exp.category = fields["category"] or "기타"
        for k in ("organization", "period", *Experience.TEXT_FIELDS):
            setattr(exp, k, fields[k])
        db.session.commit()
        flash("수정했어요. 분석 결과도 함께 갱신됩니다.", "success")
        return redirect(url_for("experiences.index"))
    return render_template("experiences/edit.html", exp=exp, categories=EXP_CATEGORIES)


@bp.route("/<int:exp_id>/delete", methods=["POST"])
@login_required
def delete(exp_id):
    exp = get_owned_or_404(Experience, exp_id)
    db.session.delete(exp)
    db.session.commit()
    flash("삭제했어요.", "info")
    return redirect(url_for("experiences.index"))


# ── 내 데이터: 업로드 기록 · 저장본 저장/불러오기/파일 ───────────────────

@bp.route("/uploads/<int:upload_id>/delete", methods=["POST"])
@login_required
def delete_upload(upload_id):
    """이 파일로 들어온 경험(이후 덧붙인 내용 포함)과 업로드 기록을 지웁니다."""
    up = get_owned_or_404(ExperienceUpload, upload_id)
    exps = owned(Experience).filter(Experience.upload_id == up.id).all()
    for e in exps:
        db.session.delete(e)
    db.session.delete(up)
    db.session.commit()
    flash(f"'{up.filename}'로 들어온 경험 {len(exps)}개를 지웠어요.", "info")
    return redirect(url_for("experiences.index", _anchor="tab-data"))


@bp.route("/reset", methods=["POST"])
@login_required
def reset_all():
    """내 경험·자격증·업로드 기록·AI 코멘트·공고 분석을 모두 지웁니다(계정과 저장본은 유지)."""
    if request.form.get("confirm") != "삭제":
        flash("확인 칸에 '삭제'라고 적어야 지울 수 있어요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-data"))
    save_snapshot(f"전체 지우기 전 자동 저장 · {datetime.now():%m/%d %H:%M}")
    n = 0
    for model in (Experience, Certificate, ExperienceUpload, PostingAnalysis):
        for row in owned(model).all():
            db.session.delete(row)
            n += model is Experience
    db.session.commit()
    flash(f"내 이력 {n}개와 자격증·업로드·분석 기록을 지웠어요. 지우기 전 상태는 저장본에 남겨 뒀어요.", "info")
    return redirect(url_for("experiences.index"))


@bp.route("/data/save", methods=["POST"])
@login_required
def snapshot_save():
    name = (request.form.get("name") or "").strip() or f"저장본 · {datetime.now():%Y.%m.%d %H:%M}"
    snap = save_snapshot(name)
    db.session.commit()
    flash(f"'{snap.name}'으로 저장했어요(경험 {snap.exp_count}개 · 자격증 {snap.cert_count}개"
          f"{' · 강점 결과지' if snap.has_strength else ''}).", "success")
    return redirect(url_for("experiences.index", _anchor="tab-data"))


@bp.route("/data/<int:snap_id>/load", methods=["POST"])
@login_required
def snapshot_load(snap_id):
    snap = get_owned_or_404(Snapshot, snap_id)
    parts = request.form.getlist("parts") or ["experiences", "strength", "applications"]
    try:
        data = validate(snap.data)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("experiences.index", _anchor="tab-data"))
    r = restore(data, experiences="experiences" in parts, strength="strength" in parts,
                applications="applications" in parts)
    db.session.commit()
    done = []
    if "experiences" in parts:
        done.append(f"경험 {r['experiences']}개 · 자격증 {r['certificates']}개")
    if r["strength"]:
        done.append("강점 결과지")
    if r["applications"]:
        done.append(f"자소서 {r['applications']}개")
    flash(f"'{snap.name}'을(를) 불러왔어요({', '.join(done) or '바뀐 내용 없음'}). 불러오기 전 상태는 자동 저장했어요.", "success")
    return redirect(url_for("experiences.index"))


@bp.route("/data/<int:snap_id>/delete", methods=["POST"])
@login_required
def snapshot_delete(snap_id):
    snap = get_owned_or_404(Snapshot, snap_id)
    db.session.delete(snap)
    db.session.commit()
    flash(f"저장본 '{snap.name}'을(를) 지웠어요.", "info")
    return redirect(url_for("experiences.index", _anchor="tab-data"))


def _json_download(data: dict, stem: str) -> Response:
    body = json.dumps(data, ensure_ascii=False, indent=1)
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="{stem}-{datetime.now():%Y%m%d-%H%M}.json"'})


@bp.route("/data/export")
@login_required
def export_current():
    """지금 데이터를 .json 저장본 파일로 내려받기."""
    return _json_download(build_data(), "growly-backup")


@bp.route("/data/<int:snap_id>/download")
@login_required
def snapshot_download(snap_id):
    snap = get_owned_or_404(Snapshot, snap_id)
    return _json_download(snap.data, f"growly-snapshot-{snap.id}")


@bp.route("/data/import", methods=["POST"])
@login_required
def snapshot_import():
    """내려받아 둔 .json 저장본 파일을 올리면 저장본 목록에 추가합니다(불러오기는 따로)."""
    f = request.files.get("file")
    if not f or not f.filename:
        flash("올릴 저장본 파일(.json)을 골라 주세요.", "error")
        return redirect(url_for("experiences.index", _anchor="tab-data"))
    raw = f.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        flash("저장본 파일이 너무 커요(최대 5MB).", "error")
        return redirect(url_for("experiences.index", _anchor="tab-data"))
    try:
        data = validate(json.loads(raw.decode("utf-8-sig")))
    except (ValueError, UnicodeDecodeError) as exc:
        msg = str(exc) if isinstance(exc, ValueError) and "GROWLY" in str(exc) else "저장본 파일을 읽지 못했어요."
        flash(msg, "error")
        return redirect(url_for("experiences.index", _anchor="tab-data"))
    snap = save_snapshot(f"파일에서 가져옴 · {f.filename[:60]}", data)
    db.session.commit()
    flash(f"'{f.filename}'을(를) 저장본으로 추가했어요(경험 {snap.exp_count}개 · 자격증 {snap.cert_count}개). "
          "'불러오기'를 누르면 지금 데이터로 바뀌어요.", "success")
    return redirect(url_for("experiences.index", _anchor="tab-data"))


# ── 공고 매칭 ───────────────────────────────────────────────────────

def _match_inputs():
    """공고 매칭에 쓰는 내 데이터: 경험, 분석, 자격증, 강점(결과지와 연결 결과)."""
    from ..strengths.services import latest_profile, link_strengths
    exps = owned(Experience).order_by(Experience.created_at).all()
    certs = owned(Certificate).all()
    profile = latest_profile()
    linked = link_strengths(profile.strengths, exps) if profile else []
    return exps, certs, profile, linked


def _data_hash(exps, certs, profile) -> str:
    import hashlib
    raw = "|".join([e.content_hash for e in exps] + [f"{c.name}:{c.score}" for c in certs]
                   + [str(profile.id) if profile else "-"])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _analyze_text(text: str) -> dict:
    exps, certs, _profile, linked = _match_inputs()
    return analyze_posting(text, analyze_all(exps), {e.id: e for e in exps}, certs=certs, strengths=linked)


def _postings() -> dict:
    """공고 매칭 화면 목록: ★저장한 공고(산업·직무 필터) + 최근 조회 기록(저장 안 한 분석)."""
    from ..core.industries import INDUSTRIES
    q = (request.args.get("q") or "").strip()
    ind = request.args.get("ind", "")
    role = request.args.get("prole", "")
    base = owned(PostingAnalysis)
    if q:
        like = f"%{q}%"
        base = base.filter(db.or_(PostingAnalysis.company.ilike(like), PostingAnalysis.title.ilike(like),
                                  PostingAnalysis.memo.ilike(like)))
    saved_all = base.filter(PostingAnalysis.is_saved.is_(True)).order_by(PostingAnalysis.saved_at.desc(),
                                                                        PostingAnalysis.created_at.desc()).all()
    saved = [p for p in saved_all if (not ind or p.industry == ind) and (not role or p.role_code == role)]
    history = base.filter(PostingAnalysis.is_saved.is_(False)).order_by(PostingAnalysis.created_at.desc()).all()
    ind_counts = {c: sum(1 for p in saved_all if p.industry == c) for c, _n, _w in INDUSTRIES}
    role_counts = {}
    for p in saved_all:
        if p.role_code in ROLE_BY_CODE:
            role_counts[p.role_code] = role_counts.get(p.role_code, 0) + 1
    return {"saved": saved, "saved_total": len(saved_all), "history": history, "q": q, "ind": ind, "prole": role,
            "industries": [(c, n) for c, n, _w in INDUSTRIES if ind_counts[c]], "ind_counts": ind_counts,
            "role_facets": sorted(((c, ROLE_BY_CODE[c]["name"], n) for c, n in role_counts.items()), key=lambda x: -x[2]),
            "role_map": ROLE_BY_CODE, "all_industries": [(c, n) for c, n, _w in INDUSTRIES], "all_roles": role_options()}


@bp.route("/posting", methods=["GET", "POST"])
@login_required
def posting():
    ctx = _postings()
    if request.method == "GET":
        return render_template("experiences/posting.html", analysis=None, **ctx)

    url = (request.form.get("url") or "").strip()
    pasted = (request.form.get("posting_text") or "").strip()
    company = (request.form.get("company") or "").strip()[:120]
    title, text = "", clean_posting_text(pasted) if pasted else ""
    if url and not pasted:
        try:
            title, text = fetch_posting(url)
        except PostingFetchError as exc:
            flash(str(exc), "error")
            return render_template("experiences/posting.html", analysis=None, form=request.form, **ctx)
    if len(text) < 80:
        flash("공고 내용을 충분히 읽지 못했어요(로그인·앱 전용 페이지일 수 있음). 공고 본문을 복사해 붙여 넣어 주세요.",
              "error")
        return render_template("experiences/posting.html", analysis=None, form=request.form, **ctx)

    if not owned(Experience).count():
        flash("먼저 경험 분석 화면에서 경험을 올리거나 추가해 주세요.", "error")
        return redirect(url_for("experiences.index"))
    result = _analyze_text(text)
    from ..core.industries import detect_industry
    pa = create_owned(PostingAnalysis, url=url, company=company, title=(title or company or "붙여넣은 공고")[:300],
                      industry=detect_industry(f"{company} {title} {text}"), role_code=result.get("main_role", ""),
                      is_saved=bool(request.form.get("save_now")),
                      posting_text=text[:30000], result_json=json.dumps(result, ensure_ascii=False))
    db.session.commit()
    flash("공고를 분석했어요. 마음에 들면 '★ 공고 저장'을 눌러 보관하세요. 저장하지 않은 분석은 최근 조회 기록에만 남아요."
          if not pa.is_saved else "공고를 분석해 저장했어요.", "success")
    return redirect(url_for("experiences.posting_detail", pa_id=pa.id))


@bp.route("/posting/<int:pa_id>")
@login_required
def posting_detail(pa_id):
    from .posting import doc_lines
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    cleaned = clean_posting_text(pa.posting_text)
    # 예전 버전이 사이트 UI 문구까지 저장한 공고는 열 때 정리·재분석(정리 결과에 본문 제목이 있을 때만)
    if cleaned and cleaned != pa.posting_text and has_body(cleaned):
        pa.posting_text = cleaned
        pa.result_json = json.dumps(_analyze_text(cleaned), ensure_ascii=False)
        db.session.commit()
    ctx = _postings()
    exps, certs, profile, _linked = _match_inputs()
    stale_ai = bool(pa.ai_json) and pa.ai_hash != _data_hash(exps, certs, profile)
    r = pa.result
    # 형광펜: 노랑 = 내 경험과 겹치는 공고 단어, 초록 = 내 강점이 드러나는 단서 단어
    exp_words = sorted({w for rec in r.get("recommendations", [])
                        for w in rec.get("hit_required", []) + rec.get("hit_preferred", []) + rec.get("hit_tokens", [])})
    str_words = sorted({w for s in r.get("strength_matches", []) for w in s.get("words", [])})
    return render_template("experiences/posting.html", analysis=pa, result=r, **ctx,
                           doc=doc_lines(pa.posting_text), exp_words=exp_words, str_words=str_words,
                           exps={e.id: e for e in exps},
                           ai_enabled=ai_client.enabled(), ai=pa.ai, stale_ai=stale_ai,
                           has_strength=profile is not None)


@bp.route("/posting/<int:pa_id>/reanalyze", methods=["POST"])
@login_required
def posting_reanalyze(pa_id):
    """저장해 둔 공고를 지금의 이력·강점·자격증으로 다시 매칭."""
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    cleaned = clean_posting_text(pa.posting_text)
    if has_body(cleaned):
        pa.posting_text = cleaned
    pa.result_json = json.dumps(_analyze_text(pa.posting_text), ensure_ascii=False)
    db.session.commit()
    flash("지금 내 이력으로 다시 매칭했어요.", "success")
    return redirect(url_for("experiences.posting_detail", pa_id=pa.id))


@bp.route("/posting/<int:pa_id>/edit", methods=["POST"])
@login_required
def posting_edit(pa_id):
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    pa.company = (request.form.get("company") or "").strip()[:120]
    pa.title = (request.form.get("title") or pa.title).strip()[:300]
    pa.memo = (request.form.get("memo") or "").strip()[:2000]
    from ..core.industries import INDUSTRY_BY_CODE
    if request.form.get("industry") in INDUSTRY_BY_CODE:
        pa.industry = request.form["industry"]
    if request.form.get("role_code") in ROLE_BY_CODE:
        pa.role_code = request.form["role_code"]
    db.session.commit()
    flash("공고 정보를 저장했어요.", "success")
    return redirect(url_for("experiences.posting_detail", pa_id=pa.id))


@bp.route("/posting/<int:pa_id>/save", methods=["POST"])
@login_required
def posting_save(pa_id):
    """★ 저장 / 저장 취소(취소하면 최근 조회 기록으로 돌아감)."""
    from datetime import datetime, timezone
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    pa.is_saved = not pa.is_saved
    pa.saved_at = datetime.now(timezone.utc) if pa.is_saved else None
    db.session.commit()
    flash("공고를 저장했어요. '저장한 공고'에서 산업·직무별로 모아 볼 수 있어요." if pa.is_saved
          else "저장을 취소했어요. 최근 조회 기록으로 옮겼어요.", "success" if pa.is_saved else "info")
    nxt = request.form.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                    else url_for("experiences.posting_detail", pa_id=pa.id))


@bp.route("/posting/history/clear", methods=["POST"])
@login_required
def posting_history_clear():
    """저장하지 않은 조회 기록을 모두 지웁니다(저장한 공고는 그대로)."""
    rows = owned(PostingAnalysis).filter(PostingAnalysis.is_saved.is_(False)).all()
    for r in rows:
        db.session.delete(r)
    db.session.commit()
    flash(f"최근 조회 기록 {len(rows)}개를 지웠어요. 저장한 공고는 그대로예요.", "info")
    return redirect(url_for("experiences.posting"))


@bp.route("/posting/compare")
@login_required
def posting_compare():
    """저장한 공고 2~4개를 나란히: 매칭 점수·직무·산업·추천 경험·강점·자격증·부족한 키워드."""
    from ..core.industries import INDUSTRY_BY_CODE
    ids = [int(i) for i in request.args.getlist("ids") if i.isdigit()][:4]
    if len(ids) < 2:
        flash("비교할 공고를 2~4개 골라 주세요.", "error")
        return redirect(url_for("experiences.posting"))
    items = [get_owned_or_404(PostingAnalysis, i) for i in ids]
    best = max(items, key=lambda p: (p.result.get("coverage", 0),
                                     (p.result.get("recommendations") or [{}])[0].get("score", 0)))
    return render_template("experiences/posting_compare.html", items=items, best=best, role_map=ROLE_BY_CODE,
                           ind_map=INDUSTRY_BY_CODE)


@bp.route("/posting/<int:pa_id>/ai", methods=["POST"])
@login_required
def posting_ai(pa_id):
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    if not ai_client.enabled():
        flash("AI 매칭 리포트를 받으려면 .env 에 OPENAI_API_KEY 를 넣고 서버를 다시 켜 주세요.", "info")
        return redirect(url_for("experiences.posting_detail", pa_id=pa.id))
    exps, certs, profile, _linked = _match_inputs()
    try:
        data = ai_client.match_posting_ai(pa.posting_text, exps, certs, profile,
                                          pa.result.get("main_role_name", "해외영업"))
    except ai_client.AiError as exc:
        flash(str(exc), "error")
        return redirect(url_for("experiences.posting_detail", pa_id=pa.id))
    pa.ai_json = json.dumps(data, ensure_ascii=False)
    pa.ai_hash = _data_hash(exps, certs, profile)
    db.session.commit()
    flash("AI 매칭 리포트를 받았어요.", "success")
    return redirect(url_for("experiences.posting_detail", pa_id=pa.id, _anchor="ai-report"))


@bp.route("/posting/<int:pa_id>/delete", methods=["POST"])
@login_required
def posting_delete(pa_id):
    pa = get_owned_or_404(PostingAnalysis, pa_id)
    db.session.delete(pa)
    db.session.commit()
    flash(f"'{pa.company or pa.title[:30]}' 공고 기록을 지웠어요.", "info")
    nxt = request.form.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("experiences.posting"))
