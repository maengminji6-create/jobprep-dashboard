"""experience types 7

경험 유형을 7개로 정리하며 저장된 분류 값을 바꿉니다(스키마 변경 없음, 데이터만).
해외경험·봉사 → 기타, 동아리·학회 → 대외활동, 교육·수료·자격증·어학 → 교육·자격증, 인턴·실무 → 인턴·직장 경험.

Revision ID: 19715ec04ef9
Revises: 8368a5afb2e8
Create Date: 2026-11-05 17:08:08.309451

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '19715ec04ef9'
down_revision = '8368a5afb2e8'
branch_labels = None
depends_on = None

UPGRADE = {"인턴·실무": "인턴·직장 경험", "동아리·학회": "대외활동", "교육·수료": "교육·자격증",
           "자격증·어학": "교육·자격증", "해외경험": "기타", "봉사": "기타"}
# 되돌릴 때는 1:1로 대응하는 이름만 되돌림(기타·대외활동으로 합쳐진 것은 어디서 왔는지 알 수 없음)
DOWNGRADE = {"인턴·직장 경험": "인턴·실무", "교육·자격증": "교육·수료"}

experience = sa.table("experience", sa.column("category", sa.String))


def _rename(mapping):
    for old, new in mapping.items():
        op.execute(experience.update().where(experience.c.category == old).values(category=new))


def upgrade():
    _rename(UPGRADE)


def downgrade():
    _rename(DOWNGRADE)
