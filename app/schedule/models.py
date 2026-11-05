import json

from ..core.models_base import TimestampMixin, UserOwnedMixin
from ..extensions import db

KINDS = ["면접", "서류 제출", "자격증 시험", "개인 일정", "기타"]
# 공고 마감 일정에서 '준비 체크리스트 만들기'를 누르면 들어가는 기본 항목
DEFAULT_CHECKLIST = ["자기소개서 작성", "이력서 최신화", "증빙 서류(성적·어학·자격증) 준비", "제출 후 접수 확인"]


class ScheduleEvent(UserOwnedMixin, TimestampMixin, db.Model):
    """내가 직접 추가한 취업 일정(면접·서류 제출·시험·개인 일정). 공고 마감일은 공고에서 자동으로 보여 줌."""
    __tablename__ = "schedule_event"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(20), default="개인 일정")
    date = db.Column(db.Date, nullable=False, index=True)
    time = db.Column(db.String(10), default="")   # 예: 14:00
    posting_id = db.Column(db.Integer, db.ForeignKey("posting_analysis.id", ondelete="SET NULL"))
    memo = db.Column(db.Text, default="")
    checklist_json = db.Column(db.Text, default="[]")  # [{"text": 할 일, "done": 끝냈는지}]
    done = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def checklist(self) -> list[dict]:
        try:
            items = json.loads(self.checklist_json or "[]")
        except ValueError:
            return []
        return [i for i in items if isinstance(i, dict) and i.get("text")]
