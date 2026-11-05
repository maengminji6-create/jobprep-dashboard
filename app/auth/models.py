from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.models_base import TimestampMixin
from ..extensions import db, login_manager


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active_flag = db.Column(db.Boolean, default=True, nullable=False)
    openai_key_enc = db.Column(db.Text, default="")    # 내가 넣은 OpenAI 키(암호화, core/secret_box) — 원래 값은 저장하지 않음
    ai_free_used = db.Column(db.Integer, default=0, nullable=False)  # 운영자 키로 쓴 무료 AI 횟수

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_active(self):
        return self.is_active_flag


class AiDailyUsage(db.Model):
    """하루 전체 무료 AI 사용량(운영자 키). 쿠키를 지워 새 공간을 만들어도 이 상한은 넘지 못함."""
    __tablename__ = "ai_daily_usage"
    day = db.Column(db.Date, primary_key=True)
    count = db.Column(db.Integer, default=0, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
