# CLAUDE.md — 이 프로젝트에서 Claude Code가 지킬 규칙

## 프로젝트
무역업 취준생용 경험정리 분석 도구(GROWLY). 앱 팩토리 + 블루프린트 구조.
화면은 경험 분석(`experiences.index`), 강점 연결(`strengths.index`), 공고 매칭(`experiences.posting`), 자소서 보관함(`applications.index`), 이력 PDF(`experiences.report`)다. 다른 탭(홈 뉴스·스케줄 등)은 의도적으로 지웠다.
로컬은 SQLite(`instance/dev.db`), 배포는 PostgreSQL(`DATABASE_URL`). DB 종류에 의존하는 코드는 쓰지 않는다.

## 구조 규칙
- 기능 하나 = `app/<기능>/` 폴더 하나: `__init__.py`(Blueprint), `routes.py`, `models.py`, `services.py`(필요 시).
- `routes.py`는 요청 처리와 템플릿 렌더링만. 계산·분석 로직은 `services.py`나 별도 모듈로.
- 외부 API 호출은 `app/integrations/` 안에서만(현재 `ai_client.py`). 테스트는 실제 API를 부르지 않고 monkeypatch로 대체한다. 채용 사이트 스크래핑 코드는 만들지 않는다.
- 경험을 만들거나 고칠 때는 `experiences/services.py`의 `upsert_experience()`를 쓴다(같은 경험은 합치기).
- 새 모델은 `app/models.py`에 import 추가 → `flask db migrate -m "..."` → 생성 파일 확인 → `flask db upgrade`.

## 데이터 분리(가장 중요)
- 사용자 데이터 모델은 `UserOwnedMixin`을 상속한다.
- 조회는 `app/core/scoping.py`의 `owned()`, `get_owned_or_404()`만 사용. `Model.query.get(id)` 금지.
- 생성은 `create_owned()`로 — `user_id`는 폼에서 받지 않는다.
- 새 기능을 만들면 `tests/test_data_isolation.py`에 "남의 데이터 접근 시 404" 케이스를 추가한다.

## 보안
- 모든 POST 폼에 `csrf_token` 포함(템플릿 매크로 `csrf()`).
- 비밀값은 `.env`에만. 새 환경변수를 쓰면 `.env.example`에 이름만 추가하고 `config.py`에서 읽는다.
- 사용자 입력 URL로 서버가 요청할 때는 `experiences/posting.py`의 사설 IP 차단 방식을 따른다.
- 리다이렉트 대상은 `/`로 시작하는 내부 경로만 허용.

## 화면
- 공통 레이아웃 `templates/base.html`, 공통 조각 `templates/components/macros.html`, 로고 `templates/components/logo.html`.
- 색은 `static/css/app.css`의 `--tone-*` 변수(베이지·머스터드), 카드·모션은 `static/css/components.css`. 모션은 prefers-reduced-motion 을 존중한다. 차트는 로컬 `static/js/vendor/chart.umd.js`(Chart.js 4).
- 문구는 한국어, 짧고 구체적으로.

## 작업 마무리 체크
1. `pytest` 전부 통과
2. 모델 변경 시 마이그레이션 파일 생성·커밋
3. `flask run --debug`로 해당 화면 직접 확인
