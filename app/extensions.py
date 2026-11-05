"""확장 객체를 한 곳에서 만들어 모든 모듈이 공유합니다(순환 import 방지)."""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
# 로그인 화면은 없음: auth/routes.py 가 요청마다 주인 계정으로 자동 로그인
