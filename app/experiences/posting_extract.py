"""채용공고 원문 모으기: URL · 이미지 · PDF · 텍스트 → 분석 전 사용자가 확인할 원문 + '확인 필요' 목록.

순서: 입력 받기 → 글 뽑기(URL 본문 · PDF 글) → 이미지 읽기(캡처 · 링크 속 이미지 · 스캔 PDF 쪽, AI 비전)
     → 원문 점검(짧음 · 자격요건/우대사항 없음 · 깨진 글자) → 확인 화면.
한 경로가 실패해도 다른 경로로 읽은 내용으로 계속 진행하고, 실패 이유는 warnings 에 남깁니다.
로그인·CAPTCHA 페이지는 우회하지 않고 다른 입력 방식을 안내합니다.
"""
import hashlib
import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..integrations import ai_client
from . import posting_images as pim
from .posting import PostingFetchError, clean_posting_text, fetch_posting_full
from .posting_images import MAX_IMAGES, is_posting_sized, to_chunks, vision_to_text
from .posting_pdf import PdfReadError, read_pdf

MIN_TEXT = 80
REQ_HINT = re.compile(r"(자격\s*요건|지원\s*자격|필수|자격\s*사항|requirements?|qualifications?)", re.I)
PREF_HINT = re.compile(r"(우대|preferred|nice to have|plus)", re.I)
DUTY_HINT = re.compile(r"(담당\s*업무|주요\s*업무|직무\s*내용|업무\s*내용|하는\s*일|responsibilit)", re.I)


def extract(url: str = "", pasted: str = "", images: list[bytes] | None = None, pdf: bytes | None = None) -> dict:
    """{"text", "title", "company", "url", "image_urls", "vision", "sources", "warnings", "error"}
    error 가 있으면 분석할 만한 원문을 얻지 못한 것(어떻게 다시 넣으면 되는지 안내 포함)."""
    out = {"text": "", "title": "", "company": "", "url": url, "image_urls": [], "vision": {}, "sources": [],
           "warnings": [], "error": ""}
    parts, blobs = [], list(images or [])[:MAX_IMAGES]
    if blobs:
        out["sources"].append(f"캡처 이미지 {len(blobs)}장")

    if pasted:
        parts.append(clean_posting_text(pasted))
        out["sources"].append("붙여 넣은 글")

    if url and not pasted:
        try:
            page = fetch_posting_full(url)
            out["title"] = page["title"]
            if page["text"]:
                parts.append(page["text"])
            out["sources"].append("링크 본문")
            for img_url in page["images"]:
                if len(blobs) >= MAX_IMAGES:
                    break
                data = pim.download_image(img_url)
                if data and is_posting_sized(data):
                    out["image_urls"].append(img_url)
                    blobs.append(data)
            if out["image_urls"]:
                out["sources"].append(f"링크 속 이미지 {len(out['image_urls'])}장")
        except PostingFetchError as exc:
            out["warnings"].append(f"링크를 읽지 못했어요: {exc}")

    if pdf:
        try:
            got = read_pdf(pdf)
            if got["text"]:
                parts.append(got["text"])
            out["sources"].append(f"PDF {got['pages']}쪽")
            if got["scanned_pages"]:
                pages = ", ".join(map(str, got["scanned_pages"][:8]))
                if got["images"]:
                    out["warnings"].append(f"PDF {pages}쪽은 글이 아니라 이미지(스캔)예요. 이미지 속 글자를 읽어 넣었으니 틀린 곳이 없는지 확인해 주세요.")
                else:
                    out["warnings"].append(f"PDF {pages}쪽은 글을 뽑을 수 없는 스캔 쪽이에요. 그 부분은 캡처 이미지로 올려 주세요.")
            blobs += got["images"][:MAX_IMAGES - len(blobs)]
        except PdfReadError as exc:
            out["warnings"].append(str(exc))

    if blobs:
        if not ai_client.enabled():
            out["warnings"].append("이미지(캡처 · 링크 속 이미지 · 스캔 PDF)의 글자는 읽지 못했어요. 읽으려면 .env 에 "
                                   "OPENAI_API_KEY 가 필요해요. 지금은 글로 된 부분만 담았어요.")
        else:
            try:
                vision = ai_client.read_posting_images(to_chunks(blobs))
                out["vision"] = vision
                parts.append(vision_to_text(vision))
                out["company"] = (vision.get("company") or "")[:120]
                out["title"] = out["title"] or vision.get("title") or ""
            except ai_client.AiError as exc:
                out["warnings"].append(f"이미지 속 글자를 읽지 못했어요: {exc}")

    out["text"] = "\n\n".join(p.strip() for p in parts if p and p.strip())[:30000]
    out["warnings"] += check_text(out["text"])
    if len(out["text"]) < MIN_TEXT:
        out["error"] = ("공고 내용을 충분히 읽지 못했어요. 로그인·앱 전용 페이지는 열 수 없어요. "
                        "공고 화면을 캡처해 '이미지'로 올리거나, PDF로 올리거나, 본문을 복사해 '텍스트'로 넣어 주세요.")
    return out


def check_text(text: str) -> list[str]:
    """분석 전에 눈으로 확인할 곳. 공고를 판단하지 않고 '읽은 원문'의 빠진 곳·깨진 곳만 알려 줌."""
    if not text:
        return []
    notes = []
    if len(text) < 300:
        notes.append("읽은 글이 짧아요. 공고의 일부만 담겼을 수 있어요.")
    if not DUTY_HINT.search(text):
        notes.append("'담당 업무'로 보이는 부분을 찾지 못했어요.")
    if not REQ_HINT.search(text):
        notes.append("'자격요건(지원자격)'으로 보이는 부분을 찾지 못했어요. 필수 요건이 빠지면 매칭이 부정확해요.")
    if not PREF_HINT.search(text):
        notes.append("'우대사항'을 찾지 못했어요(원래 없는 공고일 수도 있어요).")
    broken = text.count("�") + len(re.findall(r"[ㄱ-ㆎ]{3,}", text))  # 깨진 글자 · 낱자 모음/자음 덩어리
    if broken >= 3:
        notes.append("깨진 글자가 섞여 있어요. 해당 부분을 고쳐 주세요.")
    return notes


# ── 같은 공고 중복 확인 ─────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """비교용 링크: 대소문자·끝 슬래시·#조각·광고 추적 값(utm_ 등)을 지움."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "ref", "fbclid", "gclid"))]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def text_hash(text: str) -> str:
    """띄어쓰기·대소문자만 다른 원문은 같은 공고로 봄."""
    norm = re.sub(r"\s+", " ", text or "").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else ""


def find_duplicate(url: str, text: str, exclude_id: int | None = None):
    """내가 이미 넣은 같은 공고(같은 링크 또는 같은 원문). 없으면 None."""
    from ..core.scoping import owned
    from .models import PostingAnalysis
    q = owned(PostingAnalysis)
    if exclude_id:
        q = q.filter(PostingAnalysis.id != exclude_id)
    h = text_hash(text)
    if h:
        same = q.filter(PostingAnalysis.text_hash == h).order_by(PostingAnalysis.created_at.desc()).first()
        if same:
            return same
    key = normalize_url(url)
    if key:
        for pa in q.filter(PostingAnalysis.url != "").order_by(PostingAnalysis.created_at.desc()).all():
            if normalize_url(pa.url) == key:
                return pa
    return None


# ── 마감일 짐작(확인 화면에 미리 채우기만 함 — 정하는 건 사용자) ─────────────

_DEADLINE_LINE = re.compile(r"(마감|접수|지원\s*기간|모집\s*기간|채용\s*기간|까지|~|deadline)", re.I)
_FULL_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_SHORT_DATE = re.compile(r"(?<![\d.:])(\d{1,2})\s*[./월]\s*(\d{1,2})\s*일?(?![\d:])")


def guess_deadline(text: str, today: date | None = None) -> date | None:
    """'접수 기간 2026.10.20 ~ 2026.11.03', '~11/3(월)', '11월 3일까지' 같은 줄에서 가장 늦은 날짜."""
    today = today or date.today()
    found = []
    for line in (text or "").splitlines():
        if not _DEADLINE_LINE.search(line):
            continue
        full = _FULL_DATE.findall(line)
        for y, m, d in full:
            try:
                found.append(date(int(y), int(m), int(d)))
            except ValueError:
                continue
        if full:
            continue
        for m, d in _SHORT_DATE.findall(line):  # 연도 없는 날짜: 올해(반년 넘게 지났으면 내년)
            try:
                dt = date(today.year, int(m), int(d))
            except ValueError:
                continue
            found.append(dt.replace(year=today.year + 1) if dt < today - timedelta(days=180) else dt)
    return max(found) if found else None
