import json

from ..core.models_base import TimestampMixin, UserOwnedMixin
from ..extensions import db

STATUSES = ["작성 중", "제출 완료", "서류 합격", "면접 진행", "최종 합격", "불합격"]


class ApplicationRecord(UserOwnedMixin, TimestampMixin, db.Model):
    """자소서 보관함: 내가 낸(또는 쓰는 중인) 자기소개서와 그 기업 정보를 한곳에 저장."""
    __tablename__ = "application_record"
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(120), nullable=False)
    position = db.Column(db.String(200), default="")
    role_code = db.Column(db.String(40), default="")
    status = db.Column(db.String(20), default="작성 중")
    applied_at = db.Column(db.String(40), default="")   # 제출일(예: 2026.10.17)
    deadline = db.Column(db.String(40), default="")
    url = db.Column(db.Text, default="")
    posting_id = db.Column(db.Integer, db.ForeignKey("posting_analysis.id", ondelete="SET NULL"))
    company_info = db.Column(db.Text, default="")       # 사업·제품·최근 이슈·규모
    talent = db.Column(db.Text, default="")             # 인재상·핵심가치
    notes = db.Column(db.Text, default="")              # 면접 정보·연봉·느낀 점 등
    qa_json = db.Column(db.Text, default="[]")          # [{"q": 문항, "limit": 글자 수 제한, "a": 답변}]

    @property
    def qa(self) -> list[dict]:
        try:
            items = json.loads(self.qa_json or "[]")
        except ValueError:
            return []
        return [i for i in items if isinstance(i, dict)]

    @property
    def total_chars(self) -> int:
        return sum(len((i.get("a") or "").replace("\n", "")) for i in self.qa)
