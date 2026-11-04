from flask import flash, redirect, render_template, request, url_for
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
    return render_template("auth/me.html", key=key)


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
