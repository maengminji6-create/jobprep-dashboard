"""공고 매칭: 원문 섹션 표시 · 근거 문장 · 강점/자격증 연결 · 저장/다시 매칭/메모 · AI 리포트(가짜) · 본문 추출."""
from bs4 import BeautifulSoup

from app.experiences.models import Certificate, Experience, PostingAnalysis
from app.experiences.posting import _main_text, split_sections
from app.extensions import db
from app.strengths.models import StrengthProfile

from .conftest import login, make_user

POSTING = """(주)한빛무역 해외영업 신입 채용
주요업무
- 해외 바이어 발굴 및 수출 오더 관리
- 선적서류(인보이스, 패킹리스트) 작성
자격요건
- 영어 비즈니스 커뮤니케이션 가능자
- 꼼꼼하게 서류를 점검하는 분
우대사항
- 국제무역사 자격 보유자
- 엑셀 활용 능숙자
근무조건
- 서울 본사, 정규직
"""


def _setup(user):
    db.session.add(Experience(user_id=user.id, title="무역회사 인턴", category="인턴·실무",
                              role="해외 바이어 응대와 수출 오더 관리. 인보이스와 패킹리스트 작성 후 꼼꼼히 점검",
                              content="", strengths="", keywords="엑셀", reflection=""))
    db.session.add(Certificate(user_id=user.id, name="국제무역사 1급", score="합격"))
    db.session.add(StrengthProfile(user_id=user.id, filename="강점.txt", extracted_text="x", is_active=True,
                                   parsed_json='{"strengths": [{"name": "신중함", "summary": "미리 살핍니다", "rank": 1}]}'))
    db.session.commit()


def test_split_sections_and_main_text():
    secs = split_sections(POSTING)
    assert [s["name"] for s in secs] == ["공고 개요", "업무", "자격요건", "우대사항", "근무조건"]
    assert "국제무역사 자격 보유자" in secs[3]["lines"][0]
    html = "<html><body><nav>메뉴 메뉴</nav><div><div>광고 " + "배너 " * 80 + "</div><div>" + \
           POSTING.replace("\n", "<br>") + "</div></div><footer>회사소개</footer></body></html>"
    text = _main_text(BeautifulSoup(html, "html.parser"))
    assert "자격요건" in text and "배너" not in text and "메뉴" not in text


def test_posting_match_shows_original_and_evidence(auth_client, user):
    _setup(user)
    r = auth_client.post("/experiences/posting", data={"company": "한빛무역", "posting_text": POSTING},
                         follow_redirects=True)
    page = r.get_data(as_text=True)
    doc = page.split("<h3>공고 원문</h3>")[1].split("match-panel")[0]
    assert "<li>" not in doc  # 원문에 없는 글머리 기호를 붙이지 않음
    assert '<p class="doc-h kind-자격요건">자격요건</p>' in doc and '<p class="doc-l">- 서울 본사, 정규직</p>' in doc
    assert 'class="hl-exp" title="내 경험과 겹치는 단어">바이어</mark>' in doc  # 경험과 겹침 = 노랑
    assert 'class="hl-str" title="내 강점 단서">꼼꼼</mark>' in doc  # 강점(신중함) 단서 = 초록
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    rec = pa.result["recommendations"][0]
    assert rec["title"] == "무역회사 인턴" and rec["evidence"]
    ev = rec["evidence"][0]
    assert ev["words"] and all(w.lower() in ev["posting"].lower() and w.lower() in ev["experience"].lower() for w in ev["words"])
    assert pa.result["strength_matches"][0]["name"] == "신중함"  # '꼼꼼' 단서
    cert = pa.result["cert_matches"][0]
    assert cert["name"] == "국제무역사 1급" and cert["mentioned"] and cert["relevance"] >= 80
    assert "내 경험" in page and "공고에 언급" in page


def test_saved_posting_edit_search_reanalyze_and_ai(app, auth_client, user, monkeypatch):
    _setup(user)
    auth_client.post("/experiences/posting", data={"company": "한빛무역", "posting_text": POSTING})
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    auth_client.post(f"/experiences/posting/{pa.id}/edit", data={"company": "한빛무역", "title": "해외영업", "memo": "10/31 마감"})
    assert "10/31 마감" in auth_client.get("/experiences/posting?q=마감").get_data(as_text=True)
    assert "한빛무역" not in auth_client.get("/experiences/posting?q=없는회사").get_data(as_text=True).split("저장한 공고")[1][:400]

    # 이력을 바꾸고 다시 매칭 → 새 경험이 반영
    db.session.add(Experience(user_id=user.id, title="엑셀 리포트 알바", category="아르바이트", role="엑셀로 재고 리포트",
                              content="", strengths="", keywords="", reflection=""))
    db.session.commit()
    auth_client.post(f"/experiences/posting/{pa.id}/reanalyze")
    db.session.refresh(pa)
    assert "엑셀 리포트 알바" in [r["title"] for r in pa.result["recommendations"]]

    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    exp_id = db.session.query(Experience).filter_by(user_id=user.id, title="무역회사 인턴").one().id

    def fake(text, exps, certs, profile, role_name):
        assert profile is not None and certs and "국제무역사" in text
        return {"posting_summary": "서류에 강한 신입", "fit_summary": "잘 맞아요", "essay_strategy": "전략",
                "matches": [{"requirement": "수출 오더 관리", "experience_id": exp_id, "evidence": "오더 관리",
                             "why": "같은 업무"}],
                "strengths": [{"name": "신중함", "posting_signal": "꼼꼼하게", "how_to_show": "점검 사례"}],
                "gaps": [{"requirement": "비즈니스 영어", "suggestion": "영어 이메일 사례 정리"}]}
    monkeypatch.setattr(ai_client, "match_posting_ai", fake)
    page = auth_client.post(f"/experiences/posting/{pa.id}/ai", follow_redirects=True).get_data(as_text=True)
    assert "서류에 강한 신입" in page and "같은 업무" in page and "영어 이메일 사례 정리" in page


def test_posting_is_private(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    pa = PostingAnalysis(user_id=b.id, title="B 공고", company="B사", posting_text=POSTING, result_json="{}")
    db.session.add(pa)
    db.session.commit()
    login(client, a.email)
    assert client.get(f"/experiences/posting/{pa.id}").status_code == 404
    for url in ("reanalyze", "edit", "ai", "delete"):
        assert client.post(f"/experiences/posting/{pa.id}/{url}").status_code == 404, url
    assert "B사" not in client.get("/experiences/posting").get_data(as_text=True)


SITE_TEXT = """[티디씨엑스코리아] 고객경험 담당자 | 링커리어
Internet Explorer
서비스 종료
MY 이력 관리
공유하기
스크랩한 사용자 전체보기 (
0
명)
상세내용
[티디씨엑스코리아] 고객경험 담당자
[지원자격]
- 고객 서비스 경험자
[주요업무]
- 이메일, 채팅 고객 문의 응대
[전형절차]
- 서류전형 - HR면접 - 입사
[공고상세]
허위·과장·오류 내용이 있다면 신고해주세요.
신고하기
이 활동에 관심을 가지는 사용자 (
0
명)
스터디 모집
이화여대 / 경영학 / 학점 3.92 / 토스 IH
이 공고 조회자가 많이 본 공고
"""


def test_clean_posting_text_drops_site_ui():
    from app.experiences.posting import clean_posting_text, has_body
    c = clean_posting_text(SITE_TEXT)
    assert c.splitlines()[0] == "[티디씨엑스코리아] 고객경험 담당자"  # '상세내용' 아래부터
    assert "[지원자격]" in c and "서류전형 - HR면접 - 입사" in c
    for junk in ("신고", "스크랩", "관심을 가지는", "스터디", "이화여대", "Internet Explorer", "공고상세", "\n0\n", "명)"):
        assert junk not in c, junk
    assert has_body(c) and not has_body("메뉴\n로그인")


def test_inline_elements_stay_on_one_line():
    html = ("<html><body><div><h3>[지원자격]</h3><p>- 고객 서비스 경험자</p><h3>[주요업무]</h3><p>- 문의 응대</p>"
            "<p>관심 사용자 (<span>12</span>명) <b>우대</b>합니다</p><p>줄1<br>줄2</p></div></body></html>")
    text = _main_text(BeautifulSoup(html, "html.parser"))
    assert "관심 사용자 (12명) 우대합니다" in text and "줄1\n줄2" in text


def test_old_saved_posting_is_cleaned_when_opened(auth_client, user):
    _setup(user)
    pa = PostingAnalysis(user_id=user.id, title="옛 공고", posting_text=SITE_TEXT, result_json="{}")
    db.session.add(pa)
    db.session.commit()
    page = auth_client.get(f"/experiences/posting/{pa.id}").get_data(as_text=True)
    import re
    doc = re.sub(r"<[^>]+>", "", page.split("<h3>공고 원문</h3>")[1].split("match-panel")[0])  # 강조 태그 제거
    assert "신고하기" not in doc and "스터디 모집" not in doc and "고객 서비스 경험자" in doc
    db.session.refresh(pa)
    assert "스크랩" not in pa.posting_text
