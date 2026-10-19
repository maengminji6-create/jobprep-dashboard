import re

from ..extensions import db
from .models import User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register_user(email: str, name: str, password: str) -> tuple[User | None, str | None]:
    email = (email or "").strip().lower()
    name = (name or "").strip()
    if not EMAIL_RE.match(email):
        return None, "이메일 형식을 확인해 주세요."
    if not name:
        return None, "이름을 입력해 주세요."
    if len(password or "") < 8:
        return None, "비밀번호는 8자 이상이어야 합니다."
    if db.session.query(User).filter_by(email=email).first():
        return None, "이미 가입된 이메일입니다."
    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user, None


def authenticate(email: str, password: str) -> User | None:
    user = db.session.query(User).filter_by(email=(email or "").strip().lower()).first()
    if user and user.check_password(password or ""):
        return user
    return None


# ── 비밀번호 재설정 ────────────────────────────────────────────
# 링크 = 서명된 토큰(SECRET_KEY). DB 테이블 없이도 안전하게:
#  - 만료: PASSWORD_RESET_MAX_AGE(30분)
#  - 1회용: 토큰에 '현재 비밀번호 해시의 지문'을 넣어, 비밀번호가 바뀌면 이전 링크는 모두 무효
RESET_SALT = "growly-password-reset"


def _serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=RESET_SALT)


def _fingerprint(user: User) -> str:
    import hashlib
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:20]


def make_reset_token(user: User) -> str:
    return _serializer().dumps({"uid": user.id, "fp": _fingerprint(user)})


def verify_reset_token(token: str) -> User | None:
    from flask import current_app
    from itsdangerous import BadSignature
    try:
        data = _serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE"])
    except BadSignature:  # 위조·만료(SignatureExpired 포함)
        return None
    user = db.session.get(User, data.get("uid")) if isinstance(data, dict) else None
    if not user or not user.is_active or data.get("fp") != _fingerprint(user):
        return None
    return user


def find_user_by_email(email: str) -> User | None:
    return db.session.query(User).filter_by(email=(email or "").strip().lower()).first()
