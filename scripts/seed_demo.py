"""로그인용 데모 계정만 만듭니다. 실행: flask seed-demo

데모 계정: demo@tradeready.local / demo1234
가상의 경험 데이터는 넣지 않습니다. 경험정리는 직접 올린 파일이나 입력한 내용으로 분석됩니다.
"""
from app.auth.models import User
from app.extensions import db

DEMO_EMAIL = "demo@tradeready.local"


def seed() -> str:
    user = db.session.query(User).filter_by(email=DEMO_EMAIL).first()
    if not user:
        user = User(email=DEMO_EMAIL, name="데모 취준생")
        user.set_password("demo1234")
        db.session.add(user)
    db.session.commit()
    return f"데모 계정 준비 완료 — 로그인: {DEMO_EMAIL} / demo1234 (내 이름으로 쓰려면 회원가입을 이용하세요)"
