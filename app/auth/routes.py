from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import bp
from .services import authenticate, find_user_by_email, make_reset_token, register_user, verify_reset_token


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


# 같은 이메일·같은 IP로 재설정 메일을 연달아 보내지 못하게(서버 프로세스 메모리 기준의 간단한 제한)
_RESET_EMAIL_COOLDOWN = 60          # 같은 이메일: 60초에 1번
_RESET_IP_LIMIT, _RESET_IP_WINDOW = 5, 600  # 같은 IP: 10분에 5번
_reset_email_at: dict[str, float] = {}
_reset_ip_hits: dict[str, list[float]] = {}


def _reset_allowed(email: str, ip: str) -> bool:
    import time
    now = time.time()
    hits = [t for t in _reset_ip_hits.get(ip, []) if now - t < _RESET_IP_WINDOW]
    if len(hits) >= _RESET_IP_LIMIT or now - _reset_email_at.get(email, 0) < _RESET_EMAIL_COOLDOWN:
        _reset_ip_hits[ip] = hits
        return False
    _reset_ip_hits[ip] = hits + [now]
    _reset_email_at[email] = now
    return True


def _reset_link(token: str) -> str | None:
    """메일 속 링크. 배포에서는 APP_BASE_URL 만 사용(요청 Host 헤더를 믿으면 남의 사이트 주소로 링크가 바뀔 수 있음)."""
    base = current_app.config.get("APP_BASE_URL")
    if base:
        return base + url_for("auth.reset_password", token=token)
    if current_app.debug:  # 로컬 개발: 지금 접속한 주소 사용
        return url_for("auth.reset_password", token=token, _external=True)
    current_app.logger.error("APP_BASE_URL 이 없어 비밀번호 재설정 링크를 만들지 않았어요.")
    return None


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("experiences.index"))
    if request.method == "POST":
        from ..integrations import mailer
        email = (request.form.get("email") or "").strip().lower()
        user = find_user_by_email(email)
        if email and _reset_allowed(email, request.remote_addr or "?") and user and user.is_active:
            link = _reset_link(make_reset_token(user))
            if link:
                mailer.send_mail(user.email, "[GROWLY] 비밀번호 재설정 링크",
                                 f"{user.name}님, 비밀번호를 다시 정하려면 아래 링크를 여세요(30분 동안 1번만 쓸 수 있어요).\n\n"
                                 f"{link}\n\n직접 요청하지 않았다면 이 메일은 무시하세요. 비밀번호는 바뀌지 않아요.")
        # 가입 여부를 알려 주지 않도록 항상 같은 안내
        flash("가입된 이메일이라면 비밀번호 재설정 링크를 보냈어요. 메일함(스팸함 포함)을 확인해 주세요. "
              "링크는 30분 동안 유효해요.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = verify_reset_token(token)
    if not user:
        flash("링크가 만료됐거나 이미 사용했어요. 비밀번호 찾기를 다시 해 주세요.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password") or "", request.form.get("password2") or ""
        if len(pw) < 8:
            flash("비밀번호는 8자 이상이어야 합니다.", "error")
        elif pw != pw2:
            flash("두 비밀번호가 서로 달라요.", "error")
        else:
            from ..extensions import db
            user.set_password(pw)
            db.session.commit()
            logout_user()
            flash("비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token)
