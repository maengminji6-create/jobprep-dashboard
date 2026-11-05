# CLAUDE.md — 이 프로젝트에서 Claude Code가 지킬 규칙

## 프로젝트
무역업 취준생용 경험정리 분석 도구(CAIRN). 앱 팩토리 + 블루프린트 구조.
메뉴는 홈(`experiences.index`), 경험 관리(`experiences.manage`), AI 분석(`analysis.index`), 직무 연결(`jobfit.index`, 기준표 `core/job_competencies.py`), 자소서 보관함(`applications.index`)이고, 이력 PDF(`experiences.report`)는 홈에서 연다. 강점 진단 결과 등록(`strengths.index`)은 AI 분석에서 들어간다. 홈 뉴스 탭은 의도적으로 지웠다.
홈은 `experiences/dashboard.py`, 나의 강점 사용 설명서는 `analysis/manual.py`(저장본 `StrengthManual`)가 저장된 데이터만 엮어 만든다. 직무 적합도 같은 0–100 점수는 화면에 쓰지 않는다(키워드 점수 `experiences/analyzer.py`는 자소서 코멘트 기준 직무 추천과 경험 수정 화면의 ★ 참고 표시에만 남음). 자소서 AI 초안은 `applications/services.py`의 `draft_evidence()`로 분석·강점 근거를 함께 넘긴다.
AI 분석 결과(`ExperienceAnalysis`, `StrengthLink`)는 경험 원문 인용이 확인된 항목만 저장한다(`analysis/services.py`의 `locate()`). 역량 이름은 `core/competencies.py` 기준표 하나만 쓴다. 진단 순위와 경험 근거는 하나의 점수로 합치지 않는다.
공고 매칭(`experiences.posting*`)·면접 준비(`interview.*`)·취업 일정(`schedule.*`)은 리뉴얼 동안 쉬는 기능: `LEGACY_FEATURES=1`일 때만 메뉴·화면이 열리고, 꺼져 있으면 404(`app/__init__.py`의 `is_legacy_endpoint`). 코드·데이터는 지우지 않는다. 테스트 설정은 켜 둔 상태다.
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
- 색은 `static/css/app.css`의 `--tone-*` 변수(슬레이트 블루), 카드·모션은 `static/css/components.css`. 모션은 prefers-reduced-motion 을 존중한다. 차트는 로컬 `static/js/vendor/chart.umd.js`(Chart.js 4).
- 문구는 한국어, 짧고 구체적으로.

## 작업 마무리 체크
1. `pytest` 전부 통과
2. 모델 변경 시 마이그레이션 파일 생성·커밋
3. `flask run --debug`로 해당 화면 직접 확인
