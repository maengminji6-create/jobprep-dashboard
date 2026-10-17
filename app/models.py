"""모든 기능의 모델을 한 번에 import 해 Flask-Migrate가 테이블을 인식하게 합니다."""
from .applications.models import ApplicationRecord  # noqa: F401
from .auth.models import User  # noqa: F401
from .experiences.models import (Certificate, Experience, ExperienceComment, ExperienceUpload,  # noqa: F401
                                 PostingAnalysis, Snapshot, TopExclusion)
from .strengths.models import StrengthProfile  # noqa: F401
