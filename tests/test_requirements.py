"""공고 요건 하나하나를 내 경험과 대조: 충족 · 확인 필요 · 근거 없음 + 근거 문장. 근거 없이 확정하지 않음."""
from app.experiences.models import Certificate, Experience, PostingAnalysis
from app.experiences.posting import ANALYSIS_VERSION, split_sections
from app.experiences.requirements import check_requirements, posting_structure, terms
from app.extensions import db

POSTING = ("한빛무역 해외영업 신입(정규직)\n담당업무\n- 해외 바이어 발굴 및 수출 오더 관리\n"
           "자격요건\n- 해외 바이어 응대 경험자\n- 학사 이상\n- 영어 가능자(구술, 서술)\n"
           "우대사항\n- 엑셀 리포트 작성 가능자, SAP 사용 경험\n- 국제무역사 자격 보유자\n근무지: 서울 강남구 본사")


class _Exp:
    def __init__(self, i, title, text):
        self.id, self.title, self.full_text = i, title, text


EXPS = [_Exp(1, "LG 호주 법인 인턴", "현지 바이어 메일 응대와 수출 오더 관리\n엑셀로 재고 리포트 자동화"),
        _Exp(2, "무역 동아리", "해외 바이어 상담 모의 대회 기획")]


def _by_text(result):
    return {i["text"]: i for i in result["items"]}


def test_three_states_with_evidence():
    r = check_requirements(split_sections(POSTING), EXPS, [])
    items = _by_text(r)
    met = items["해외 바이어 응대 경험자"]
    assert met["status"] == "met" and met["evidence"][0]["title"] == "LG 호주 법인 인턴"
    assert "바이어" in met["evidence"][0]["words"] and "바이어" in met["evidence"][0]["sentence"]
    assert items["학사 이상"]["status"] == "check"  # 학력은 경험 기록으로 판단하지 않음
    assert items["영어 가능자(구술, 서술)"]["status"] == "none"  # 괄호 안 쉼표로 나누지 않음
    assert "경험이 없다는 뜻은 아니에요" in items["영어 가능자(구술, 서술)"]["reason"]
    assert items["엑셀 리포트 작성 가능자"]["status"] == "met"  # 한 줄의 여러 요건을 나눔
    assert items["SAP 사용 경험"]["status"] == "none" and items["SAP 사용 경험"]["suggestion"]
    assert r["summary"]["required"] == {"total": 3, "met": 1, "check": 1, "none": 1}
    assert r["support"][0]["title"] == "LG 호주 법인 인턴"


def test_certificate_counts_as_met():
    cert = Certificate(name="국제무역사 1급", score="합격")
    items = _by_text(check_requirements(split_sections(POSTING), EXPS, [cert]))
    assert items["국제무역사 자격 보유자"]["status"] == "met" and "국제무역사 1급" in items["국제무역사 자격 보유자"]["reason"]


def test_english_posting_matches_korean_experience():
    en = "Requirements: experience with overseas buyers and export orders, business English\nPreferred: Excel reporting"
    items = _by_text(check_requirements(split_sections(en), EXPS, []))
    first = items["experience with overseas buyers and export orders"]
    assert first["status"] == "met" and {"바이어", "수출"} <= set(first["evidence"][0]["words"])  # 경험에 적힌 말로
    assert items["business English"]["status"] == "none"
    assert items["Excel reporting"]["status"] == "met"


def test_no_requirement_sections_means_not_enough():
    r = check_requirements(split_sections("회사 소개\n좋은 회사입니다."), EXPS, [])
    assert r["items"] == [] and not r["enough"]


def test_structure_and_terms():
    s = posting_structure(split_sections(POSTING), POSTING)
    assert s["duties"] == ["- 해외 바이어 발굴 및 수출 오더 관리"] and "정규직" in s["employment"]
    assert s["location"].startswith("근무지") and "서울" in s["location"]
    assert terms("영어 가능자(구술, 서술)") == ["영어", "구술", "서술"]


def test_detail_page_shows_requirement_checks(auth_client, user):
    db.session.add(Experience(user_id=user.id, title="LG 호주 법인 인턴", category="인턴·실무",
                              role="현지 바이어 메일 응대와 수출 오더 관리", content="엑셀로 재고 리포트 자동화",
                              strengths="", keywords="", reflection=""))
    db.session.commit()
    page = auth_client.post("/experiences/posting", data={"mode": "text", "posting_text": POSTING, "company": "한빛무역"},
                            follow_redirects=True).get_data(as_text=True)
    assert "필수·우대 요건 확인" in page and "필수 충족" in page and "req-met" in page and "근거 없음" in page
    assert "자소서에 쓸 경험" in page and "근무지 · " in page
    pa = db.session.query(PostingAnalysis).one()
    assert pa.result["version"] == ANALYSIS_VERSION and pa.result["requirements"]["summary"]["required"]["met"] == 1


def test_two_letter_korean_matches_word_start_only():
    """'업계'가 '사업계획서' 한가운데 걸리지 않음."""
    exps = [_Exp(1, "콘퍼런스", "정보전달, PT, 사업계획서 작성")]
    text = "자격요건\n- 고객 서비스 또는 여행 업계 경험자"
    item = check_requirements(split_sections(text), exps, [])["items"][0]
    assert item["status"] == "none" and not item["evidence"]


def test_old_analysis_gets_deadline_when_reopened(auth_client, user):
    db.session.add(Experience(user_id=user.id, title="인턴", category="인턴·실무", role="바이어 응대", content="",
                              strengths="", keywords="", reflection=""))
    pa = PostingAnalysis(user_id=user.id, title="예전 공고", posting_text="[모집기간]\n- 2026.11.13 까지\n" + POSTING,
                         result_json='{"version": 3}')
    db.session.add(pa)
    db.session.commit()
    auth_client.get(f"/experiences/posting/{pa.id}")
    db.session.refresh(pa)
    from datetime import date
    assert pa.deadline == date(2026, 11, 13) and pa.result["version"] == ANALYSIS_VERSION
