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

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_active(self):
        return self.is_active_flag


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
