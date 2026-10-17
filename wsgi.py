"""배포 서버(gunicorn)와 `flask` 명령이 읽는 진입점."""
from app import create_app

app = create_app()
