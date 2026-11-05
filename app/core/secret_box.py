"""사용자가 넣은 API 키 같은 비밀값을 DB에 암호화해서 저장(Fernet).

암호화 키는 ENCRYPTION_KEY(없으면 SECRET_KEY에서 만듦). 키가 바뀌어 풀 수 없으면 빈 값으로 보고 다시 넣게 함.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet() -> Fernet:
    raw = current_app.config.get("ENCRYPTION_KEY") or current_app.config["SECRET_KEY"]
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest()))


def seal(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii") if value else ""


def open_(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask(key: str) -> str:
    """화면 표시용: 앞 3자·끝 4자만."""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else "…"
