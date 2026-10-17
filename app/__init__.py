"""앱 팩토리: 설정 → 확장 → 블루프린트 → 에러 핸들러 → CLI 순서로 조립합니다."""
import os

from dotenv import load_dotenv

load_dotenv()  # 설정을 읽기 전에 .env 를 먼저 불러와야 합니다

from flask import Flask, redirect, url_for  # noqa: E402

from .config import CONFIGS, INSTANCE_DIR  # noqa: E402
from .extensions import csrf, db, login_manager, migrate  # noqa: E402

NAV_ITEMS = [
    # (endpoint, 메뉴명, 아이콘 글자, 활성 표시 키)
    ("experiences.index", "경험 분석", "✎", "experiences"),
    ("strengths.index", "강점 연결", "✦", "strengths"),
    ("experiences.posting", "공고 매칭", "◎", "posting"),
    ("applications.index", "자소서 보관함", "▤", "applications"),
]


def _nav_key(endpoint: str) -> str:
    if endpoint.startswith("experiences.posting"):
        return "posting"
    if endpoint.startswith("strengths."):
        return "strengths"
    if endpoint.startswith("applications."):
        return "applications"
    return "experiences"


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.environ.get("APP_ENV", "dev")
    app = Flask(__name__, instance_path=INSTANCE_DIR)
    app.config.from_object(CONFIGS[config_name])

    if config_name == "prod" and not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError("배포 환경에는 DATABASE_URL 환경변수가 필요합니다.")

    os.makedirs(INSTANCE_DIR, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # SQLite에서도 ALTER 가능하게
    login_manager.init_app(app)
    csrf.init_app(app)

    # 모델 등록(마이그레이션이 모든 테이블을 인식하도록)
    from . import models  # noqa: F401

    from .auth import bp as auth_bp
    from .experiences import bp as experiences_bp
    from .applications import bp as applications_bp
    from .strengths import bp as strengths_bp

    for bp in (auth_bp, experiences_bp, strengths_bp, applications_bp):
        app.register_blueprint(bp)

    @app.route("/")
    def root():
        return redirect(url_for("experiences.index"))

    from .core.errors import register_error_handlers
    register_error_handlers(app)

    from .cli import register_cli
    register_cli(app)

    if config_name == "dev":
        from .core.devreload import register_dev_reload
        register_dev_reload(app)

    @app.template_filter("localtime")
    def localtime(dt, fmt="%Y.%m.%d %H:%M"):
        """DB 시각(UTC)을 이 컴퓨터 시간대로. SQLite는 시간대 정보를 버리므로 없으면 UTC로 봅니다."""
        from datetime import timezone
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime(fmt)

    @app.template_filter("highlight")
    def highlight(text, exp_words=None, str_words=None):
        """형광펜: 내 경험과 겹치는 단어는 노랑(hl-exp), 내 강점 단서는 초록(hl-str), 둘 다면 hl-both.
        먼저 HTML 이스케이프하므로 공고·경험 글에 태그가 있어도 안전합니다."""
        import re

        from markupsafe import Markup, escape
        safe = str(escape(text or ""))
        exp = {str(escape(w)).lower() for w in (exp_words or []) if w and len(w) >= 2}
        stg = {str(escape(w)).lower() for w in (str_words or []) if w and len(w) >= 2}
        if not exp and not stg:
            return Markup(safe)
        pattern = re.compile("|".join(re.escape(w) for w in sorted(exp | stg, key=len, reverse=True)), re.IGNORECASE)

        def mark(m):
            w = m.group(0).lower()
            cls = "hl-both" if w in exp and w in stg else ("hl-exp" if w in exp else "hl-str")
            title = {"hl-exp": "내 경험과 겹치는 단어", "hl-str": "내 강점 단서", "hl-both": "경험·강점 모두"}[cls]
            return f'<mark class="{cls}" title="{title}">{m.group(0)}</mark>'
        return Markup(pattern.sub(mark, safe))

    @app.context_processor
    def inject_nav():
        from flask import request
        return {"NAV_ITEMS": NAV_ITEMS, "nav_active": _nav_key(request.endpoint or "")}

    return app
