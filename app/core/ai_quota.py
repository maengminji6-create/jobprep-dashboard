"""AI 호출에 쓸 키 고르기 · 무료 횟수 차감.

- 사용자가 내 공간에 자기 OpenAI 키를 넣었으면 → 그 키(횟수 제한 없음, 요금은 사용자 계정)
- 아니면 운영자 키(OPENAI_API_KEY) → 개인 공간마다 AI_FREE_PER_USER회 + 하루 전체 AI_FREE_DAILY_CAP회까지 무료
  (AI_FREE_PER_USER=0 이면 제한 없음 — 로컬에서 내 키로 쓸 때)
이미지·스캔 PDF 읽기처럼 비싼 호출은 AI_VISION_COST회로 셉니다.
"""
from datetime import date

from flask import current_app, has_request_context
from flask_login import current_user

from ..extensions import db
from .secret_box import open_


class QuotaError(Exception):
    """사용자에게 그대로 보여 줄 안내 문구."""


def _user():
    if not has_request_context() or not current_user.is_authenticated:
        return None
    return current_user._get_current_object()


def own_key() -> str:
    u = _user()
    return open_(u.openai_key_enc) if u is not None else ""


def free_left() -> int | None:
    """남은 무료 횟수. 제한이 없으면 None."""
    limit = current_app.config["AI_FREE_PER_USER"]
    if not limit:
        return None
    u = _user()
    return max(0, limit - (u.ai_free_used or 0)) if u is not None else limit


def _today_used() -> int:
    from ..auth.models import AiDailyUsage
    row = db.session.get(AiDailyUsage, date.today())
    return row.count if row else 0


def pick_key(cost: int = 1) -> tuple[str, bool]:
    """(이번 호출에 쓸 키, 운영자 무료 키인지). 쓸 수 있는 키가 없으면 QuotaError."""
    mine = own_key()
    if mine:
        return mine, False
    operator = current_app.config.get("OPENAI_API_KEY") or ""
    if not operator:
        raise QuotaError(unavailable_message())
    left = free_left()
    if left is None:
        return operator, False  # 제한 없음(로컬)
    cap = current_app.config["AI_FREE_DAILY_CAP"]
    if left < cost or (cap and _today_used() + cost > cap):
        raise QuotaError(unavailable_message(cost))
    return operator, True


def charge(cost: int = 1) -> None:
    """운영자 키로 무료 호출에 성공했을 때 횟수 차감(바로 저장)."""
    from ..auth.models import AiDailyUsage
    u = _user()
    if u is not None:
        u.ai_free_used = (u.ai_free_used or 0) + cost
    row = db.session.get(AiDailyUsage, date.today())
    if row is None:
        row = AiDailyUsage(day=date.today(), count=0)
        db.session.add(row)
    row.count += cost
    db.session.commit()


def available(cost: int = 1) -> bool:
    try:
        pick_key(cost)
        return True
    except QuotaError:
        return False


def unavailable_message(cost: int = 1) -> str:
    """AI를 쓸 수 없을 때 상황에 맞는 안내."""
    operator = current_app.config.get("OPENAI_API_KEY") or ""
    limit = current_app.config["AI_FREE_PER_USER"]
    if not operator:
        if current_app.config.get("DEBUG") or current_app.config.get("TESTING"):
            return ".env 에 OPENAI_API_KEY 를 넣고 서버를 다시 켜 주세요. (내 공간에서 내 OpenAI 키를 넣어도 돼요)"
        return "AI 기능을 쓰려면 내 공간(오른쪽 위 이름)에서 내 OpenAI API 키를 넣어 주세요."
    left = free_left()
    if left is not None and left < cost:
        need = f"(이 기능은 무료 {cost}회가 필요해요) " if cost > 1 and left else ""
        return (f"무료 AI {limit}회 중 남은 횟수가 부족해요. {need}내 공간(오른쪽 위 이름)에서 내 OpenAI API 키를 넣으면 "
                "계속 쓸 수 있어요.")
    return "오늘 무료 AI 사용량이 다 찼어요. 내일 다시 쓰거나, 내 공간에서 내 OpenAI API 키를 넣으면 바로 쓸 수 있어요."
