"""PDF로 된 채용공고 읽기(외부 API 없음).

- 글이 들어 있는 PDF: 쪽마다 글을 뽑아 순서대로 잇습니다.
- 스캔 PDF(쪽에 글이 거의 없음): 그 쪽에 들어 있는 이미지를 꺼내 돌려줍니다 → OCR(AI 비전)이 읽음.
암호가 걸렸거나 PDF가 아니면 PdfReadError 를 냅니다.
"""
import io

MAX_PAGES = 15
MAX_IMAGES = 6
SCANNED_MIN_CHARS = 30  # 한 쪽의 글이 이보다 적으면 스캔 쪽으로 봄


class PdfReadError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 안내 문구를 담습니다."""


def read_pdf(data: bytes) -> dict:
    """{"text": 뽑은 글, "pages": 쪽 수, "scanned_pages": [스캔으로 본 쪽 번호], "images": [PNG bytes]}"""
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise PdfReadError("PDF 파일이 아니에요. 확장자만 .pdf 인 다른 파일인지 확인해 주세요.")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError as _PypdfError
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfReadError("암호가 걸린 PDF는 읽을 수 없어요. 암호를 푼 PDF나 캡처 이미지를 올려 주세요.")
        pages = reader.pages[:MAX_PAGES]
    except _PypdfError:
        raise PdfReadError("PDF를 열지 못했어요. 손상된 파일인지 확인해 주세요.")

    texts, scanned, images = [], [], []
    for n, page in enumerate(pages, start=1):
        text = (page.extract_text() or "").strip()
        if len(text) >= SCANNED_MIN_CHARS:
            texts.append(text)
            continue
        scanned.append(n)
        for img in _page_images(page):
            if len(images) < MAX_IMAGES:
                images.append(img)
    return {"text": "\n\n".join(texts), "pages": len(reader.pages), "scanned_pages": scanned, "images": images}


def _page_images(page) -> list[bytes]:
    """쪽에 들어 있는 큰 이미지를 PNG로(작은 로고·장식은 제외). 꺼낼 수 없는 형식은 건너뜀."""
    out = []
    try:
        found = list(page.images)
    except Exception:
        return out
    for img in found:
        try:
            im = img.image
            if im is None or im.width < 400 or im.height < 300:
                continue
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "PNG")
            out.append(buf.getvalue())
        except Exception:
            continue
    return out
