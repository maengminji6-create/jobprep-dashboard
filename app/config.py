"""환경별 설정. 코드에는 비밀값을 쓰지 않고 전부 환경변수(.env)에서 읽습니다."""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _db_url(default: str) -> str:
    url = os.environ.get("DATABASE_URL") or default
    # 일부 배포 플랫폼이 주는 옛 형식(postgres://) 보정
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    # Vercel 함수는 요청 본문이 4.5MB를 넘으면 앱에 닿기 전에 끊으므로 Vercel에서는 기본 4MB
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB") or (4 if os.environ.get("VERCEL") else 10)) * 1024 * 1024

    # 로그인 없이 브라우저마다 개인 공간: 이 쿠키로 기억(접속할 때마다 기한 연장, 브라우저 최대치 400일)
    REMEMBER_COOKIE_DURATION = timedelta(days=400)
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    OWNER_EMAIL = ""  # 배포에서는 절대 쓰지 않음(쓰면 모든 방문자가 그 계정으로 들어감)

    # AI 코멘트(선택, OpenAI). 키가 없으면 규칙 기반 기본 코멘트만 보여 줍니다.
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    AI_MODEL = os.environ.get("AI_MODEL") or "gpt-5.4-mini"
    # 운영자 키(OPENAI_API_KEY)로 개인 공간마다 무료 N회 → 그 뒤엔 사용자가 내 공간에 넣은 자기 키. 0 = 제한 없음
    AI_FREE_PER_USER = int(os.environ.get("AI_FREE_PER_USER") or 5)
    AI_FREE_DAILY_CAP = int(os.environ.get("AI_FREE_DAILY_CAP") or 50)  # 하루 전체 무료 상한(쿠키를 지워 새 공간을 만드는 남용 방지)
    AI_VISION_COST = int(os.environ.get("AI_VISION_COST") or 3)         # 이미지·스캔 PDF 읽기 1번 = 무료 3회
    # 사용자 키 암호화 키. 비우면 SECRET_KEY에서 만듦(그래서 SECRET_KEY를 바꾸면 저장된 사용자 키는 다시 넣어야 함)
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")


class DevConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _db_url("sqlite:///" + os.path.join(INSTANCE_DIR, "dev.db"))
    # 로컬 전용: 이 이메일 계정으로 바로 들어감. 비우면 브라우저마다 개인 공간(배포와 같음)
    OWNER_EMAIL = (os.environ.get("OWNER_EMAIL") or "").strip().lower()
    AI_FREE_PER_USER = int(os.environ.get("AI_FREE_PER_USER") or 0)  # 로컬은 내 키로 제한 없이


class TestConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    OPENAI_API_KEY = ""  # 테스트에서는 실제 API를 부르지 않음
    AI_FREE_PER_USER = 0  # 횟수 제한은 테스트에서 따로 켬


class ProdConfig(BaseConfig):
    SQLALCHEMY_DATABASE_URI = _db_url("")
    if os.environ.get("VERCEL"):  # 서버리스: 쉬는 동안 끊길 수 있는 연결을 붙잡아 두지 않고 요청마다 새로 맺음
        from sqlalchemy.pool import NullPool
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "poolclass": NullPool}
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True


CONFIGS = {"dev": DevConfig, "test": TestConfig, "prod": ProdConfig}
