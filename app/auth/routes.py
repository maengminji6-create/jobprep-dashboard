from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user

from ..extensions import db
from . import bp
from .services import get_or_create_visitor, make_access_key, user_from_key


@bp.before_app_request
def auto_login():
    """로그인 화면 없이 내 공간으로 자동 접속(정적 파일 요청은 건너뜀)."""
    if request.endpoint == "static" or current_user.is_authenticated:
        return
    login_user(get_or_create_visitor(), remember=True)


@bp.route("/", methods=["GET", "POST"])
@login_required
def me():
    """내 공간: 이름 바꾸기 · 기록 열쇠 만들기."""
    key = None
    if request.method == "POST":
        if request.form.get("action") == "key":
            key = make_access_key(current_user)
        else:
            name = (request.form.get("name") or "").strip()[:80]
            if name:
                current_user.name = name
                db.session.commit()
                flash("이름을 바꿨어요.", "success")
            return redirect(url_for("auth.me"))
    from ..core import ai_quota
    from ..core.secret_box import mask
    mine = ai_quota.own_key()
    return render_template("auth/me.html", key=key, my_key=mask(mine) if mine else "", free_left=ai_quota.free_left(),
                           free_limit=current_app.config["AI_FREE_PER_USER"], has_operator=bool(current_app.config.get("OPENAI_API_KEY")))


@bp.route("/open", methods=["POST"])
def open_with_key():
    """기록 열쇠로 내 공간 다시 열기(다른 기기 · 쿠키를 지운 뒤)."""
    user = user_from_key(request.form.get("key"))
    if not user:
        flash("열쇠가 맞지 않아요. 복사한 그대로 붙여 넣었는지 확인해 주세요.", "error")
        return redirect(url_for("auth.me"))
    login_user(user, remember=True)
    flash("내 기록을 다시 열었어요.", "success")
    return redirect(url_for("experiences.index"))


@bp.route("/ai-key", methods=["POST"])
@login_required
def ai_key():
    """내 OpenAI API 키 저장(확인 후 암호화) · 지우기. 키는 내 AI 요청에만 쓰이고 화면·저장본·로그에 나오지 않음."""
    from ..core.secret_box import seal
    from ..integrations import ai_client
    if request.form.get("action") == "delete":
        current_user.openai_key_enc = ""
        db.session.commit()
        flash("내 OpenAI API 키를 지웠어요.", "info")
        return redirect(url_for("auth.me", _anchor="ai"))
    key = (request.form.get("api_key") or "").strip()
    if not key.startswith("sk-") or len(key) < 20 or any(c.isspace() for c in key):
        flash("OpenAI API 키는 'sk-'로 시작해요. platform.openai.com/api-keys 에서 복사한 값을 그대로 넣어 주세요.", "error")
        return redirect(url_for("auth.me", _anchor="ai"))
    try:
        ai_client.check_key(key)
    except ai_client.AiError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.me", _anchor="ai"))
    current_user.openai_key_enc = seal(key)
    db.session.commit()
    flash("내 OpenAI API 키를 저장했어요. 이제 AI 기능을 횟수 제한 없이 쓸 수 있어요(요금은 내 OpenAI 계정에 청구돼요).", "success")
    return redirect(url_for("auth.me", _anchor="ai"))
