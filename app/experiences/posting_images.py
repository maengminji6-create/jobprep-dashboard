"""이미지로 된 채용공고 읽기 준비.

많은 공고가 모집부문·직무내용·자격요건·우대사항을 글이 아니라 이미지에 넣습니다.
1) collect_image_urls(): 공고 페이지에서 본문 이미지 주소를 고름(로고·아이콘 제외)
2) download_image(): 공고 링크와 같은 규칙(사설 IP 차단, 크기 제한)으로 이미지를 받음
3) to_chunks(): 세로로 긴 공고 이미지를 읽기 좋은 조각으로 잘라 data URL 로 만듦 → AI(비전)가 읽음
이미지는 저장하지 않고, 읽어 낸 글(구조화 결과)만 공고 분석에 저장합니다.
"""
import base64
import io
import re
from urllib.parse import urljoin, urlparse

import requests

SKIP_SRC = re.compile(r"(logo|icon|ico_|btn|button|sprite|avatar|profile|emoji|badge|arrow|loading|spinner|"
                      r"banner_s|thumb_s|sns|kakao|facebook|naver_|google|apple)", re.IGNORECASE)
MAX_IMAGES = 6
MAX_BYTES = 8 * 1024 * 1024
MAX_CHUNKS = 10
CHUNK_W, CHUNK_H, OVERLAP = 1100, 1400, 60
UPLOAD_EXT = {"png", "jpg", "jpeg", "webp"}


def collect_image_urls(soup, base_url: str) -> list[str]:
    """본문에 들어 있는 큰 이미지 후보(순서 유지, 중복 제거)."""
    urls = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not src or src.startswith("data:"):
            continue
        url = urljoin(base_url, src.strip())
        path = urlparse(url).path.lower()
        if path.endswith((".svg", ".gif", ".ico")) or SKIP_SRC.search(url):
            continue
        try:
            w, h = int(img.get("width", 0) or 0), int(img.get("height", 0) or 0)
        except ValueError:
            w = h = 0
        if (w and w < 200) or (h and h < 150):
            continue
        if url not in urls:
            urls.append(url)
    return urls[:MAX_IMAGES * 2]


def download_image(url: str) -> bytes | None:
    """공고 이미지 1장 받기. 이미지가 아니거나 너무 크면 None."""
    from .posting import _is_public_host
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _is_public_host(parsed.hostname):
        return None
    try:
        with requests.get(url, timeout=10, stream=True,
                          headers={"User-Agent": "Mozilla/5.0 (jobprep-dashboard; personal use)"}) as resp:
            if resp.status_code >= 400 or not resp.headers.get("Content-Type", "").startswith("image/"):
                return None
            data = b""
            for chunk in resp.iter_content(64 * 1024):
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
            return data
    except requests.RequestException:
        return None


def is_posting_sized(data: bytes) -> bool:
    """공고 본문으로 볼 만큼 큰 이미지인지(작은 배너·아이콘 제외)."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:
        return False
    return w >= 400 and h >= 300


def to_chunks(blobs: list[bytes]) -> list[str]:
    """이미지들을 가로 1100px 이하로 줄이고, 세로로 긴 것은 1400px씩 겹쳐 잘라 JPEG data URL 목록으로."""
    from PIL import Image
    out = []
    for data in blobs:
        try:
            im = Image.open(io.BytesIO(data))
            im = im.convert("RGB")
        except Exception:
            continue
        if im.width > CHUNK_W:
            im = im.resize((CHUNK_W, round(im.height * CHUNK_W / im.width)))
        top = 0
        while top < im.height and len(out) < MAX_CHUNKS:
            piece = im.crop((0, top, im.width, min(im.height, top + CHUNK_H)))
            buf = io.BytesIO()
            piece.save(buf, "JPEG", quality=85)
            out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
            if top + CHUNK_H >= im.height:
                break
            top += CHUNK_H - OVERLAP
        if len(out) >= MAX_CHUNKS:
            break
    return out


VISION_MARK = "[[이미지에서 읽은 공고 내용]]"


def vision_to_text(v: dict) -> str:
    """AI가 이미지에서 읽은 구조를 분석용 글로. 섹션 제목(주요업무·자격요건·우대사항)을 붙여 매칭 규칙이 그대로 쓰이게."""
    lines = [VISION_MARK]
    if v.get("title"):
        lines.append(v["title"])
    for p in v.get("positions", []):
        head = " · ".join(x for x in (p.get("division"), p.get("name"), p.get("type")) if x)
        lines.append(f"[모집부문] {head}")
        for label, key in (("주요업무", "duties"), ("자격요건", "requirements"), ("우대사항", "preferred")):
            items = [i for i in p.get(key, []) if i]
            if items:
                lines.append(label)
                lines += [f"- {i}" for i in items]
    common = v.get("common") or {}
    for label, key in (("자격요건", "requirements"), ("우대사항", "preferred")):
        items = [i for i in common.get(key, []) if i]
        if items:
            lines.append(f"{label} (공통)")
            lines += [f"- {i}" for i in items]
    if v.get("process"):
        lines.append("전형절차")
        lines += [f"- {i}" for i in v["process"]]
    for i in v.get("other", []):
        lines.append(i)
    return "\n".join(lines)
