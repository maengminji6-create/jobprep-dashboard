import json

from ..core.models_base import TimestampMixin, UserOwnedMixin
from ..extensions import db

CATEGORIES = ["직무 역량", "경험", "문제 해결", "지원 동기", "기타"]


class InterviewSession(UserOwnedMixin, TimestampMixin, db.Model):
    """면접 준비 한 건: 지원 기업·공고에 맞춘 예상 질문과 면접 뒤 복기."""
    __tablename__ = "interview_session"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(120), default="")
    role_code = db.Column(db.String(40), default="")
    posting_id = db.Column(db.Integer, db.ForeignKey("posting_analysis.id", ondelete="SET NULL"))
    application_id = db.Column(db.Integer, db.ForeignKey("application_record.id", ondelete="SET NULL"))
    interview_date = db.Column(db.Date)
    review = db.Column(db.Text, default="")  # 면접 복기: 실제 받은 질문·잘한 점·아쉬운 점
    questions = db.relationship("InterviewQuestion", cascade="all, delete-orphan",
                                order_by="InterviewQuestion.id")


class InterviewQuestion(UserOwnedMixin, TimestampMixin, db.Model):
    __tablename__ = "interview_question"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("interview_session.id", ondelete="CASCADE"), nullable=False, index=True)
    category = db.Column(db.String(20), default="기타")
    question = db.Column(db.Text, nullable=False)
    basis = db.Column(db.Text, default="")         # 질문의 근거(공고 문장·경험 이름) — 지어낸 질문이 아님을 보여 줌
    source = db.Column(db.String(10), default="rule")  # rule | ai | manual
    exp_ids = db.Column(db.String(200), default="")    # 추천·사용 경험 id(쉼표)
    answer = db.Column(db.Text, default="")
    asked = db.Column(db.Boolean, default=False, nullable=False)  # 실제 면접에서 받은 질문인지(복기)
    self_note = db.Column(db.Text, default="")     # 복기 메모
    feedback_json = db.Column(db.Text, default="")  # 답변 점검 결과(규칙 + 선택 AI)

    @property
    def exp_id_list(self) -> list[int]:
        return [int(x) for x in (self.exp_ids or "").split(",") if x.strip().isdigit()]

    @property
    def feedback(self) -> dict:
        try:
            return json.loads(self.feedback_json or "{}") or {}
        except ValueError:
            return {}
