"""Vercel 빌드 단계(vercel.json 의 buildCommand).

1) app/static → public/static 복사: Vercel CDN이 /static/... 을 바로 내려 줌(주소는 url_for('static') 그대로)
   (CDN이 못 내려 줘도 함수 묶음에 app/static 이 남아 있어 Flask 가 대신 내려 줌)
2) 운영 배포(VERCEL_ENV=production)일 때만 DB 마이그레이션(flask db upgrade).
   미리보기 배포는 운영 DB를 바꾸지 않도록 건너뜀. 마이그레이션이 실패하면 빌드를 멈춰 깨진 앱이 배포되지 않게 함.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def copy_static() -> None:
    src, dst = ROOT / "app" / "static", ROOT / "public" / "static"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"정적 파일 복사: {src} → {dst}")


def migrate() -> None:
    if os.environ.get("VERCEL_ENV") != "production":
        print("미리보기 배포라 DB 마이그레이션은 건너뜀")
        return
    if not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL 이 없어요. Vercel 프로젝트에 Postgres(Neon)를 연결하거나 환경변수를 넣어 주세요.")
    env = {**os.environ, "FLASK_APP": "wsgi.py", "APP_ENV": "prod"}
    print("DB 마이그레이션: flask db upgrade")
    subprocess.run([sys.executable, "-m", "flask", "db", "upgrade"], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    copy_static()
    migrate()
