import json

from ..core.models_base import TimestampMixin, UserOwnedMixin
from ..extensions import db

EVIDENCE_LEVELS = ["충분", "보통", "약함"]
LINK_ORIGINS = {"ai": "AI 연결", "rule": "단어 단서", "user": "직접 연결"}


class ExperienceAnalysis(UserOwnedMixin, TimestampMixin, db.Model):
    """경험 1개의 AI 분석(B. 경험 기반 역량). 모든 항목은 경험 원문 인용(quote)이 확인된 것만 저장합니다.
    content_hash 가 경험의 지금 지문과 다르면 '내용이 바뀌어 다시 분석 필요'."""
    __tablename__ = "experience_analysis"
    id = db.Column(db.Integer, primary_key=True)
    experience_id = db.Column(db.Integer, db.ForeignKey("experience.id", ondelete="CASCADE"), nullable=False,
                              unique=True, index=True)
    content_hash = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(60), default="")
    data_json = db.Column(db.Text, nullable=False, default="{}")
    # {"summary", "actions": [{text, quote, field}], "problem_solving": {text, quote, field} | None,
    #  "results": [...], "competencies": [{name, quotes: [{quote, field, reason}], level}], "needs_info": [str],
    #  "dropped": 원문에서 근거를 찾지 못해 뺀 항목 수}

    @property
    def data(self) -> dict:
        try:
            return json.loads(self.data_json or "{}") or {}
        except ValueError:
            return {}


class StrengthLink(UserOwnedMixin, TimestampMixin, db.Model):
    """C. 진단 강점 × 경험 연결 한 건. AI·규칙이 만든 연결도 사용자가 고치거나(edited) 해제(removed)할 수 있고,
    고친·해제한 연결은 다시 자동 연결해도 덮어쓰지 않습니다."""
    __tablename__ = "strength_link"
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("strength_profile.id", ondelete="CASCADE"), nullable=False,
                           index=True)
    strength_name = db.Column(db.String(40), nullable=False)
    experience_id = db.Column(db.Integer, db.ForeignKey("experience.id", ondelete="CASCADE"), nullable=False,
                              index=True)
    quote = db.Column(db.Text, default="")        # 근거 행동: 경험 원문 그대로
    reason = db.Column(db.Text, default="")       # 연결한 이유
    evidence = db.Column(db.String(10), default="보통")  # 충분 | 보통 | 약함
    origin = db.Column(db.String(10), default="ai")      # ai | rule | user
    edited = db.Column(db.Boolean, default=False, nullable=False)
    removed = db.Column(db.Boolean, default=False, nullable=False)
    content_hash = db.Column(db.String(64), default="")  # 연결 당시 경험 지문
    __table_args__ = (db.UniqueConstraint("profile_id", "strength_name", "experience_id", name="uq_link_strength_exp"),)


class StrengthManual(UserOwnedMixin, TimestampMixin, db.Model):
    """나의 강점 사용 설명서 저장본: 저장 당시 진단 강점·경험 분석·연결을 엮은 결과를 통째로(JSON) 보관.
    원본 데이터가 바뀌어도 저장본은 그대로라 언제든 다시 열어 볼 수 있습니다."""
    __tablename__ = "strength_manual"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    job_code = db.Column(db.String(40), default="")
    data_json = db.Column(db.Text, nullable=False, default="{}")

    @property
    def data(self) -> dict:
        try:
            return json.loads(self.data_json or "{}") or {}
        except ValueError:
            return {}
