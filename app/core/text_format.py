"""긴 경험 글을 읽기 좋은 블록으로 나눕니다(이력 PDF용).

사용자가 적은 형식을 그대로 살려 구조만 알아봅니다.
- 빈 줄 → 문단 나눔
- "- ", "• ", "· " 로 시작 → 글머리표 목록
- "1. ", "2) " 로 시작 → 번호 목록(적은 번호 유지)
- "<제목>", "<제목>/" 한 줄 → 소제목. 같은 제목이 다시 나오면("/<제목>") 닫는 표시로 보고 숨김
- "강점: …", "팀장의 역할: …" 처럼 짧은 머리말 + 콜론(또는 세미콜론) → 머리말을 굵게
"""
import re

_BULLET = re.compile(r"^\s*[-•·▪*]\s+(.+)$")
_NUMBER = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")
_HEADING = re.compile(r"^\s*/?<\s*/?\s*([^<>]+?)\s*/?\s*>\s*/?\s*$")
_LEAD = re.compile(r"^([^:：;\n]{1,20}?)\s*[:：;]\s+(.+)$", re.S)


def _lead(text: str) -> dict:
    """{"lead": 머리말 또는 None, "text": 나머지}. 주소(https:)·시각(10:30)은 머리말로 보지 않음."""
    m = _LEAD.match(text.strip())
    if m and not re.search(r"https?$|\d$", m.group(1)):
        return {"lead": m.group(1).strip(), "text": m.group(2).strip()}
    return {"lead": None, "text": text.strip()}


def text_blocks(text: str | None) -> list[dict]:
    """[{"kind": "p", "lines": [...]}, {"kind": "ul"/"ol", "items": [...]}, {"kind": "h", "text": ...}]"""
    blocks: list[dict] = []
    para: list[dict] = []
    headings: set[str] = set()

    def close_para():
        if para:
            blocks.append({"kind": "p", "lines": list(para)})
            para.clear()

    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            close_para()
            continue
        if m := _HEADING.match(line):
            close_para()
            if m.group(1) not in headings:  # 두 번째로 나오면 닫는 표시
                headings.add(m.group(1))
                blocks.append({"kind": "h", "text": m.group(1)})
        elif m := _BULLET.match(line):
            close_para()
            if not blocks or blocks[-1]["kind"] != "ul":
                blocks.append({"kind": "ul", "items": []})
            blocks[-1]["items"].append(_lead(m.group(1)))
        elif m := _NUMBER.match(line):
            close_para()
            if not blocks or blocks[-1]["kind"] != "ol":
                blocks.append({"kind": "ol", "items": []})
            blocks[-1]["items"].append({"n": int(m.group(1)), **_lead(m.group(2))})
        else:
            para.append(_lead(line))
    close_para()
    return blocks
