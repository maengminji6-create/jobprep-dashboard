"""자격증 분리·관련도 · TOP 3 빼기/되돌리기 · 저장본 저장/불러오기/파일."""
import io
import json

from app.core.certificates import cert_bonus, evaluate
from app.experiences.models import Certificate, Experience, Snapshot, TopExclusion
from app.extensions import db

from .conftest import login, make_user


def _add(user, title, role, category="인턴·실무"):
    e = Experience(user_id=user.id, title=title, category=category, role=role, content="", strengths="",
                   keywords="", reflection="")
    db.session.add(e)
    db.session.commit()
    return e


def test_trade_certificate_is_relevant_to_overseas_sales():
    ev = evaluate("국제무역사 1급", "합격")
    assert ev["known"] and ev["roles"]["overseas_sales"] >= 80 and ev["roles"]["trade_admin"] == 100
    assert evaluate("TOEIC", "950")["roles"]["overseas_sales"] > evaluate("TOEIC", "700")["roles"]["overseas_sales"]
    assert evaluate("OPIc", "IH")["roles"]["overseas_sales"] > 60
    assert cert_bonus([ev], "overseas_sales") >= 12
    assert evaluate("이상한 자격증")["known"] is False


def test_certificate_card_shows_relevance_and_boosts_role(auth_client, user):
    _add(user, "바이어 응대 인턴", "해외 바이어 견적 대응과 수출 오더 관리")
    auth_client.post("/experiences/certificate", data={"cert_name": "국제무역사 1급", "cert_score": "합격"})
    manage = auth_client.get("/experiences/manage?role=overseas_sales").get_data(as_text=True)
    assert "국제무역사 1급" in manage and "무역 실무 전반" in manage and "해외영업 관련 높음" in manage


def test_excel_certificate_rows_become_certificates(auth_client, user):
    from openpyxl import Workbook
    wb = Workbook()
    for r in [["경험명", "분류", "기간", "나의 역할"], ["포워딩 인턴", "인턴", "2025.01", "FCL 부킹"],
              ["무역영어 1급", "자격증", "2024.11", ""]]:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    r = auth_client.post("/experiences/upload", data={"file": (io.BytesIO(buf.getvalue()), "a.xlsx")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "자격증·어학 1개" in r.get_data(as_text=True)
    assert [c.name for c in db.session.query(Certificate).filter_by(user_id=user.id)] == ["무역영어 1급"]
    assert [e.title for e in db.session.query(Experience).filter_by(user_id=user.id)] == ["포워딩 인턴"]


def test_snapshot_save_load_export_import(auth_client, user):
    _add(user, "원래 경험", "수출 오더 관리")
    db.session.add(Certificate(user_id=user.id, name="TOEIC", score="900"))
    db.session.commit()
    auth_client.post("/experiences/data/save", data={"name": "10월 버전"})
    snap = db.session.query(Snapshot).filter_by(user_id=user.id).one()
    assert snap.exp_count == 1 and snap.cert_count == 1

    # 내용을 바꾼 뒤 저장본 불러오기 → 원래대로, 바뀐 상태는 자동 저장
    auth_client.post("/experiences/reset", data={"confirm": "삭제"})
    _add(user, "새 경험", "재고 관리")
    r = auth_client.post(f"/experiences/data/{snap.id}/load", data={"parts": ["experiences"]}, follow_redirects=True)
    assert "불러왔어요" in r.get_data(as_text=True)
    assert [e.title for e in db.session.query(Experience).filter_by(user_id=user.id)] == ["원래 경험"]
    assert [c.name for c in db.session.query(Certificate).filter_by(user_id=user.id)] == ["TOEIC"]
    names = [s.name for s in db.session.query(Snapshot).filter_by(user_id=user.id)]
    assert any("불러오기 전 자동 저장" in n for n in names) and any("전체 지우기 전 자동 저장" in n for n in names)

    # 파일로 내려받기 → 다시 올리기
    res = auth_client.get("/experiences/data/export")
    assert res.mimetype == "application/json" and "attachment" in res.headers["Content-Disposition"]
    data = json.loads(res.get_data(as_text=True))
    assert data["format"] == "growly-backup" and data["experiences"][0]["title"] == "원래 경험"
    r = auth_client.post("/experiences/data/import", data={"file": (io.BytesIO(res.get_data()), "backup.json")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "저장본으로 추가했어요" in r.get_data(as_text=True)
    bad = auth_client.post("/experiences/data/import", data={"file": (io.BytesIO(b'{"x":1}'), "x.json")},
                           content_type="multipart/form-data", follow_redirects=True)
    assert "CAIRN에서 내려받은 저장본" in bad.get_data(as_text=True)


def test_snapshots_certs_exclusions_are_private(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    e = _add(b, "B 경험", "수출")
    cert = Certificate(user_id=b.id, name="B 자격증")
    snap = Snapshot(user_id=b.id, name="B 저장본", data_json=json.dumps({"format": "growly-backup", "experiences": []}))
    db.session.add_all([cert, snap])
    db.session.commit()
    login(client, a.email)
    for url in (f"/experiences/data/{snap.id}/load", f"/experiences/data/{snap.id}/delete",
                f"/experiences/certificate/{cert.id}/delete"):
        assert client.post(url).status_code == 404, url
    assert client.get(f"/experiences/data/{snap.id}/download").status_code == 404
    assert client.get(f"/experiences/certificate/{cert.id}/edit").status_code == 404
    assert "B 자격증" not in client.get("/experiences/manage").get_data(as_text=True)
