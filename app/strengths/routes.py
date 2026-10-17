from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required

from ..core.scoping import create_owned, get_owned_or_404, owned
from ..core.trade_roles import ROLE_BY_CODE
from ..experiences.analyzer import analyze_all, recommend_roles
from ..experiences.models import Experience
from ..experiences.parser import extract_text
from ..extensions import db
from ..integrations import ai_client
from . import bp
from .models import StrengthProfile
from .services import (dump, experiences_hash, latest_profile, link_strengths, matrix, parse_strengths,
                       profile_history)

ALLOWED = {"pdf", "docx", "txt", "md"}


def _role(exps) -> str:
    role = request.values.get("role")
    if role in ROLE_BY_CODE:
        return role
    if session.get("exp_role") in ROLE_BY_CODE:
        return session["exp_role"]
    recs = recommend_roles(analyze_all(exps))
    return recs[0]["code"] if recs else "overseas_sales"


@bp.route("/")
@login_required
def index():
    exps = owned(Experience).order_by(Experience.created_at).all()
    profile = latest_profile()
    role = _role(exps)
    linked, mat, ai, ai_stale = [], None, None, False
    if profile:
        linked = link_strengths(profile.strengths, exps)
        mat = matrix(linked, exps)
        if profile.ai_json:
            ai = profile.ai
            ai_stale = profile.ai_role != role or profile.ai_hash != experiences_hash(exps, role, profile.id)
    return render_template("strengths/index.html", profile=profile, linked=linked, mat=mat, ai=ai,
                           ai_stale=ai_stale, ai_role_name=ROLE_BY_CODE.get(profile.ai_role, {}).get("name", "")
                           if profile else "", role=role, role_name=ROLE_BY_CODE[role]["name"],
                           exps={e.id: e for e in exps}, exp_count=len(exps), ai_enabled=ai_client.enabled(),
                           history=profile_history())


@bp.route("/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    pasted = (request.form.get("pasted") or "").strip()
    filename, text = "직접 붙여넣은 결과", pasted
    if f and f.filename:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED:
            flash("강점 결과지는 pdf, docx, txt, md 파일만 올릴 수 있어요.", "error")
            return redirect(url_for("strengths.index"))
        try:
            text = extract_text(f.filename, f.read())
        except Exception as exc:
            current_app.logger.exception("강점 결과지 읽기 실패: %s", f.filename)
            flash(f"파일을 읽지 못했어요({exc.__class__.__name__}). 내용을 복사해 '직접 붙여넣기'로 넣어 보세요.", "error")
            return redirect(url_for("strengths.index"))
        filename = f.filename[:255]
    if len(text.strip()) < 30:
        flash("결과지에서 글자를 거의 읽지 못했어요. 스캔 이미지 PDF라면 결과 내용을 복사해 붙여넣어 주세요.", "error")
        return redirect(url_for("strengths.index"))
    parsed = parse_strengths(text)
    # 새 결과지를 '사용 중'으로, 이전 결과지는 저장본으로 남겨 두고 언제든 다시 불러올 수 있게
    for old in owned(StrengthProfile).all():
        old.is_active = False
    create_owned(StrengthProfile, filename=filename, extracted_text=text[:200000], parsed_json=dump(parsed),
                 is_active=True)
    db.session.commit()
    names = ", ".join(s["name"] for s in parsed["strengths"][:5])
    if parsed["strengths"]:
        flash(f"강점 {len(parsed['strengths'])}개를 찾았어요: {names}. 내 경험과 연결해 보여 드릴게요.", "success")
    else:
        flash("결과지는 저장했지만 강점 이름을 찾지 못했어요. AI 분석을 쓰거나 결과지 형식을 확인해 주세요.", "info")
    return redirect(url_for("strengths.index"))


@bp.route("/ai", methods=["POST"])
@login_required
def ai_link():
    profile = latest_profile()
    if not profile:
        flash("먼저 강점 결과지를 올려 주세요.", "error")
        return redirect(url_for("strengths.index"))
    if not ai_client.enabled():
        flash("AI 분석을 쓰려면 .env 에 OPENAI_API_KEY 를 넣고 서버를 다시 켜 주세요.", "info")
        return redirect(url_for("strengths.index"))
    exps = owned(Experience).order_by(Experience.created_at).all()
    if not exps:
        flash("연결할 경험이 아직 없어요. 경험 분석 화면에서 이력을 먼저 넣어 주세요.", "error")
        return redirect(url_for("strengths.index"))
    role = _role(exps)
    try:
        data, truncated = ai_client.link_strengths_ai(profile.extracted_text, [s["name"] for s in profile.strengths],
                                                       exps, ROLE_BY_CODE[role]["name"])
    except ai_client.AiError as exc:
        flash(str(exc), "error")
        return redirect(url_for("strengths.index"))
    profile.ai_json = dump(data)
    profile.ai_role = role
    profile.ai_hash = experiences_hash(exps, role, profile.id)
    db.session.commit()
    msg = f"{ROLE_BY_CODE[role]['name']} 기준으로 강점과 경험을 연결했어요."
    if truncated:
        msg += f" 결과지가 길어 앞 {ai_client.REPORT_CHAR_LIMIT:,}자만 분석했어요."
    flash(msg, "success")
    return redirect(url_for("strengths.index", _anchor="ai"))


@bp.route("/<int:profile_id>/activate", methods=["POST"])
@login_required
def activate(profile_id):
    """저장해 둔 강점 결과지 불러오기."""
    target = get_owned_or_404(StrengthProfile, profile_id)
    for p in owned(StrengthProfile).all():
        p.is_active = p.id == target.id
    db.session.commit()
    flash(f"'{target.filename}' 결과지를 불러왔어요.", "success")
    return redirect(url_for("strengths.index"))


@bp.route("/<int:profile_id>/delete", methods=["POST"])
@login_required
def delete_one(profile_id):
    target = get_owned_or_404(StrengthProfile, profile_id)
    was_active = target.is_active
    db.session.delete(target)
    db.session.flush()
    if was_active:  # 지운 게 사용 중이었으면 가장 최근 결과지를 사용 중으로
        nxt = owned(StrengthProfile).order_by(StrengthProfile.created_at.desc()).first()
        if nxt:
            nxt.is_active = True
    db.session.commit()
    flash(f"'{target.filename}' 결과지를 지웠어요.", "info")
    return redirect(url_for("strengths.index"))


@bp.route("/delete", methods=["POST"])
@login_required
def delete():
    """강점 결과지 전부 지우기."""
    for p in owned(StrengthProfile).all():
        db.session.delete(p)
    db.session.commit()
    flash("강점 결과지를 모두 지웠어요.", "info")
    return redirect(url_for("strengths.index"))
