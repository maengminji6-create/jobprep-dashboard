"""개발용 자동 새로고침. VS Code에서 파일을 저장하면 열려 있는 브라우저 화면이 저절로 새로고침됩니다.

- 템플릿·CSS·JS 저장 → 바뀐 시각이 달라져 페이지가 새로고침
- .py 저장 → `flask run --debug` 가 서버를 재시작하고, 재시작 시각이 달라져 페이지가 새로고침
개발 환경(APP_ENV=dev)에서만 켜지고 배포(prod)·테스트에서는 등록되지 않습니다.
"""
import os
import time

from flask import jsonify

STARTED_AT = time.time()
WATCH_EXT = (".html", ".css", ".js")


def _latest_mtime(root: str) -> float:
    latest = 0.0
    for folder in ("templates", "static"):
        for dirpath, _dirs, files in os.walk(os.path.join(root, folder)):
            if "vendor" in dirpath:
                continue
            for name in files:
                if name.endswith(WATCH_EXT):
                    latest = max(latest, os.path.getmtime(os.path.join(dirpath, name)))
    return latest


def register_dev_reload(app):
    @app.route("/__dev/version")
    def dev_version():
        return jsonify(version=f"{STARTED_AT:.0f}-{_latest_mtime(app.root_path):.3f}")

    @app.context_processor
    def inject_dev_reload():
        return {"dev_reload": True}
