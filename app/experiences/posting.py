"""채용공고 분석: 사용자가 직접 넣은 공고 링크 1개(또는 붙여넣은 공고 글)를 읽어 내 경험·강점·자격증과 매칭합니다.

- 사용자가 요청한 링크 한 건만 그 자리에서 읽습니다(같은 사이트의 본문 iframe 1개까지). 사이트를 돌아다니며 모으지 않습니다.
- 로그인·JS 렌더링 페이지는 내용을 못 읽을 수 있으므로 '공고 내용 붙여넣기'를 함께 지원합니다.
- 내부망 주소로 요청하지 않도록(SSRF 방지) 사설 IP는 차단합니다.
- 추천마다 '공고의 어느 문장 ↔ 내 경험의 어느 문장'이 같은 단어로 이어지는지 근거를 함께 돌려줍니다.
"""
import ipaddress
import re
import socket
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..core.trade_roles import COMMON_SIGNALS, ROLE_BY_CODE, TRADE_ROLES, USAGE_LABELS
from .analyzer import essay_question_for, role_scores

PREFERRED_RE = re.compile(r"(우대\s*사항|우대\s*조건|우대|preferred|plus|nice to have)", re.IGNORECASE)
REQUIRED_RE = re.compile(r"(자격\s*요건|지원\s*자격|필수|requirements|qualifications|담당\s*업무|주요\s*업무)",
                         re.IGNORECASE)
TOKEN_STOP = set("및 등 경우 관련 업무 담당 담당자 가능 우대 이상 이하 필수 지원 자격 사항 채용 모집 회사 근무 경력 신입 "
                 "또는 있는 있으신 가능한 가능자 경험 경험이 경험자 보유자 보유 능숙자 위한 통해 대한 분야 해당 "
                 "the and for with you our will are".split())

# 공고 본문을 섹션으로 나누는 제목 패턴
SECTION_PATTERNS = [
    ("업무", re.compile(r"^\s*[\[【■●◆▶•·\-\d\.\)]*\s*(주요\s*업무|담당\s*업무|업무\s*내용|하는\s*일|직무\s*내용|"
                       r"job\s*description|responsibilit\w*|what\s+you.?ll\s+do)", re.IGNORECASE)),
    ("자격요건", re.compile(r"^\s*[\[【■●◆▶•·\-\d\.\)]*\s*(자격\s*요건|지원\s*자격|필수\s*(요건|사항|조건)?|"
                         r"requirements?|qualifications?)", re.IGNORECASE)),
    ("우대사항", re.compile(r"^\s*[\[【■●◆▶•·\-\d\.\)]*\s*(우대\s*(사항|조건)?|preferred|nice\s*to\s*have|plus)",
                         re.IGNORECASE)),
    ("근무조건", re.compile(r"^\s*[\[【■●◆▶•·\-\d\.\)]*\s*(근무\s*(조건|지|형태|시간)|고용\s*형태|급여|연봉|복리\s*후생|혜택|"
                         r"전형\s*절차|채용\s*절차|접수\s*(기간|방법)|제출\s*서류)", re.IGNORECASE)),
]
BODY_HINTS = ("자격", "우대", "담당", "주요업무", "업무", "requirement", "qualification")


class PostingFetchError(Exception):
    pass


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _get(url: str):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PostingFetchError("http:// 또는 https:// 로 시작하는 링크를 넣어 주세요.")
    if not _is_public_host(parsed.hostname):
        raise PostingFetchError("접근할 수 없는 주소입니다.")
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0 (jobprep-dashboard; personal use)"})
    except requests.RequestException as exc:
        raise PostingFetchError(f"링크를 열지 못했습니다({exc.__class__.__name__}). 공고 내용을 붙여 넣어 주세요.")
    if resp.status_code >= 400:
        raise PostingFetchError(f"사이트가 요청을 거부했습니다(HTTP {resp.status_code}). 공고 내용을 붙여 넣어 주세요.")
    if "html" not in resp.headers.get("Content-Type", "html"):
        raise PostingFetchError("HTML 공고 페이지가 아닙니다. 공고 내용을 붙여 넣어 주세요.")
    return resp


BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "tr", "table", "section", "article", "main", "h1", "h2", "h3", "h4", "h5",
              "h6", "dl", "dt", "dd", "blockquote", "pre", "header", "footer", "figure", "figcaption"]

# 채용 사이트 화면 요소: 이 문구가 나오면 그 아래는 공고가 아니라 사이트 UI(신고·스크랩·추천 공고·커뮤니티 등)
END_MARKERS = re.compile(
    r"(허위.{0,8}과장.{0,20}신고|신고하기|이 공고를 스크랩|스크랩한 사용자|관심을 가지는 사용자|스터디 모집|"
    r"지원서 다운로드|합격\s*자소서|조회자가 많이 본|함께 본 공고|비슷한 공고|추천 공고|인기 활동|담당자\s*Q&A|"
    r"BEST 이야기|기업\s*리뷰|연봉\s*정보 보기|이 기업의 다른 공고)")
# 한 줄씩 빼는 버튼·라벨
JUNK_LINE = re.compile(r"^(\[?공고\s*상세\]?|공유하기|스크랩|지원하기|홈페이지 지원|목록|이전|다음|top|로그인|회원가입|"
                       r"더보기|접기|닫기|댓글|조회|d-\d+)$", re.IGNORECASE)


def _lines(node) -> str:
    """보이는 그대로 줄 나누기: 블록 요소 경계·<br>에서만 줄을 바꾸고, span·b 같은 인라인은 한 줄로 이어 붙임."""
    raw = node.get_text("")
    out = []
    for ln in raw.splitlines():
        ln = re.sub(r"[ \t ​]+", " ", ln).strip()
        if ln:
            out.append(ln)
    return "\n".join(out)


def _mark_blocks(soup) -> None:
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")


START_MARKER = re.compile(r"^(상세\s*내용|상세\s*요강|모집\s*요강|공고\s*내용)$")
BROWSER_NOTICE = re.compile(r"(internet explorer|브라우저로 접속|서비스 종료)", re.IGNORECASE)


def _is_section_head(ln: str) -> bool:
    return len(ln) <= 40 and any(pat.match(ln) for name, pat in SECTION_PATTERNS if name != "근무조건")


def has_body(text: str) -> bool:
    """업무·자격요건·우대사항 같은 본문 제목이 있는지(정리 결과를 믿고 저장해도 되는지 판단)."""
    return any(_is_section_head(ln.strip()) for ln in (text or "").splitlines())


def clean_posting_text(text: str) -> str:
    """사이트 UI 문구를 걷어 내고 공고 본문만 남깁니다. 붙여넣은 글·예전에 저장한 공고에도 씁니다.

    - '상세내용' 같은 표시가 있으면 그 아래부터 읽음(위쪽은 사이트 메뉴·요약 박스)
    - 본문(업무·자격요건·우대사항 제목)이 나온 뒤 '신고하기·스크랩한 사용자' 같은 사이트 UI가 나오면 그 아래는 버림
    - 본문 전에 나오는 그런 문구, 버튼 라벨, 숫자·괄호만 있는 줄은 한 줄씩 뺌
    """
    lines = [re.sub(r"[ \t ​]+", " ", ln).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    start = next((i + 1 for i, ln in enumerate(lines) if START_MARKER.match(ln)), 0)
    if start and any(_is_section_head(ln) for ln in lines[start:]):
        lines = lines[start:]
    out, body_started = [], False
    for ln in lines:
        if _is_section_head(ln):
            body_started = True
        if END_MARKERS.search(ln):
            if body_started:
                break  # 본문 뒤의 사이트 UI 는 통째로 버림
            continue
        if JUNK_LINE.match(ln) or BROWSER_NOTICE.search(ln) or not re.search(r"[가-힣A-Za-z]{2,}", ln):
            continue
        out.append(ln)
    return "\n".join(out)


def _main_text(soup) -> str:
    """공고 본문 고르기: '자격·우대·담당' 같은 단어가 2개 이상 든 블록 중 가장 작은(구체적인) 것."""
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg", "form", "aside", "button"]):
        tag.decompose()
    _mark_blocks(soup)
    best = None
    for node in soup.find_all(["article", "main", "section", "div", "td"]):
        text = _lines(node)
        if len(text) < 120:
            continue
        low = text.lower().replace(" ", "")
        if sum(1 for h in BODY_HINTS if h in low) >= 2 and (best is None or len(text) < len(best)):
            best = text
    return best or _lines(soup.body or soup)


def fetch_posting(url: str) -> tuple[str, str]:
    """(페이지 제목, 공고 본문 텍스트)를 돌려줍니다."""
    resp = _get(url)
    soup = BeautifulSoup(resp.content, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "")[:300]
    text = _main_text(soup)
    # 본문이 같은 사이트의 iframe 안에 있는 공고(예: 상세 내용 별도 페이지)는 그 페이지 1개만 더 읽음
    if len(text) < 300:
        host = urlparse(resp.url).hostname
        for frame in soup.find_all("iframe", src=True):
            src = urljoin(resp.url, frame["src"])
            if urlparse(src).hostname == host:
                try:
                    inner = BeautifulSoup(_get(src).content, "html.parser")
                    inner_text = _main_text(inner)
                    if len(inner_text) > len(text):
                        text = inner_text
                except PostingFetchError:
                    pass
                break
    return title, clean_posting_text(text)[:30000]


# ── 공고 구조 ───────────────────────────────────────────────────────

HEADING_RE = re.compile(r"^([\[【〈<]\s*[^\]】〉>]{1,24}\s*[\]】〉>]|[■●◆▶◼□]\s*.{1,24}|.{1,20}[:：])$")


def doc_lines(text: str) -> list[dict]:
    """공고 원문을 그대로 한 줄씩. 글머리 기호를 붙이지 않고, 제목 줄(예: [모집기간], 자격요건)만 표시해 굵게 보여 줍니다.
    [{"text": 원문 줄, "head": 제목 줄인지, "kind": 업무|자격요건|우대사항|근무조건|기타}]"""
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        bullet = ln[0] in "-·•*○◦ㆍ※"  # 원문에서 글머리로 시작하는 줄은 내용(제목 아님)
        kind = None if bullet else next((name for name, pat in SECTION_PATTERNS if len(ln) <= 40 and pat.match(ln)), None)
        is_head = not bullet and (bool(kind) or (len(ln) <= 26 and bool(HEADING_RE.match(ln))))
        out.append({"text": ln, "head": is_head, "kind": kind or "기타"})
    return out


def split_sections(text: str) -> list[dict]:
    """[{"name": "업무|자격요건|우대사항|근무조건|공고 개요", "lines": [...]}] — 화면에 공고 원문을 보여 줄 때 사용."""
    sections, cur = [], {"name": "공고 개요", "lines": []}
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        head = next((name for name, pat in SECTION_PATTERNS if len(ln) <= 40 and pat.match(ln)), None)
        if head:
            if cur["lines"]:
                sections.append(cur)
            cur = {"name": head, "lines": []}
            rest = SECTION_PATTERNS[[n for n, _ in SECTION_PATTERNS].index(head)][1].sub("", ln, count=1).strip(" :：-")
            if len(rest) > 3:
                cur["lines"].append(rest)
        else:
            cur["lines"].append(ln)
    if cur["lines"]:
        sections.append(cur)
    return sections


def _sections(text: str) -> tuple[str, str]:
    """본문을 '필수/업무' 영역과 '우대' 영역으로 대략 나눕니다."""
    required, preferred, mode = [], [], "required"
    for ln in text.splitlines():
        if PREFERRED_RE.search(ln) and len(ln) < 40:
            mode = "preferred"
        elif REQUIRED_RE.search(ln) and len(ln) < 40:
            mode = "required"
        (preferred if mode == "preferred" else required).append(ln)
    return "\n".join(required), "\n".join(preferred)


def _dict_words(text: str) -> set[str]:
    low = text.lower()
    words = set()
    for role in TRADE_ROLES:
        words.update(kw for kw in role["keywords"] if kw.lower() in low)
    for s in COMMON_SIGNALS.values():
        words.update(w for w in s["words"] if w.lower() in low)
    return words


def _frequent_tokens(text: str, n: int = 15) -> list[str]:
    toks = [t for t in re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", text) if t.lower() not in TOKEN_STOP]
    return [w for w, c in Counter(toks).most_common(60) if c >= 2][:n]


def _sentences(text: str) -> list[str]:
    out = []
    for ln in (text or "").splitlines():
        for part in re.split(r"(?<=[.!?。])\s+|\s*/\s+|\s*➡\s*", ln):
            part = part.strip(" -•·")
            if 6 <= len(part) <= 220:
                out.append(part)
    return out


def _evidence(words: list[str], posting_lines: list[str], exp_lines: list[str], limit: int = 2) -> list[dict]:
    """같은 단어가 들어 있는 (공고 문장, 내 경험 문장) 쌍. 단어가 많이 겹치는 쌍부터."""
    pairs, used_p, used_e = [], set(), set()
    for w in words:
        wl = w.lower()
        p = next((s for s in posting_lines if wl in s.lower() and s not in used_p), None)
        e = next((s for s in exp_lines if wl in s.lower() and s not in used_e), None)
        if p and e:
            shared = [x for x in words if x.lower() in p.lower() and x.lower() in e.lower()]
            pairs.append({"posting": p, "experience": e, "words": shared or [w]})
            used_p.add(p)
            used_e.add(e)
    pairs.sort(key=lambda x: len(x["words"]), reverse=True)
    return pairs[:limit]


# ── 매칭 ────────────────────────────────────────────────────────────

def analyze_posting(posting_text: str, analyses: list[dict], experiences: dict, certs: list | None = None,
                    strengths: list[dict] | None = None) -> dict:
    """공고 텍스트 + 내 경험 분석 결과(+자격증, 강점) → 추천 경험(근거 문장 포함)·강점·자격증·부족한 키워드."""
    required_txt, preferred_txt = _sections(posting_text)
    req_words = _dict_words(required_txt)
    pref_words = _dict_words(preferred_txt) - req_words
    all_words = req_words | pref_words
    freq = _frequent_tokens(posting_text)
    # 근거 문장은 업무·자격요건·우대사항에서 먼저 찾음(제목·근무조건 줄은 근거로 약함)
    core = [ln for sec in split_sections(posting_text) if sec["name"] in ("업무", "자격요건", "우대사항")
            for ln in sec["lines"]]
    posting_lines = _sentences("\n".join(core)) or _sentences(posting_text)

    rs = role_scores(posting_text)
    top_roles = sorted(rs.items(), key=lambda kv: kv[1]["score"], reverse=True)[:3]
    main_role = top_roles[0][0] if top_roles and top_roles[0][1]["score"] > 0 else "overseas_sales"

    recs, covered = [], set()
    for a in analyses:
        exp = experiences[a["id"]]
        exp_text = exp.full_text.lower()
        hit_req = sorted(w for w in req_words if w.lower() in exp_text)
        hit_pref = sorted(w for w in pref_words if w.lower() in exp_text)
        dict_hits = {w.lower() for w in hit_req + hit_pref}
        hit_freq = [t for t in freq if t.lower() in exp_text and t.lower() not in dict_hits][:5]
        covered.update(hit_req, hit_pref)
        if not (hit_req or hit_pref or hit_freq):
            continue  # 공고와 겹치는 단어가 하나도 없으면 추천하지 않음
        score = len(hit_req) * 12 + len(hit_pref) * 8 + len(hit_freq) * 4 + a["roles"][main_role]["score"] * 0.35 \
            + max(a["usage"].values()) * 0.1
        points = hit_req + hit_pref + hit_freq
        recs.append({
            "id": a["id"], "title": a["title"], "category": a["category"], "score": min(100, round(score)),
            "hit_required": hit_req, "hit_preferred": hit_pref, "hit_tokens": hit_freq,
            "role_fit": a["roles"][main_role]["score"], "best_usage": USAGE_LABELS[a["best_usage"]],
            "question": essay_question_for(a), "numbers": a["numbers"],
            "evidence": _evidence(points, posting_lines, _sentences(exp.full_text)),
            "appeal": _appeal_sentence(a, points, ROLE_BY_CODE[main_role]["name"]),
        })
    recs.sort(key=lambda r: r["score"], reverse=True)

    return {
        "main_role": main_role, "main_role_name": ROLE_BY_CODE[main_role]["name"],
        "top_roles": [{"code": c, "name": ROLE_BY_CODE[c]["name"], "score": v["score"]} for c, v in top_roles],
        "required_keywords": sorted(req_words), "preferred_keywords": sorted(pref_words),
        "frequent_tokens": freq, "recommendations": recs[:6],
        "gaps_required": sorted(req_words - covered), "gaps_preferred": sorted(pref_words - covered),
        "coverage": round(len(covered & all_words) / len(all_words) * 100) if all_words else 0,
        "strength_matches": _strength_matches(strengths or [], posting_lines),
        "cert_matches": _cert_matches(certs or [], posting_text, main_role),
        "highlight": sorted(all_words | set(freq[:8]), key=len, reverse=True),
    }


def _strength_matches(strengths: list[dict], posting_lines: list[str]) -> list[dict]:
    """공고가 원하는 성향(문장 속 단서 단어)과 내 강점이 맞닿는 곳. strengths 는 link_strengths() 결과."""
    from ..strengths.services import _clues
    out = []
    for s in strengths:
        clues = _clues(s["name"])
        lines = [ln for ln in posting_lines if any(c in ln for c in clues)][:2]
        if not lines:
            continue
        words = sorted({c for c in clues for ln in lines if c in ln})
        out.append({"name": s["name"], "summary": s.get("summary", ""), "posting_lines": lines, "words": words,
                    "experiences": [m["title"] for m in s.get("matches", [])[:2]]})
    return out


def _cert_matches(certs: list, posting_text: str, main_role: str) -> list[dict]:
    low = posting_text.lower().replace(" ", "")
    out = []
    for c in certs:
        ev = c.evaluation
        # '국제무역사 1급', 'TOEIC 900' → '국제무역사', 'toeic' 처럼 급수·점수를 떼고 공고에 나오는지 확인
        base = re.sub(r"\s*(\d\s*급|\d+\s*점?|level\s*\d+|lv\.?\s*\d+)\s*$", "", c.name.strip(), flags=re.IGNORECASE)
        base = base.lower().replace(" ", "")
        mentioned = len(base) >= 2 and base in low
        rel = ev["roles"].get(main_role, 0)
        if mentioned or rel >= 40:
            out.append({"name": c.name, "score": c.score or "", "relevance": rel, "mentioned": mentioned,
                        "reason": ev["reason"]})
    return sorted(out, key=lambda x: (x["mentioned"], x["relevance"]), reverse=True)


def _appeal_sentence(a: dict, points: list[str], role_name: str) -> str:
    kw = ", ".join(points[:3]) if points else "직무 관련 역량"
    num = f" 특히 '{a['numbers'][0]}' 같은 수치 성과를 첫 문장에 배치하세요." if a["numbers"] else \
        " 결과를 숫자(%, 건수, 금액)로 표현할 수 있는지 다시 확인해 보세요."
    return (f"'{a['title']}' 경험은 공고가 요구하는 {kw}와 연결됩니다. "
            f"{role_name} 직무의 '{essay_question_for(a)}' 문항 소재로 쓰고, 상황→행동→결과 순서로 정리하세요.{num}")
