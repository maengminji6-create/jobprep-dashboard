"""경험 구조화: STAR 칸 · 역량 추천(근거 문장) · 빈 칸 질문 · AI 초안 검증(지어낸 숫자 차단) · 활용 내역."""
from app.experiences.models import Experience, PostingAnalysis
from app.experiences.structuring import (check_ai_competencies, check_draft, star_gaps,
                                         suggest_competencies)
from app.extensions import db

from .conftest import login, make_user


def _exp(user, **kw):
    fields = dict(title="LG 호주 법인 인턴", category="인턴·실무", organization="LG 호주 법인",
                  role="현지 바이어 영문 메일 응대와 수출 오더 관리", content="엑셀로 재고 리포트를 정리해 팀 회의에 공유",
                  strengths="", keywords="", reflection="")
    fields.update(kw)
    e = Experience(user_id=user.id, **fields)
    db.session.add(e)
    db.session.commit()
    return e


def test_competency_suggestions_come_with_evidence(app, user):
    e = _exp(user)
    names = {c["name"]: c for c in suggest_competencies(e)}
    assert "글로벌 커뮤니케이션" in names and "무역 실무" in names and "데이터 분석" in names
    assert "바이어" in names["글로벌 커뮤니케이션"]["words"] and "바이어" in names["글로벌 커뮤니케이션"]["evidence"]
    e.competencies = "무역 실무"
    assert "무역 실무" not in {c["name"] for c in suggest_competencies(e)}  # 이미 단 태그는 다시 추천 안 함


def test_star_gaps_ask_questions_and_no_number_nudge(app, user):
    e = _exp(user)
    assert {g["field"] for g in star_gaps(e)} == {"star_situation", "star_task", "star_action", "star_result"}
    assert "자유 기록" in star_gaps(e)[0]["label"]  # STAR가 비었는데 메모가 있으면 옮기라고 먼저 안내
    e.star_situation, e.star_task, e.star_result = "인턴 2개월 차", "재고 보고 지연", "보고가 빨라짐"
    e.star_action = "내가 재고 시트를 품목별로 다시 묶고 매주 엑셀 정리를 맡았다"
    gaps = star_gaps(e)
    assert len(gaps) == 1 and "실제로 잰 값" in gaps[0]["question"]  # 숫자를 지어내라고 하지 않음


def test_star_gaps_flag_short_or_team_only_action(app, user):
    e = _exp(user)
    e.star_situation, e.star_task, e.star_result = "상황", "과제", "리포트 작성 시간 2시간 → 30분"
    e.star_action = "엑셀 정리"
    assert any("2~3가지" in g["question"] for g in star_gaps(e))
    e.star_action = "우리 팀원들이 함께 공급업체 목록을 비교하고 단가표를 다시 만들었다"
    assert any("내가 맡아서" in g["question"] for g in star_gaps(e))


def test_check_draft_blocks_invented_numbers():
    source = "바이어 메일 응대, 주 3회 리포트 작성"
    clean, notes = check_draft({"star_situation": "호주 법인 영업팀", "star_task": "주 3회 리포트",
                                "star_action": "메일 응대", "star_result": "응답 시간 40% 단축"}, source)
    assert clean["star_task"] == "주 3회 리포트" and clean["star_result"] == ""  # 원문에 없는 40% → 비움
    assert any("40" in n for n in notes)


def test_ai_competency_evidence_must_be_quoted_from_my_text():
    source = "현지 바이어 영문 메일 응대와 수출 오더 관리"
    kept = check_ai_competencies([{"name": "글로벌 커뮤니케이션", "evidence": "현지 바이어 영문 메일 응대"},
                                  {"name": "리더십", "evidence": "팀 10명을 이끌었다"}], source)
    assert [k["name"] for k in kept] == ["글로벌 커뮤니케이션"]


def test_edit_saves_star_competencies_and_roles(auth_client, user):
    e = _exp(user)
    page = auth_client.get(f"/experiences/{e.id}/edit").get_data(as_text=True)
    assert "STAR로 정리" in page and "채우면 좋은 칸" in page and 'data-add-tag="글로벌 커뮤니케이션"' in page
    data = {"title": e.title, "category": e.category, "organization": e.organization, "period": "", "role": e.role,
            "content": e.content, "strengths": "", "reflection": "", "keywords": "",
            "star_situation": "인턴 2개월 차", "star_task": "재고 보고 지연", "star_action": "엑셀로 정리", "star_result": "보고 주기 단축",
            "competencies": "무역 실무, #데이터 분석, 무역 실무", "related_roles": ["overseas_sales", "없는직무"]}
    auth_client.post(f"/experiences/{e.id}/edit", data=data)
    db.session.refresh(e)
    assert e.star_action == "엑셀로 정리" and e.competency_list == ["무역 실무", "데이터 분석"]
    assert e.related_role_list == ["overseas_sales"]  # 없는 직무 코드는 버림
    assert "엑셀로 정리" in auth_client.get("/experiences/report").get_data(as_text=True)


def test_structure_without_key_explains(auth_client, user):
    e = _exp(user)
    r = auth_client.post(f"/experiences/{e.id}/structure", follow_redirects=True)
    assert "OPENAI_API_KEY" in r.get_data(as_text=True)


def test_structure_with_ai_fills_draft_but_does_not_save(app, auth_client, user, monkeypatch):
    from app.integrations import ai_client
    e = _exp(user)
    app.config["OPENAI_API_KEY"] = "test-key"
    monkeypatch.setattr(ai_client, "structure_experience", lambda exp, role: {
        "star_situation": "LG 호주 법인 인턴 기간", "star_task": "", "star_action": "현지 바이어 영문 메일 응대",
        "star_result": "매출 25% 증가",
        "competencies": [{"name": "글로벌 커뮤니케이션", "evidence": "현지 바이어 영문 메일 응대"},
                         {"name": "리더십", "evidence": "팀을 이끌었다"}],
        "questions": ["결과로 무엇이 달라졌나요?"]})
    page = auth_client.post(f"/experiences/{e.id}/structure").get_data(as_text=True)
    assert "AI 초안" in page and "현지 바이어 영문 메일 응대</textarea>" in page
    assert "매출 25% 증가" not in page and "원문에 없는 숫자(25)" in page  # 지어낸 성과는 초안에서 뺌
    assert "✦ 글로벌 커뮤니케이션" in page and "✦ 리더십" not in page  # 근거 인용이 내 글에 없으면 버림
    assert "결과로 무엇이 달라졌나요?" in page
    db.session.refresh(e)
    assert not e.star_action  # 저장은 사용자가 확인한 뒤


def test_usage_lists_postings_and_essays(app, auth_client, user):
    e = _exp(user)
    posting = ("자격요건\n- 해외 바이어 응대 경험자\n- 수출 오더 관리 경험\n우대사항\n- 엑셀 리포트 작성 가능자\n"
               "담당업무\n- 수출 오더 관리와 바이어 메일 응대 업무 전반")
    auth_client.post("/experiences/posting", data={"mode": "text", "posting_text": posting, "company": "한빛무역"})
    auth_client.post("/applications/new", data={"company": "한빛무역", "q": ["지원 동기"], "limit": [""],
                                                "a": ["LG 호주 법인에서 바이어 메일을 응대하며 배웠습니다."]})
    page = auth_client.get(f"/experiences/{e.id}/edit").get_data(as_text=True)
    side = page.split('class="exp-side"')[1]
    assert "근거로 쓰인 공고" in side and "한빛무역" in side and "요건" in side and "충족" in side
    assert "답변에 쓴 자소서 문항" in side and "지원 동기" in side


def test_cannot_structure_or_edit_others_experience(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    ea, eb = _exp(a, title="A의 경험"), _exp(b)
    login(client, a.email)
    assert client.post(f"/experiences/{eb.id}/structure").status_code == 404
    assert client.get(f"/experiences/{eb.id}/edit").status_code == 404
    # 남의 공고 분석에 내 경험 id가 들어 있어도 내 활용 내역에는 나오지 않음
    pb = PostingAnalysis(user_id=b.id, title="B의 비밀 공고", posting_text="x",
                         result_json='{"requirements": {"support": [{"id": %d, "met": 1, "items": []}]}}' % ea.id)
    db.session.add(pb)
    db.session.commit()
    assert "B의 비밀 공고" not in client.get(f"/experiences/{ea.id}/edit").get_data(as_text=True)
