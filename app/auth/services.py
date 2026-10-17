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
