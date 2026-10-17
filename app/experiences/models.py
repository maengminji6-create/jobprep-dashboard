import json

from ..core.models_base import TimestampMixin, UserOwnedMixin
from ..extensions import db

CATEGORIES = ["인턴·실무", "프로젝트", "대외활동", "공모전·수상", "동아리·학회", "아르바이트",
              "교육·수료", "자격증·어학", "해외경험", "봉사", "기타"]


class ExperienceUpload(UserOwnedMixin, TimestampMixin, db.Model):
    """업로드한 경험정리 파일. 원본 파일은 저장하지 않고 추출한 텍스트만 보관합니다."""
    __tablename__ = "experience_upload"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    extracted_text = db.Column(db.Text, default="")
    item_count = db.Column(db.Integer, default=0)


class Experience(UserOwnedMixin, TimestampMixin, db.Model):
    __tablename__ = "experience"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(40), default="기타")
    organization = db.Column(db.String(120), default="")
    period = db.Column(db.String(60), default="")
    role = db.Column(db.Text, default="")         # 나의 역할
    content = db.Column(db.Text, default="")      # 상세 내용
    strengths = db.Column(db.Text, default="")    # 강점·성과
    keywords = db.Column(db.Text, default="")     # 키워드(쉼표·# 구분)
    reflection = db.Column(db.Text, default="")   # 느낀점·배운 점
    source = db.Column(db.String(20), default="manual")  # manual | upload
    upload_id = db.Column(db.Integer, db.ForeignKey("experience_upload.id", ondelete="SET NULL"))
    comments = db.relationship("ExperienceComment", cascade="all, delete-orphan")  # SQLite도 함께 삭제되도록 ORM이 지움
    exclusions = db.relationship("TopExclusion", cascade="all, delete-orphan")

    TEXT_FIELDS = ("role", "content", "strengths", "keywords", "reflection")
    TEXT_LABELS = {"role": "나의 역할", "content": "내용", "strengths": "강점·성과", "keywords": "키워드",
                   "reflection": "느낀점"}

    @property
    def full_text(self) -> str:
        """분석에 쓰는 전체 텍스트(제목·기관·모든 항목)."""
        parts = [self.title, self.organization or ""]
        parts += [getattr(self, f) or "" for f in self.TEXT_FIELDS]
        return "\n".join(p for p in parts if p)

    @property
    def content_hash(self) -> str:
        """분석에 쓰는 내용의 지문. AI 코멘트가 최신인지 판단할 때 씁니다."""
        import hashlib
        import re
        # 띄어쓰기·줄바꿈만 달라진 건 '내용 변경'으로 보지 않음(같은 파일을 다시 올려도 코멘트가 그대로 유효)
        text = re.sub(r"\s+", " ", " ".join([self.category or "", self.period or "", self.full_text])).strip()
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def keyword_list(self) -> list[str]:
        import re
        return [k for k in (w.strip(" #·") for w in re.split(r"[,#\n/]", self.keywords or "")) if k]


class PostingAnalysis(UserOwnedMixin, TimestampMixin, db.Model):
    """채용공고 링크(또는 붙여넣은 공고)와 내 경험을 매칭한 결과."""
    __tablename__ = "posting_analysis"
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.Text, default="")
    company = db.Column(db.String(120), default="")
    title = db.Column(db.String(300), default="")
    posting_text = db.Column(db.Text, default="")
    result_json = db.Column(db.Text, default="{}")
    memo = db.Column(db.Text, default="")          # 내가 남기는 메모(마감일·지원 여부 등)
    is_saved = db.Column(db.Boolean, default=False, nullable=False)  # ★ 저장한 공고(아니면 '최근 조회 기록')
    saved_at = db.Column(db.DateTime(timezone=True))
    industry = db.Column(db.String(30), default="etc")   # core/industries.py 코드(자동 분류, 직접 변경 가능)
    role_code = db.Column(db.String(40), default="")     # 직무 분류(기본은 분석이 찾은 직무)
    ai_json = db.Column(db.Text, default="")       # AI 매칭 리포트(선택)
    ai_hash = db.Column(db.String(64), default="") # 리포트 당시 내 이력 지문(바뀌면 '다시 받기' 표시)

    @property
    def ai(self):
        try:
            return json.loads(self.ai_json or "{}") or {}
        except ValueError:
            return {}

    @property
    def result(self):
        try:
            return json.loads(self.result_json or "{}")
        except ValueError:
            return {}


class ExperienceComment(UserOwnedMixin, TimestampMixin, db.Model):
    """경험 × 직무별 자소서 어필 코멘트(AI). 경험 내용이 바뀌면 content_hash 가 달라져 '다시 받기'로 표시."""
    __tablename__ = "experience_comment"
    id = db.Column(db.Integer, primary_key=True)
    experience_id = db.Column(db.Integer, db.ForeignKey("experience.id", ondelete="CASCADE"), nullable=False,
                              index=True)
    role_code = db.Column(db.String(40), nullable=False)
    content_hash = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(60), default="")
    data_json = db.Column(db.Text, default="{}")
    __table_args__ = (db.UniqueConstraint("experience_id", "role_code", name="uq_comment_exp_role"),)

    @property
    def data(self):
        try:
            return json.loads(self.data_json or "{}")
        except ValueError:
            return {}


class Certificate(UserOwnedMixin, TimestampMixin, db.Model):
    """자격증·어학. 경험과 따로 저장하고, 직무 관련도는 core/certificates.py 의 표로 평가합니다."""
    __tablename__ = "certificate"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    score = db.Column(db.String(60), default="")      # 점수·등급(예: 900, IH, 1급 합격)
    acquired = db.Column(db.String(40), default="")   # 취득일(예: 2025.05)
    issuer = db.Column(db.String(120), default="")
    note = db.Column(db.Text, default="")

    @property
    def evaluation(self) -> dict:
        from ..core.certificates import evaluate
        return evaluate(self.name, self.score or "", self.note or "")


class TopExclusion(UserOwnedMixin, TimestampMixin, db.Model):
    """'TOP 3에서 빼기': 이 직무의 추천 순위에서 이 경험을 제외(다음 순위가 올라옴)."""
    __tablename__ = "top_exclusion"
    id = db.Column(db.Integer, primary_key=True)
    experience_id = db.Column(db.Integer, db.ForeignKey("experience.id", ondelete="CASCADE"), nullable=False, index=True)
    role_code = db.Column(db.String(40), nullable=False)
    __table_args__ = (db.UniqueConstraint("experience_id", "role_code", name="uq_exclusion_exp_role"),)


class Snapshot(UserOwnedMixin, TimestampMixin, db.Model):
    """내 이력(경험·자격증)과 강점 결과지를 통째로 저장해 둔 저장본. 나중에 불러오거나 파일로 내려받을 수 있어요."""
    __tablename__ = "snapshot"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    data_json = db.Column(db.Text, nullable=False, default="{}")
    exp_count = db.Column(db.Integer, default=0)
    cert_count = db.Column(db.Integer, default=0)
    has_strength = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def data(self) -> dict:
        try:
            return json.loads(self.data_json or "{}")
        except ValueError:
            return {}
