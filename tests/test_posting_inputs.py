"""채용공고 입력 4가지(링크 · 이미지 · PDF · 텍스트): 원문 추출 → 확인·수정 → 분석, 실패해도 다른 방식 안내."""
import io

from PIL import Image

from app.experiences import posting_extract as pex
from app.experiences.models import Experience, PostingAnalysis
from app.experiences.posting_pdf import PdfReadError, read_pdf
from app.extensions import db

from .conftest import login, make_user
from .test_posting_images import VISION, submit_review

POSTING_EN = ("Overseas Sales Associate. Responsibilities: develop overseas buyers, manage export orders and shipping "
              "schedules. Requirements: business English, trade documents. Preferred: international trade certificate.")


def text_pdf(text: str) -> bytes:
    """글자(Helvetica)가 들어 있는 1쪽짜리 PDF를 직접 만듦."""
    lines = [text[i:i + 80] for i in range(0, len(text), 80)]
    ops = "BT /F1 11 Tf 40 780 Td 14 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def scanned_pdf() -> bytes:
    """글은 없고 이미지만 들어 있는 PDF(스캔본)."""
    buf = io.BytesIO()
    Image.new("RGB", (900, 1200), (250, 250, 250)).save(buf, "PDF")
    return buf.getvalue()


def _exp(user):
    db.session.add(Experience(user_id=user.id, title="수출 인턴", category="인턴·실무",
                              role="overseas buyers export orders shipping schedules trade documents business English",
                              content="", strengths="", keywords="", reflection=""))
    db.session.commit()


def test_read_pdf_text_and_scanned_and_invalid():
    got = read_pdf(text_pdf(POSTING_EN))
    assert "Responsibilities" in got["text"] and got["pages"] == 1 and not got["scanned_pages"]
    got = read_pdf(scanned_pdf())
    assert got["scanned_pages"] == [1] and len(got["images"]) == 1 and got["text"] == ""
    try:
        read_pdf(b"not a pdf at all")
        raise AssertionError("PDF가 아닌데 통과함")
    except PdfReadError as exc:
        assert "PDF 파일이 아니에요" in str(exc)


def test_pdf_upload_goes_through_review_and_user_edits_are_used(auth_client, user):
    _exp(user)
    r = auth_client.post("/experiences/posting", data={"mode": "pdf", "pdf": (io.BytesIO(text_pdf(POSTING_EN)), "job.pdf")},
                         content_type="multipart/form-data")
    review = r.get_data(as_text=True)
    assert "읽은 원문 확인" in review and "PDF 1쪽" in review and "Responsibilities" in review
    edited = review.replace("Overseas Sales Associate.", "Overseas Sales Associate. 원산지 증명 업무 포함.")
    submit_review(auth_client, edited)
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    assert "원산지 증명 업무 포함" in pa.posting_text  # 확인 화면에서 고친 글로 분석
    assert "extract_warnings" in pa.result


def test_scanned_pdf_without_key_explains(auth_client, user):
    _exp(user)
    r = auth_client.post("/experiences/posting", data={"mode": "pdf", "pdf": (io.BytesIO(scanned_pdf()), "scan.pdf")},
                         content_type="multipart/form-data", follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "OPENAI_API_KEY" in page and "충분히 읽지 못했어요" in page  # 읽은 글이 없으면 분석하지 않고 다른 방식 안내
    assert not db.session.query(PostingAnalysis).count()


def test_scanned_pdf_is_read_by_vision(app, auth_client, user, monkeypatch):
    _exp(user)
    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    monkeypatch.setattr(ai_client, "read_posting_images", lambda chunks: VISION)
    review = auth_client.post("/experiences/posting", data={"mode": "pdf", "pdf": (io.BytesIO(scanned_pdf()), "scan.pdf")},
                              content_type="multipart/form-data").get_data(as_text=True)
    assert "이미지(스캔)" in review and "구매 전략 수립" in review and 'value="한미약품"' in review


def test_link_failure_suggests_other_inputs(auth_client, user, monkeypatch):
    _exp(user)

    def blocked(url):
        raise pex.PostingFetchError("로그인이 필요한 페이지예요.")
    monkeypatch.setattr(pex, "fetch_posting_full", blocked)
    page = auth_client.post("/experiences/posting", data={"mode": "url", "url": "https://example.com/job"},
                            follow_redirects=True).get_data(as_text=True)
    assert "로그인이 필요한 페이지예요" in page and "캡처해" in page and "PDF로 올리거나" in page
    assert 'value="url" checked' in page  # 입력 화면으로 돌아옴(링크는 그대로)


def test_text_is_analyzed_directly_with_check_notes(auth_client, user):
    _exp(user)
    auth_client.post("/experiences/posting", data={"mode": "text", "posting_text": POSTING_EN + " " * 5})
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    assert any("자격요건" in w for w in pa.result["extract_warnings"]) is False  # Requirements 가 있으면 경고 없음


def test_check_text_flags_missing_parts():
    notes = pex.check_text("해외영업 담당 업무: 바이어 관리")
    assert any("자격요건" in n for n in notes) and any("우대사항" in n for n in notes) and any("짧아요" in n for n in notes)


def test_edit_posting_text_and_isolation(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    pb = PostingAnalysis(user_id=b.id, title="B의 공고", posting_text="B 원문", result_json="{}")
    db.session.add(pb)
    db.session.commit()
    login(client, a.email)
    assert client.post(f"/experiences/posting/{pb.id}/text", data={"posting_text": "x" * 100}).status_code == 404
    db.session.refresh(pb)
    assert pb.posting_text == "B 원문"
