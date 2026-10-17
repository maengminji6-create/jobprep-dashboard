from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import bp
from .services import authenticate, register_user


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("experiences.index"))
    if not current_app.config["ALLOW_SIGNUP"]:
        flash("지금은 새 회원가입을 받지 않아요.", "info")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        user, error = register_user(request.form.get("email"), request.form.get("name"),
                                    request.form.get("password"))
        if error:
            flash(error, "error")
        else:
            login_user(user)
            flash(f"{user.name}님, 환영합니다! 경험정리 파일을 올리거나 경험을 직접 추가해 보세요.", "success")
            return redirect(url_for("experiences.index"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("experiences.index"))
    if request.method == "POST":
        user = authenticate(request.form.get("email"), request.form.get("password"))
        if user:
            login_user(user, remember=bool(request.form.get("remember")))
            nxt = request.args.get("next")
            if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("experiences.index")
            return redirect(nxt)
        flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
