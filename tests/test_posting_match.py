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
    db.session.add(Experience(user_id=user.id, title="엑셀 리포트 알바", category="아르바이트", role="엑셀로 인보이스·패킹리스트 정리, 해외 바이어 문의 응대",
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


def test_no_highlight_for_generic_words_or_weak_matches(auth_client, user):
    """'본인이·실제·글로벌' 같은 일반 단어나 우연히 한 단어만 겹친 경험은 강조·추천하지 않음."""
    db.session.add(Experience(user_id=user.id, title="카페 아르바이트", category="아르바이트",
                              role="본인이 실제로 매장 청소와 글로벌 손님 응대", content="", strengths="", keywords="",
                              reflection=""))
    db.session.commit()
    text = ("글로벌 영업팀 채용\n주요업무\n- 본인이 실제로 해외 바이어 발굴과 수출 오더 관리\n자격요건\n- 영어 가능\n"
            "우대사항\n- 국제무역사 보유, 글로벌 경험")
    auth_client.post("/experiences/posting", data={"company": "테스트상사", "posting_text": text})
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    assert pa.result["recommendations"] == [] and pa.result["highlight"] == []
    page = auth_client.get(f"/experiences/posting/{pa.id}").get_data(as_text=True)
    doc = page.split('<div class="doc-body">')[1].split("match-panel")[0]  # 범례 제외, 원문만
    assert "hl-exp" not in doc and "hl-str" not in doc


LINKAREER_IMAGE_POSTING = """MY 이력 관리
무료 공고등록
기업형태
중견기업
접수기간
시작일2026.09.28
마감일2026.10.18
채용형태
채용연계형 인턴, 신입
근무지역
서울 송파구, 경기 평택시
홈페이지
https://www.example.com
관심 유저 통계 보기
상세내용
[한미그룹] 2026년 하반기 공개채용
[모집기간]
[모집분야]
-[한미약품] 해외영업
-[한미약품] 구매
[채용공고]
'지원서 파일 없음'
학교, 전공, 연령, 관심 직무 현황을 확인할 수 있어요!
지원부터 면접까지 함께 준비할 스터디를 찾아보세요
전남도립대학교 / 미래자동차 / 학점 4.49/4.5 / / 기타: 설비보전기능사
이 글은 한미그룹 생산직에 합격한 지원자의 실제 자기소개서입니다.
1. 본인이 지원한 직무의 지원동기와 입사 후 어떻게 성장하고 싶은지 작성해주십시오.
[설비 운영의 가치를 체득한 계기와 성장 의지]
공군 공병으로 복
[한국수력원자력] 2026년도 제2차 체험형 청년인턴 선발 모집요강
조회 21,002
댓글 0
링커리어
• 링커리어 소개• 공지사항• 채용• 회사 공시사항
Copyright © Linkareer Inc. All Rights Reserved.
"""


def test_site_widgets_after_image_posting_are_dropped():
    """본문이 이미지인 공고: 합격 자소서·스터디·추천 공고(조회·댓글)·푸터·남의 스펙은 빼고, 링크에 적힌 공고 정보만 남김."""
    from app.experiences.posting import clean_posting_text
    c = clean_posting_text(LINKAREER_IMAGE_POSTING)
    for junk in ("지원서 파일 없음", "스터디", "학점", "자기소개서", "본인이 지원한", "설비 운영의 가치", "공군",
                 "한국수력원자력", "조회", "댓글", "링커리어", "Copyright", "[채용공고]", "[모집기간]", "MY 이력", "통계"):
        assert junk not in c, junk
    assert c.splitlines()[:5] == ["공고 요약", "기업형태 · 중견기업", "접수 · 2026.09.28 ~ 2026.10.18",
                                  "채용형태 · 채용연계형 인턴, 신입", "지역 · 서울 송파구, 경기 평택시"]
    assert "[모집분야]\n-[한미약품] 해외영업\n-[한미약품] 구매" in c
    assert clean_posting_text(c) == c  # 다시 정리해도 그대로


def test_heading_with_bullet_value_is_kept():
    from app.experiences.posting import clean_posting_text
    t = "[지원자격]\n- 신입가능\n[근무형태]\n- 급여조건 : 기본급+인센티브 별도"
    assert clean_posting_text(t) == t
