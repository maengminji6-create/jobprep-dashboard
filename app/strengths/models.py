import json

from ..core.models_base import TimestampMixin, UserOwnedMixin
from ..extensions import db


class StrengthProfile(UserOwnedMixin, TimestampMixin, db.Model):
    """업로드한 강점 진단 결과. 여러 개를 저장해 두고 그중 하나를 불러와(활성) 씁니다. 원본 파일은 저장하지 않고 추출한 텍스트만 보관합니다."""
    __tablename__ = "strength_profile"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), default="")
    extracted_text = db.Column(db.Text, default="")
    parsed_json = db.Column(db.Text, default="{}")   # 규칙으로 뽑은 강점 목록·영역·역할
    ai_json = db.Column(db.Text, default="")         # AI 강점-경험 연결 결과(선택)
    ai_role = db.Column(db.String(40), default="")   # AI 분석 기준 직무
    ai_hash = db.Column(db.String(64), default="")   # 분석 당시 경험 내용 지문(바뀌면 '다시 분석' 표시)
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # 지금 화면에 쓰는 결과지(나머지는 저장본)

    @staticmethod
    def _load(text):
        try:
            return json.loads(text or "{}") or {}
        except ValueError:
            return {}

    @property
    def parsed(self) -> dict:
        return self._load(self.parsed_json)

    @property
    def strengths(self) -> list[dict]:
        return self.parsed.get("strengths", [])

    @property
    def ai(self) -> dict:
        return self._load(self.ai_json)
