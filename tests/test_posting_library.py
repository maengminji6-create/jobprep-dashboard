"""공고 매칭 보관: 조회 기록 vs ★저장 · 저장 취소 · 기록 지우기 · 산업/직무 분류·필터 · 비교 · 다른 사람 접근 차단."""
from app.core.industries import detect_industry
from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db

from .conftest import login, make_user

BEAUTY = ("코스알엑스 화장품 해외영업 신입 채용\n주요업무\n- 해외 바이어 발굴, 수출 오더 관리, 아마존 채널 운영 지원\n"
          "자격요건\n- 영어 비즈니스 커뮤니케이션 가능자\n우대사항\n- K뷰티 화장품 수출 경험, 스킨케어 제품 이해")
LOGI = ("한빛로지스 국제물류 포워딩 신입 채용\n주요업무\n- 수출입 선적 부킹, 해상 운임 견적, 컨테이너 스케줄 관리\n"
        "자격요건\n- 물류 산업 관심, 꼼꼼한 서류 처리\n우대사항\n- 물류관리사 자격 보유자")


def _exp(user):
    db.session.add(Experience(user_id=user.id, title="무역 인턴", category="인턴·실무", role="바이어 응대, 수출 오더 관리, 선적 부킹",
                              content="", strengths="", keywords="", reflection=""))
    db.session.commit()


def test_detect_industry():
    assert detect_industry(BEAUTY) == "beauty"
    assert detect_industry(LOGI) == "logistics"
    assert detect_industry("아무 내용") == "etc"


def test_history_vs_saved_and_clear(auth_client, user):
    _exp(user)
    auth_client.post("/experiences/posting", data={"company": "코스알엑스", "posting_text": BEAUTY})
    auth_client.post("/experiences/posting", data={"company": "한빛로지스", "posting_text": LOGI, "save_now": "1"})
    rows = {p.company: p for p in db.session.query(PostingAnalysis).filter_by(user_id=user.id)}
    assert rows["코스알엑스"].is_saved is False and rows["한빛로지스"].is_saved is True
    assert rows["코스알엑스"].industry == "beauty" and rows["한빛로지스"].industry == "logistics"

    page = auth_client.get("/experiences/posting").get_data(as_text=True)
    saved_part = page.split('id="saved"')[1].split('id="history"')[0]
    history_part = page.split('id="history"')[1]
    assert "한빛로지스" in saved_part and "코스알엑스" not in saved_part
    assert "코스알엑스" in history_part

    # 조회 기록에서 ★ 저장 → 저장한 공고로, 다시 누르면 저장 취소
    pid = rows["코스알엑스"].id
    auth_client.post(f"/experiences/posting/{pid}/save")
    assert db.session.get(PostingAnalysis, pid).is_saved
    auth_client.post(f"/experiences/posting/{pid}/save")
    assert not db.session.get(PostingAnalysis, pid).is_saved

    # 기록 전체 지우기: 저장 안 한 것만
    r = auth_client.post("/experiences/posting/history/clear", follow_redirects=True)
    assert "1개를 지웠어요" in r.get_data(as_text=True)
    assert [p.company for p in db.session.query(PostingAnalysis).filter_by(user_id=user.id)] == ["한빛로지스"]


def test_filters_edit_and_compare(auth_client, user):
    _exp(user)
    for comp, text in (("코스알엑스", BEAUTY), ("한빛로지스", LOGI)):
        auth_client.post("/experiences/posting", data={"company": comp, "posting_text": text, "save_now": "1"})
    a, b = db.session.query(PostingAnalysis).filter_by(user_id=user.id).order_by(PostingAnalysis.id).all()
    page = auth_client.get("/experiences/posting?ind=beauty").get_data(as_text=True)
    saved_part = page.split('id="saved"')[1].split('id="history"')[0]
    assert "코스알엑스" in saved_part and "한빛로지스" not in saved_part and "화장품·뷰티" in page

    auth_client.post(f"/experiences/posting/{b.id}/edit", data={"company": "한빛로지스", "title": "x", "memo": "",
                                                                "industry": "trading", "role_code": "forwarding"})
    db.session.refresh(b)
    assert b.industry == "trading" and b.role_code == "forwarding"
    assert "한빛로지스" in auth_client.get("/experiences/posting?prole=forwarding").get_data(as_text=True).split('id="saved"')[1].split('id="history"')[0]

    page = auth_client.get(f"/experiences/posting/compare?ids={a.id}&ids={b.id}").get_data(as_text=True)
    assert "저장한 공고 비교" in page and "가장 잘 맞는 공고" in page and "코스알엑스" in page and "한빛로지스" in page
    assert "쓸 경험 TOP 3" in page and "무역 인턴" in page
    r = auth_client.get(f"/experiences/posting/compare?ids={a.id}", follow_redirects=True)
    assert "2~4개 골라" in r.get_data(as_text=True)


def test_library_is_private(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    mine = PostingAnalysis(user_id=a.id, title="내 공고", posting_text="x", result_json="{}", is_saved=True)
    theirs = PostingAnalysis(user_id=b.id, title="남의 공고", company="B사", posting_text="x", result_json="{}")
    db.session.add_all([mine, theirs])
    db.session.commit()
    login(client, a.email)
    assert client.post(f"/experiences/posting/{theirs.id}/save").status_code == 404
    assert client.get(f"/experiences/posting/compare?ids={mine.id}&ids={theirs.id}").status_code == 404
    client.post("/experiences/posting/history/clear")
    assert db.session.get(PostingAnalysis, theirs.id) is not None  # 남의 기록은 안 지워짐
    assert "B사" not in client.get("/experiences/posting").get_data(as_text=True)
