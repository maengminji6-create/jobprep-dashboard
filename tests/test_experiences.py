import io
import os

from app.experiences.analyzer import analyze
from app.experiences.models import Experience, PostingAnalysis
from app.experiences.parser import split_experiences
from app.extensions import db

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_experiences.txt")


def test_split_experiences_by_headers():
    with open(FIXTURE, encoding="utf-8") as f:
        items = split_experiences(f.read())
    assert len(items) == 3
    assert items[0]["period"].startswith("2025.07")
    assert items[0]["category"] == "인턴·실무"


def test_analyze_scores_trade_roles():
    exp = Experience(id=1, title="포워딩 인턴", content="선적 부킹과 컨테이너 운임 견적, B/L 서류를 처리하고 물류 비용을 15% 절감")
    a = analyze(exp)
    assert a["roles"]["forwarding"]["score"] > a["roles"]["overseas_marketing"]["score"]
    assert a["usage"]["strength"] > 0
    assert "15%" in a["numbers"]


def test_upload_txt_creates_experiences(auth_client, user):
    with open(FIXTURE, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "경험정리.txt")}
    r = auth_client.post("/experiences/upload", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert db.session.query(Experience).filter_by(user_id=user.id).count() == 3
    page = auth_client.get("/experiences/?role=customs").get_data(as_text=True)
    assert "관세·통관 TOP 3 경험" in page


def test_posting_analysis_with_pasted_text(auth_client, user):
    db.session.add(Experience(user_id=user.id, title="통관 인턴",
                              content="HS코드 품목분류와 수입신고 업무를 지원하고 FTA 원산지증명 발급을 도왔습니다."))
    db.session.commit()
    posting = ("[담당업무]\n수입 통관 및 HS코드 품목분류\n관세 환급 업무\n"
               "[자격요건]\n관세 관련 전공자\n엑셀 활용 가능자\n[우대사항]\n원산지관리사 자격 보유자\nFTA 실무 경험자")
    r = auth_client.post("/experiences/posting", data={"posting_text": posting, "company": "테스트관세법인"},
                         follow_redirects=True)
    assert r.status_code == 200
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    assert pa.result["main_role"] == "customs"
    assert pa.result["recommendations"][0]["title"] == "통관 인턴"


def test_posting_blocks_private_urls(auth_client, user):
    db.session.add(Experience(user_id=user.id, title="x", content="y"))
    db.session.commit()
    r = auth_client.post("/experiences/posting", data={"url": "http://127.0.0.1/admin"}, follow_redirects=True)
    assert "접근할 수 없는 주소" in r.get_data(as_text=True)


def _xlsx_bytes(rows):
    from openpyxl import Workbook
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_spreadsheet_maps_columns():
    from app.experiences.parser import parse_spreadsheet
    data = _xlsx_bytes([
        ["내 경험정리 시트"],
        ["경험명", "구분", "회사", "시작", "종료", "행동", "결과"],
        ["포워딩사 인턴", "인턴", "OO로지스", "2025.01", "2025.06", "FCL 부킹과 선적 스케줄 관리", "운임 비교표로 비용 8% 절감"],
        ["", "", "", "", "", "", ""],
        ["토익 900", "자격증·어학", "", "2024.11", "", "", ""],
    ])
    _, items = parse_spreadsheet("경험.xlsx", data)
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "포워딩사 인턴"
    assert first["category"] == "인턴·실무"
    assert first["organization"] == "OO로지스"
    assert first["period"] == "2025.01 ~ 2025.06"
    assert first["content"] == "종류: 인턴\nFCL 부킹과 선적 스케줄 관리"
    assert first["strengths"] == "운임 비교표로 비용 8% 절감"


def test_parse_spreadsheet_with_stacked_tables():
    """한 시트에 아르바이트 표(기관명)와 대외활동 표(활동명)가 위아래로 있는 경우."""
    from app.experiences.parser import parse_spreadsheet
    data = _xlsx_bytes([
        ["순번", "기관명", "종류", "기간", "개월", "나의 역할", "key-word", "강약점", "느낀점"],
        [1, "LG 호주 법인", "인턴(BOP CE)", "2025.04 ~ 2025.08", "4개월", "S&OP 회의, 장기재고 계산", "꼼꼼함", None, None],
        [2, "세븐일레븐", "편의점/알바", "2023.03 ~ 2024.01", "11개월", "재고 관리", None, None, None],
        [None] * 9,
        ["순번", "활동명", "종류", "기간", "인원(명)", "나의 역할", "key-word", "강약점", "느낀점"],
        [1, "RISE", "논문", "2024.03~06", "3명", "논문 작성", "#탄소국경조정제도", None, None],
        [2, "버디", "봉사", None, "1명", "외국인 유학생 도움", None, None, None],
    ])
    _, items = parse_spreadsheet("경험.xlsx", data)
    assert [i["title"] for i in items] == ["LG 호주 법인 · 인턴(BOP CE)", "세븐일레븐 · 편의점/알바", "RISE", "버디"]
    assert [i["category"] for i in items] == ["인턴·실무", "아르바이트", "공모전·수상", "봉사"]
    assert items[0]["period"] == "2025.04 ~ 2025.08 (4개월)"
    assert items[0]["role"] == "S&OP 회의, 장기재고 계산" and items[0]["keywords"] == "꼼꼼함"
    assert "3명" in items[2]["content"] and items[2]["keywords"] == "#탄소국경조정제도"


def test_upload_xlsx_and_csv(auth_client, user):
    data = _xlsx_bytes([["제목", "내용"], ["해외 전시회 바이어 응대", "바이어 20명 상담, 견적 요청 5건 확보"]])
    r = auth_client.post("/experiences/upload", data={"file": (io.BytesIO(data), "경험정리.xlsx")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "경험 1개".encode() in r.data
    csv_bytes = "제목,분류,내용\n관세 환급 프로젝트,프로젝트,HS코드 분류로 환급액 계산\n".encode("cp949")
    r = auth_client.post("/experiences/upload", data={"file": (io.BytesIO(csv_bytes), "경험.csv")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "경험 1개".encode() in r.data
    titles = {e.title for e in db.session.query(Experience).filter_by(user_id=user.id)}
    assert {"해외 전시회 바이어 응대", "관세 환급 프로젝트"} <= titles


def test_upload_sample_docx(auth_client, user):
    path = os.path.join(os.path.dirname(__file__), "..", "samples", "경험정리_샘플.docx")
    with open(path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "경험정리_샘플.docx")}
    auth_client.post("/experiences/upload", data=data, content_type="multipart/form-data")
    from app.experiences.models import Certificate
    cats = {e.category for e in db.session.query(Experience).filter_by(user_id=user.id)}
    assert {"인턴·실무", "프로젝트"} <= cats and "자격증·어학" not in cats
    assert db.session.query(Certificate).filter_by(user_id=user.id).count() >= 1  # 자격증 행은 자격증으로


def test_save_adds_and_merges_into_existing(auth_client, user):
    auth_client.post("/experiences/save", data={"title": "LG 호주 법인 인턴", "role": "장기재고 계산",
                                                "keywords": "#꼼꼼함, 엑셀"})
    exp = db.session.query(Experience).filter_by(user_id=user.id).one()
    assert exp.role == "장기재고 계산" and exp.keyword_list == ["꼼꼼함", "엑셀"]

    # 같은 이름으로 다시 저장 → 새로 만들지 않고 덧붙임(중복 문장·키워드는 제외)
    auth_client.post("/experiences/save", data={"title": "LG 호주 법인 인턴", "role": "장기재고 계산\nS&OP 회의 참여",
                                                "strengths": "리포트 작성 시간 50% 단축", "keywords": "엑셀 #S&OP"})
    # 목록에서 고른 경험에 느낀점만 추가
    auth_client.post("/experiences/save", data={"target_id": exp.id, "reflection": "숫자로 말하는 습관"})
    db.session.refresh(exp)
    assert db.session.query(Experience).filter_by(user_id=user.id).count() == 1
    assert exp.role == "장기재고 계산\nS&OP 회의 참여"
    assert exp.strengths == "리포트 작성 시간 50% 단축" and exp.reflection == "숫자로 말하는 습관"
    assert exp.keyword_list == ["꼼꼼함", "엑셀", "S&OP"]
    page = auth_client.get("/experiences/?role=scm").get_data(as_text=True)
    assert "글로벌 SCM TOP 3 경험" in page and "LG 호주 법인 인턴" in page


def test_reupload_updates_instead_of_duplicating(auth_client, user):
    rows = [["경험명", "나의 역할", "키워드"], ["포워딩 인턴", "FCL 부킹", "#꼼꼼함"]]
    for _ in range(2):
        auth_client.post("/experiences/upload", data={"file": (io.BytesIO(_xlsx_bytes(rows)), "a.xlsx")},
                         content_type="multipart/form-data")
    rows = [["경험명", "나의 역할", "키워드"], ["포워딩 인턴", "운임 견적 비교", "#책임감"]]
    r = auth_client.post("/experiences/upload", data={"file": (io.BytesIO(_xlsx_bytes(rows)), "a.xlsx")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "기존 경험 업데이트 1개" in r.get_data(as_text=True)
    exps = db.session.query(Experience).filter_by(user_id=user.id).all()
    assert len(exps) == 1
    assert exps[0].role == "FCL 부킹\n운임 견적 비교" and exps[0].keyword_list == ["꼼꼼함", "책임감"]
