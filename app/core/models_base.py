"""모든 모델이 함께 쓰는 믹스인."""
from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class UserOwnedMixin:
    """사용자 개인 데이터 테이블에 반드시 붙입니다. user_id 로 데이터를 분리합니다."""

    @db.declared_attr
    def user_id(cls):
        return db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                         nullable=False, index=True)
