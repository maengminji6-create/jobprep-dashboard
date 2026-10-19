"""환경별 설정. 코드에는 비밀값을 쓰지 않고 전부 환경변수(.env)에서 읽습니다."""
import os

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
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", 10)) * 1024 * 1024

    # 회원가입 허용(1) / 막기(0). 배포 후 내 계정을 만든 다음 0 으로 바꾸면 다른 사람이 가입할 수 없어요.
    ALLOW_SIGNUP = os.environ.get("ALLOW_SIGNUP", "1") == "1"

    # AI 코멘트(선택, OpenAI). 키가 없으면 규칙 기반 기본 코멘트만 보여 줍니다.
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    AI_MODEL = os.environ.get("AI_MODEL") or "gpt-5.4-mini"

    # 비밀번호 재설정 메일(선택). MAIL_SERVER 가 비면 메일을 보내지 않아요(개발 모드에서는 링크를 터미널에 표시).
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 587)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "")
    # 메일 속 링크의 사이트 주소(예: https://growly.onrender.com). 요청 Host 헤더를 믿지 않기 위해 배포에서는 꼭 설정
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")
    PASSWORD_RESET_MAX_AGE = 30 * 60  # 재설정 링크 유효 시간(초)


class DevConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _db_url("sqlite:///" + os.path.join(INSTANCE_DIR, "dev.db"))


class TestConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    OPENAI_API_KEY = ""  # 테스트에서는 실제 API를 부르지 않음
    MAIL_SERVER = ""  # 테스트에서는 실제 메일을 보내지 않음
    APP_BASE_URL = "https://growly.test"


class ProdConfig(BaseConfig):
    SQLALCHEMY_DATABASE_URI = _db_url("")
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True


CONFIGS = {"dev": DevConfig, "test": TestConfig, "prod": ProdConfig}
