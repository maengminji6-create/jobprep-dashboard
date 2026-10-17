"""업로드한 경험정리 파일에서 경험 단위를 뽑습니다.

- 문서(.docx .pdf .txt .md): 텍스트를 뽑아 제목 줄 기준으로 나눔
- 표(.xlsx .xlsm .xls .csv): 한 행 = 경험 하나. 머리글로 제목·분류·기관·기간·내용 열을 찾음
"""
import csv
import io
import re
from datetime import date, datetime

from .models import CATEGORIES

SPREADSHEET_EXT = {"xlsx", "xlsm", "xls", "csv"}
ALLOWED_EXT = {"docx", "pdf", "txt", "md"} | SPREADSHEET_EXT

HEADER_RE = re.compile(
    r"^\s*(#{1,4}\s+.+|\[.{2,60}\]\s*.*|【.{2,60}】.*|[■●◆▶◼︎□○◇►▪]\s*.{2,80}|\d{1,2}[\.\)]\s+.{2,60}|"
    r"(경험|활동|프로젝트|인턴|Experience)\s*\d+\s*[:.\-].*)$")
PERIOD_RE = re.compile(
    r"(\d{4}\s*[.\-/년]\s*\d{1,2}\s*월?)\s*[~\-–—]\s*(\d{4}\s*[.\-/년]\s*\d{1,2}\s*월?|현재|진행\s*중)")

CATEGORY_HINTS = [
    ("인턴·실무", ["인턴", "intern", "현장실습", "실습", "실무", "근무", "재직", "계약직"]),
    ("공모전·수상", ["공모전", "수상", "대상", "최우수", "우수상", "장려상", "경진대회", "대회", "논문"]),
    ("해외경험", ["교환학생", "어학연수", "워킹홀리데이", "해외봉사", "해외 인턴"]),
    ("대외활동", ["서포터즈", "기자단", "대외활동", "홍보대사", "앰버서더"]),
    ("동아리·학회", ["동아리", "학회", "소모임"]),
    ("프로젝트", ["프로젝트", "project", "팀플", "캡스톤"]),
    ("아르바이트", ["아르바이트", "알바", "파트타임"]),
    ("교육·수료", ["교육", "수료", "부트캠프", "아카데미", "과정"]),
    ("자격증·어학", ["자격증", "토익", "오픽", "toeic", "opic", "hsk", "jlpt", "취득"]),
    ("봉사", ["봉사"]),
]


def allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def extract_text(filename: str, data: bytes) -> str:
    ext = filename.rsplit(".", 1)[1].lower()
    if ext == "docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        lines = []
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                lines.append("")
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            lines.append(f"## {text}" if style.startswith(("heading", "제목", "title")) else text)
        for table in doc.tables:  # 표로 정리한 경험도 읽기
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(dict.fromkeys(cells)))
            lines.append("")
        return "\n".join(lines)
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def guess_category(title: str, body: str = "") -> str:
    """제목에서 먼저 찾고, 없으면 본문에서 찾습니다."""
    for text in (title, body):
        low = (text or "").lower()
        for cat, words in CATEGORY_HINTS:
            if any(w in low for w in words):
                return cat
    return "기타"


def _clean_header(line: str) -> str:
    line = re.sub(r"^\s*(#{1,4}|[■●◆▶◼︎□○◇►▪]|\d{1,2}[\.\)])\s*", "", line).strip()
    return line.strip("[]【】 ").strip()


def split_experiences(text: str) -> list[dict]:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    blocks: list[dict] = []
    cur = None
    for ln in lines:
        if HEADER_RE.match(ln) and len(ln.strip()) <= 90:
            if cur and (cur["body"] or cur["title"]):
                blocks.append(cur)
            cur = {"title": _clean_header(ln), "body": []}
        else:
            if cur is None:
                cur = {"title": "", "body": []}
            cur["body"].append(ln)
    if cur:
        blocks.append(cur)

    # 머리글이 거의 없으면 빈 줄 기준으로 나누기
    if len([b for b in blocks if b["title"]]) < 2:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        blocks, buf = [], ""
        for p in paras:
            buf = f"{buf}\n{p}".strip() if buf else p
            if len(buf) >= 60:
                first, _, rest = buf.partition("\n")
                blocks.append({"title": first[:80] if rest else "", "body": [rest or buf]})
                buf = ""
        if buf:
            blocks.append({"title": "", "body": [buf]})

    results = []
    for b in blocks:
        body = "\n".join(b["body"]).strip()
        title = b["title"] or (body.split("\n", 1)[0][:60] if body else "")
        if len(body) + len(title) < 15:
            continue
        joined = f"{title}\n{body}"
        m = PERIOD_RE.search(joined)
        period = f"{m.group(1)} ~ {m.group(2)}".replace(" ", "") if m else ""
        cat = guess_category(title, body)
        results.append({"title": title[:200] or "이름 없는 경험", "content": body or title, "period": period,
                        "category": cat if cat in CATEGORIES else "기타"})
    return results


# ── 엑셀·CSV ─────────────────────────────────────────────────────────

# 머리글 단어 → 경험 필드. 앞에 있는 단어일수록 먼저 찾습니다.
COLUMN_HINTS = {
    "title": ["경험명", "활동명", "프로젝트명", "제목", "경험", "활동", "항목", "이름", "title", "experience", "activity"],
    "category": ["분류", "구분", "유형", "카테고리", "종류", "category", "type"],
    "organization": ["기관", "회사", "소속", "단체", "주최", "주관", "organization", "company"],
    "period": ["기간", "일자", "날짜", "시기", "period", "date"],
    "start": ["시작", "start"],
    "end": ["종료", "끝", "end"],
    "duration": ["개월", "기간(월)", "duration"],
}
# 글 항목 열 → 경험의 어느 칸에 넣을지. 위에서부터 먼저 맞는 칸으로 들어갑니다.
TEXT_FIELD_HINTS = {
    "keywords": ["key-word", "keyword", "키워드", "해시태그", "tag"],
    "reflection": ["느낀", "배운", "소감", "교훈", "회고", "lesson"],
    "strengths": ["강약", "강점", "약점", "장점", "단점", "성과", "결과", "역량", "strength", "result"],
    "role": ["역할", "담당", "업무", "role"],
    "content": ["내용", "상세", "설명", "행동", "상황", "과제", "인원", "팀원", "비고", "메모", "star", "content",
                "description", "detail", "note"],
}
CONTENT_HINTS = [w for ws in TEXT_FIELD_HINTS.values() for w in ws]
# 경험 내용이 아닌 열(순번 등)
IGNORE_HINTS = ["순번", "번호", "no.", "no", "#"]


def is_spreadsheet(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in SPREADSHEET_EXT


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y.%m")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _read_rows(filename: str, data: bytes) -> list[tuple[str, list[list[str]]]]:
    """[(시트 이름, 행 목록)] — 각 행은 문자열 리스트. 빈 행은 뺍니다."""
    ext = filename.rsplit(".", 1)[1].lower()
    sheets = []
    if ext in ("xlsx", "xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            sheets.append((ws.title, [[_cell_str(v) for v in row] for row in ws.iter_rows(values_only=True)]))
        wb.close()
    elif ext == "xls":
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        for sh in book.sheets():
            rows = []
            for r in range(sh.nrows):
                row = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        row.append(_cell_str(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)))
                    else:
                        row.append(_cell_str(cell.value))
                rows.append(row)
            sheets.append((sh.name, rows))
    else:  # csv
        text = None
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("utf-8", errors="ignore")
        sheets.append(("CSV", [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]))
    return [(name, [r for r in rows if any(r)]) for name, rows in sheets]


def _match_header(cell: str, words: list[str]) -> bool:
    low = cell.lower().replace(" ", "")
    return any(w in low for w in words)


ALL_HEADER_WORDS = [w for ws in COLUMN_HINTS.values() for w in ws] + CONTENT_HINTS


def _is_ignored(cell: str) -> bool:
    return cell.lower().replace(" ", "") in IGNORE_HINTS


def _is_header_row(row: list[str]) -> bool:
    """짧은 칸 가운데 머리글 단어가 3개 이상(칸이 적으면 2개 이상)이면 머리글 행.

    한 시트에 표가 여러 개 쌓여 있어도(예: 아르바이트 표 아래 대외활동 표) 표마다 머리글을 다시 찾습니다.
    """
    filled = [c for c in row if c]
    if not filled or any(len(c) > 20 for c in filled):
        return False
    hits = sum(1 for c in filled if _match_header(c, ALL_HEADER_WORDS) or _is_ignored(c))
    return hits >= min(3, len(filled)) and hits >= 2


def _column_map(header: list[str]) -> dict:
    cols, used = {}, {j for j, h in enumerate(header) if h and _is_ignored(h)}
    for field in ("title", "category", "organization", "period", "start", "end", "duration"):
        for j, h in enumerate(header):
            if j not in used and h and _match_header(h, COLUMN_HINTS[field]):
                cols[field] = j
                used.add(j)
                break
    # 글 항목 열: 칸(field)별로 열 번호 목록
    cols["text"] = {f: [] for f in TEXT_FIELD_HINTS}
    for j, h in enumerate(header):
        if j in used or not h:
            continue
        field = next((f for f, words in TEXT_FIELD_HINTS.items() if _match_header(h, words)), "content")
        cols["text"][field].append(j)
    return cols


def _make_item(title, period, category, organization, texts: dict):
    """texts: {"role": ..., "content": ..., "strengths": ..., "keywords": ..., "reflection": ...}"""
    title = re.sub(r"\s+", " ", title or "").strip()
    organization = re.sub(r"\s+", " ", organization or "").strip()
    category = re.sub(r"\s+", " ", category or "").strip()
    texts = {k: (v or "").strip() for k, v in texts.items()}
    body = "\n".join(v for v in texts.values() if v)
    if not title:
        # 제목 열이 없으면 '기관 · 종류'를 제목으로 (예: 'LG 호주 법인 · 인턴(BOP CE)')
        title = " · ".join(x for x in (organization, category) if x) or body.split("\n", 1)[0][:60]
    if len(title) < 2 or (not body and len(title) < 4 and not category):
        return None
    if not period:
        m = PERIOD_RE.search(f"{title}\n{body}")
        period = f"{m.group(1)} ~ {m.group(2)}".replace(" ", "") if m else ""
    # 직접 적은 종류(예: '봉사장학생', '논문')를 먼저 보고, 못 정하면 제목·내용으로 추정
    cat = category if category in CATEGORIES else guess_category(category)
    if cat == "기타":
        cat = guess_category(title, body)
    if category and category not in CATEGORIES:  # 원래 적은 종류는 내용에 남겨 분석에 활용
        texts["content"] = f"종류: {category}\n{texts.get('content', '')}".strip()
    item = {"title": title[:200], "period": period[:60], "category": cat if cat in CATEGORIES else "기타",
            "organization": organization[:120]}
    item.update({f: texts.get(f, "") for f in TEXT_FIELD_HINTS})
    return item


def parse_spreadsheet(filename: str, data: bytes) -> tuple[str, list[dict]]:
    """(분석용 전체 텍스트, 경험 목록)을 돌려줍니다. 모든 시트·시트 안의 모든 표를 읽습니다."""
    items, text_lines = [], []
    for _sheet, rows in _read_rows(filename, data):
        header, cols = None, None
        for row in rows:
            if _is_header_row(row):
                header, cols = row, _column_map(row)
                text_lines.append(" | ".join(c for c in row if c))
                continue
            cells = [c for c in row if c]
            text_lines.append(" | ".join(cells))
            if header is None:
                # 머리글 없는 시트: 첫 칸 = 제목, 나머지 = 내용 (칸 하나짜리 메모 행은 건너뜀)
                if len(cells) >= 2 or len(cells[0]) >= 15:
                    items.append(_make_item(cells[0][:80], "", "", "",
                                            {"content": "\n".join(cells[1:]) or cells[0]}))
                continue

            def get(j, row=row):
                return row[j] if j is not None and j < len(row) else ""
            texts = {}
            for field, idxs in cols["text"].items():
                vals = [(header[j], get(j)) for j in idxs if get(j)]
                # 같은 칸에 열이 여러 개면 '머리글: 값'으로 구분해 이어 붙임
                texts[field] = "\n".join(f"{h}: {v}" if len(idxs) > 1 else v for h, v in vals)
            period = get(cols.get("period"))
            if not period and (get(cols.get("start")) or get(cols.get("end"))):
                period = f"{get(cols.get('start'))} ~ {get(cols.get('end')) or '현재'}"
            if get(cols.get("duration")) and get(cols.get("duration")) not in period:
                period = f"{period} ({get(cols.get('duration'))})".strip()
            items.append(_make_item(get(cols.get("title")), period, get(cols.get("category")),
                                    get(cols.get("organization")), texts))
    return "\n".join(text_lines), [it for it in items if it]
