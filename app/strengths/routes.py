from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..core.scoping import create_owned, get_owned_or_404, owned
from ..experiences.models import Experience
from ..experiences.parser import extract_text
from ..extensions import db
from . import bp
from .models import StrengthProfile
from .services import (MAX_STRENGTHS, SOURCES, dump, latest_profile, parse_manual, parse_strengths, preview_items,
                       profile_history, strengths_from_form)

ALLOWED = {"pdf", "docx", "txt", "md"}


@bp.route("/")
@login_required
def index():
    return render_template("strengths/index.html", profile=latest_profile(), history=profile_history(),
                           exp_count=owned(Experience).count(), sources=SOURCES)


def _preview(source: str, filename: str, text: str, parsed: dict, profile=None):
    """저장 전 확인 화면. 문서에서 읽은 강점을 그대로 보여 주고, 사용자가 고친 뒤 '저장'해야 반영됩니다."""
    return render_template("strengths/preview.html", source=source, filename=filename, text=text, parsed=parsed,
                           items=preview_items(parsed["strengths"], text), profile=profile, sources=SOURCES,
                           max_strengths=MAX_STRENGTHS)


@bp.route("/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    pasted = (request.form.get("pasted") or "").strip()
    source, filename, text = "paste", "직접 붙여넣은 결과", pasted
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
        source, filename = "file", f.filename[:255]
    if len(text.strip()) < 30:
        flash("결과지에서 글자를 거의 읽지 못했어요. 스캔 이미지 PDF라면 결과 내용을 복사해 붙여넣어 주세요.", "error")
        return redirect(url_for("strengths.index"))
    return _preview(source, filename, text[:200000], parse_strengths(text))


@bp.route("/manual", methods=["POST"])
@login_required
def manual():
    """결과지 없이 강점을 직접 입력('강점: 설명' 한 줄에 하나, 또는 쉼표로 이름만) → 확인 화면."""
    text = (request.form.get("manual") or "").strip()
    parsed = parse_manual(text)
    if not parsed["strengths"]:
        flash("강점을 한 줄에 하나씩 적어 주세요. 예: '신중함: 잘못될 일을 미리 살펴요'", "error")
        return redirect(url_for("strengths.index"))
    return _preview("manual", "직접 입력한 강점", text, parsed)


@bp.route("/<int:profile_id>/edit")
@login_required
def edit(profile_id):
    p = get_owned_or_404(StrengthProfile, profile_id)
    return _preview(p.parsed.get("source") or ("manual" if p.parsed.get("method") == "manual" else "file"),
                    p.filename, p.extracted_text or "", p.parsed, profile=p)


@bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    """확인 화면에서 고친 강점을 저장. profile_id 가 있으면 그 결과지를 고침(아니면 새 결과지로 '사용 중')."""
    source = request.form.get("source") if request.form.get("source") in SOURCES else "paste"
    text = (request.form.get("source_text") or "")[:200000]
    filename = (request.form.get("filename") or SOURCES[source]).strip()[:255]
    strengths = strengths_from_form(request.form, text)
    if not strengths:
        flash("저장할 강점이 없어요. 강점 이름을 하나 이상 남겨 주세요.", "error")
        return redirect(url_for("strengths.index"))
    parsed = {"strengths": strengths, "method": request.form.get("method") or source, "source": source,
              "tool": (request.form.get("tool") or "").strip()[:60],
              "area": (request.form.get("area") or "").strip()[:200], "role": (request.form.get("role") or "").strip()[:200]}
    pid = request.form.get("profile_id", type=int)
    if pid:
        p = get_owned_or_404(StrengthProfile, pid)
        names = {s["name"] for s in strengths}
        dropped = [lk for lk in p.links if lk.strength_name not in names]
        for lk in dropped:  # 이름을 바꾸거나 뺀 강점의 경험 연결은 근거가 사라지므로 지움
            db.session.delete(lk)
        p.parsed_json = dump(parsed)
        db.session.commit()
        flash(f"강점 {len(strengths)}개로 고쳤어요." + (f" 빠진 강점의 경험 연결 {len(dropped)}개를 지웠어요." if dropped else ""),
              "success")
        return redirect(url_for("strengths.index"))
    for old in owned(StrengthProfile).all():
        old.is_active = False
    create_owned(StrengthProfile, filename=filename, extracted_text=text, parsed_json=dump(parsed), is_active=True)
    db.session.commit()
    flash(f"강점 {len(strengths)}개를 저장했어요: {', '.join(s['name'] for s in strengths[:5])}. "
          "AI 분석에서 내 경험과 연결해 보세요.", "success")
    return redirect(url_for("strengths.index"))


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
