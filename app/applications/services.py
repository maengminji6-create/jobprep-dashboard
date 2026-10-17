"""자소서 보관함 도우미: 폼 읽기, 답변에 쓴 내 경험 찾기."""
import json
import re

# 경험 이름에 흔히 들어가 '어떤 경험인지' 구분하지 못하는 단어
GENERIC = set("인턴 단기 온라인 알바 아르바이트 프로젝트 디저트 카페 교육 과정 봉사 봉사장학생 대학교 대학 "
              "1기 2기 학원 편의점 학생 활동 동아리 대회 팀 부트캠프 인천대".split())


def read_qa(form) -> list[dict]:
    """폼의 q[] / limit[] / a[] 를 문항 목록으로. 문항·답변이 모두 빈 줄은 버림."""
    qs, limits, answers = form.getlist("q"), form.getlist("limit"), form.getlist("a")
    out = []
    for i, q in enumerate(qs):
        a = answers[i] if i < len(answers) else ""
        lim = limits[i] if i < len(limits) else ""
        if q.strip() or a.strip():
            out.append({"q": q.strip()[:500], "limit": re.sub(r"\D", "", lim)[:5], "a": a.strip()[:10000]})
    return out


def dump_qa(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)


def _tokens(exp) -> list[str]:
    raw = re.split(r"[\s·/()\[\],]+", f"{exp.title} {exp.organization or ''}")
    return [t for t in dict.fromkeys(raw) if len(t) >= 2 and t not in GENERIC]


def used_experiences(text: str, exps: list) -> list:
    """답변 글에 이름(기관·활동명)이 나오는 내 경험."""
    low = (text or "").lower()
    return [e for e in exps if any(t.lower() in low for t in _tokens(e))]
