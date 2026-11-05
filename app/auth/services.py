"""로그인 없이 쓰는 개인 공간.

- 배포: 처음 들어온 브라우저마다 개인 계정을 하나 만들고 오래 가는 쿠키로 기억해요. 남의 기록은 볼 수 없어요.
- 쿠키가 지워지거나 다른 기기에서 열 때는 '기록 열쇠'(계정번호-비밀문자열)로 내 공간을 다시 엽니다.
  열쇠의 비밀 부분은 비밀번호처럼 해시로만 저장해서, 만들 때 한 번만 보여 줄 수 있어요.
- 로컬 개발: .env 의 OWNER_EMAIL 이 있으면 그 계정으로 바로 들어가요(DevConfig 에서만 읽음).
"""
import secrets

from flask import current_app

from ..extensions import db
from .models import User

GUEST_NAME = "취준생"


def _new_user(email: str, name: str) -> User:
    user = User(email=email, name=name)
    user.set_password(secrets.token_urlsafe(16))  # 열쇠를 만들기 전까지는 아무도 모르는 값
    db.session.add(user)
    db.session.commit()
    return user


def get_or_create_visitor() -> User:
    """쿠키로 기억된 사람이 없을 때: 로컬 주인 계정 또는 새 개인 공간."""
    owner = current_app.config.get("OWNER_EMAIL")
    if owner:
        return db.session.query(User).filter_by(email=owner).first() or _new_user(owner, GUEST_NAME)
    return _new_user(f"guest-{secrets.token_hex(8)}@growly.local", GUEST_NAME)


def make_access_key(user: User) -> str:
    """새 기록 열쇠를 만들고(이전 열쇠는 무효) 화면에 한 번 보여 줄 문자열을 돌려줍니다."""
    secret = secrets.token_urlsafe(12)
    user.set_password(secret)
    db.session.commit()
    return f"{user.id}-{secret}"


def user_from_key(key: str) -> User | None:
    uid, _, secret = (key or "").strip().partition("-")
    if not uid.isdigit() or not secret:
        return None
    user = db.session.get(User, int(uid))
    if not user or not user.is_active or not user.check_password(secret):
        return None
    return user
