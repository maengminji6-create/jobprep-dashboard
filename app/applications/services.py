"""자소서 보관함 도우미: 폼 읽기, 답변에 쓴 내 경험 찾기."""
import json
import re

# 경험 이름에 흔히 들어가 '어떤 경험인지' 구분하지 못하는 단어
GENERIC = set("인턴 단기 온라인 알바 아르바이트 프로젝트 디저트 카페 교육 과정 봉사 봉사장학생 대학교 대학 "
              "1기 2기 학원 편의점 학생 활동 동아리 대회 팀 부트캠프 인천대".split())


def read_qa(form) -> list[dict]:
    """폼의 q[] / limit[] / a[] / exps[](문항에 쓴 경험 id, 쉼표) 를 문항 목록으로. 문항·답변이 모두 빈 줄은 버림."""
    qs, limits, answers, exps = form.getlist("q"), form.getlist("limit"), form.getlist("a"), form.getlist("exps")
    out = []
    for i, q in enumerate(qs):
        a = answers[i] if i < len(answers) else ""
        lim = limits[i] if i < len(limits) else ""
        ids = [int(x) for x in (exps[i] if i < len(exps) else "").split(",") if x.strip().isdigit()][:10]
        if q.strip() or a.strip():
            out.append({"q": q.strip()[:500], "limit": re.sub(r"\D", "", lim)[:5], "a": a.strip()[:10000],
                        "exps": list(dict.fromkeys(ids))})
    return out


def dump_qa(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)


def _tokens(exp) -> list[str]:
    raw = re.split(r"[\s·/()\[\],]+", f"{exp.title} {exp.organization or ''}")
    return [t for t in dict.fromkeys(raw) if len(t) >= 2 and t not in GENERIC]


def used_experiences(text: str, exps: list, chosen: list[int] | None = None) -> list:
    """이 답변에 쓴 내 경험: 직접 고른 경험(chosen) + 답변 글에 이름(기관·활동명)이 나오는 경험."""
    low = (text or "").lower()
    picked = set(chosen or [])
    return [e for e in exps if e.id in picked or any(t.lower() in low for t in _tokens(e))]


# ── 자소서 작성 보조: 문항 유형 · 경험 추천 · STAR 뼈대 · 버전 ────────────────────

QUESTION_TYPES = [  # (유형 이름 = experiences.analyzer.ESSAY_QUESTIONS 이름, 문항 단서)
    ("지원동기·입사 후 포부", ["지원 동기", "지원동기", "지원한 이유", "입사 후", "포부", "왜 우리", "비전", "목표"]),
    ("협업·갈등 해결", ["협업", "갈등", "팀", "동료", "소통", "의견", "조율", "함께"]),
    ("도전·성장 경험", ["도전", "실패", "극복", "성장", "어려움", "한계", "새로운", "변화"]),
    ("직무역량·전문성", ["역량", "전문성", "강점", "직무", "경험", "준비", "노력", "능력"]),
]


def question_type(question: str) -> str:
    q = (question or "").replace(" ", "")
    for name, clues in QUESTION_TYPES:
        if any(c.replace(" ", "") in q for c in clues):
            return name
    return "직무역량·전문성"


def suggest_for_question(question: str, exps: list, analyses: dict, posting=None, limit: int = 4) -> dict:
    """문항에 맞는 내 경험 추천. 점수 근거(이유)를 함께 돌려주고, 근거가 하나도 없는 경험은 추천하지 않음."""
    from ..experiences.analyzer import essay_question_for
    qtype = question_type(question)
    support = {}
    if posting is not None:
        for sp in (posting.result.get("requirements") or {}).get("support", []):
            support[sp.get("id")] = sp
    out = []
    for e in exps:
        a = analyses[e.id]
        score, reasons = 0, []
        if essay_question_for(a) == qtype:
            score += 30
            reasons.append(f"'{qtype}' 문항에 맞는 경험이에요")
        sp = support.get(e.id)
        if sp and (sp.get("met") or sp.get("check")):
            score += 20 * sp.get("met", 0) + 8 * sp.get("check", 0)
            reasons.append(f"이 공고 요건 {sp.get('met', 0)}개를 충족하는 근거예요")
        filled = [f for f in e.STAR_FIELDS if (getattr(e, f) or "").strip()]
        if len(filled) >= 3:
            score += 10
            reasons.append("STAR로 정리돼 있어 바로 쓸 수 있어요")
        best_usage = max(a["usage"].values()) if a["usage"] else 0
        score += best_usage * 0.1
        if not reasons:
            continue
        out.append({"id": e.id, "title": e.title, "category": e.category, "score": round(score),
                    "reasons": reasons, "star_filled": len(filled), "outline": star_outline(e)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return {"type": qtype, "items": out[:limit]}


def star_outline(exp) -> str:
    """답변 뼈대: 경험의 STAR 칸(사용자가 쓴 글) 그대로. 빈 칸은 무엇을 쓸지 괄호로 남김(내용을 지어내지 않음)."""
    labels = [("star_situation", "상황", "상황을"), ("star_task", "과제", "과제를"), ("star_action", "행동", "행동을"),
              ("star_result", "결과", "결과를")]
    fallback = {"star_situation": "", "star_task": "", "star_action": exp.role or "", "star_result": exp.strengths or ""}
    lines = [f"[{exp.title}]"]
    for f, label, obj in labels:
        text = (getattr(exp, f) or "").strip() or fallback[f].strip()
        lines.append(f"{label}: {text}" if text else f"{label}: (여기에 {obj} 적어 주세요)")
    return "\n".join(lines)


def check_answer_draft(draft: str, source: str) -> tuple[str, list[str]]:
    """AI 답변 초안 점검: 원문(고른 경험·문항·공고)에 없는 숫자가 든 문장은 빼고 알려 줌."""
    src_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", source or ""))
    kept, dropped = [], []
    for sent in re.split(r"(?<=[.!?。다요])\s+", draft or ""):
        if not sent.strip():
            continue
        if any(n not in src_numbers for n in re.findall(r"\d+(?:[.,]\d+)?", sent)):
            dropped.append(sent.strip())
        else:
            kept.append(sent.strip())
    notes = [f"원문에 없는 숫자가 있어 뺀 문장: “{d[:60]}”" for d in dropped[:5]]
    return " ".join(kept), notes


def save_version(rec) -> bool:
    """지금 문항·답변을 이전 버전으로 남김(바로 전 버전과 같으면 남기지 않음). commit 은 호출한 쪽에서."""
    from ..core.scoping import create_owned
    from .models import ApplicationVersion
    if not rec.qa or not any((i.get("a") or "").strip() for i in rec.qa):
        return False
    last = rec.versions[0] if rec.versions else None
    if last and last.qa_json == rec.qa_json:
        return False
    create_owned(ApplicationVersion, application_id=rec.id, qa_json=rec.qa_json, total_chars=rec.total_chars)
    return True


# ── 지원 상태 연동: 공고(공고 매칭) ↔ 지원 기록(자소서 보관함) ─────────────────

def sync_from_application(rec) -> None:
    """지원 기록 상태를 바꾸면 연결된 공고도 같은 상태로(공고는 ★ 저장한 공고로 올라감)."""
    from ..core.scoping import owned
    from ..experiences.models import PostingAnalysis
    if not rec.posting_id:
        return
    pa = owned(PostingAnalysis).filter(PostingAnalysis.id == rec.posting_id).first()
    if pa:
        pa.status = rec.status
        _mark_saved(pa)


def sync_from_posting(pa) -> None:
    """공고 상태를 바꾸면 그 공고로 만든 지원 기록도 같은 상태로."""
    from ..core.scoping import owned
    from .models import ApplicationRecord
    for rec in owned(ApplicationRecord).filter(ApplicationRecord.posting_id == pa.id).all():
        rec.status = pa.status


def _mark_saved(pa) -> None:
    from datetime import datetime, timezone
    if not pa.is_saved:
        pa.is_saved = True
        pa.saved_at = datetime.now(timezone.utc)
