"""경험 구조화: 핵심 역량 추천 · STAR 빈 칸 질문 · AI 초안 검증 · 경험 활용 내역.

원칙: 사용자가 적은 글에 근거가 있는 것만 추천하고, 성과·수치는 만들지 않습니다.
정보가 비어 있으면 채워 달라고 '질문'으로 요청합니다.
"""
import re

from ..core.competencies import CLUES as COMPETENCIES  # 역량 이름 → 내 글에서 찾는 단서(공통 기준표)

STAR_QUESTIONS = {
    "star_situation": "언제·어디서·어떤 상황이었나요? 어떤 문제가 있었나요? (예: 인턴 2개월 차, 호주 법인 영업팀에서)",
    "star_task": "내가 맡은 역할과 해결해야 했던 과제·목표는 무엇이었나요?",
    "star_action": "내가 직접 한 행동과 해결 과정을 순서대로 적어 주세요. 팀이 한 일과 내가 한 일을 나눠 적으면 좋아요.",
    "star_result": "결과는 어땠나요? 바뀐 점이나 받은 피드백을 적어 주세요.",
}
SELF_WORDS = ("내가", "제가", "직접", "혼자", "스스로", "담당")
TEAM_WORDS = ("우리", "팀원들", "팀이", "함께")
NUMBER = re.compile(r"\d")


def _sentences(text: str) -> list[str]:
    out = []
    for ln in (text or "").splitlines():
        for part in re.split(r"(?<=[.!?。])\s+", ln):
            part = part.strip(" -•·")
            if len(part) >= 4:
                out.append(part)
    return out


def suggest_competencies(exp, limit: int = 6) -> list[dict]:
    """[{"name", "words": 내 글에서 찾은 단서, "evidence": 그 단서가 든 내 문장}] — 단서가 많은 순. 이미 단 태그는 뺌."""
    have = set(exp.competency_list)
    base = "\n".join(getattr(exp, f) or "" for f in exp.TEXT_FIELDS)
    sents = _sentences(f"{exp.title}\n{base}")
    out = []
    for name, words in COMPETENCIES.items():
        if name in have:
            continue
        found = [w for w in words if any(w in s.lower() for s in sents)]
        if not found:
            continue
        evidence = next((s for s in sents if any(w in s.lower() for w in found)), "")
        out.append({"name": name, "words": found[:4], "evidence": evidence[:160]})
    out.sort(key=lambda x: len(x["words"]), reverse=True)
    return out[:limit]


def star_gaps(exp) -> list[dict]:
    """비어 있거나 약한 STAR 칸과 채울 때 도움이 되는 질문(규칙 기반, 내용을 지어 주지 않음).
    결과에 숫자가 없으면 '실제로 잰 값이 있을 때만' 적으라고 안내."""
    gaps = [{"field": f, "label": exp.TEXT_LABELS[f], "question": q}
            for f, q in STAR_QUESTIONS.items() if not (getattr(exp, f) or "").strip()]
    notes = " ".join(getattr(exp, f) or "" for f in ("role", "content", "strengths", "reflection")).strip()
    if exp.star_filled == 0 and notes:
        gaps.insert(0, {"field": "star_situation", "label": "자유 기록 → STAR",
                        "question": "자유 기록에 적은 글이 있어요. 그 글을 상황·과제·행동·결과로 나눠 옮겨 보세요."})
    action = (exp.star_action or "").strip()
    if action and len(action) < 30:
        gaps.append({"field": "star_action", "label": exp.TEXT_LABELS["star_action"],
                     "question": "행동이 짧아요. 내가 직접 한 일을 순서대로 2~3가지 적어 주세요."})
    elif action and any(w in action for w in TEAM_WORDS) and not any(w in action for w in SELF_WORDS):
        gaps.append({"field": "star_action", "label": exp.TEXT_LABELS["star_action"],
                     "question": "팀이 한 일만 보여요. 그중 내가 맡아서 한 일이 무엇인지 나눠 적어 주세요."})
    result = (exp.star_result or "").strip()
    if result and not NUMBER.search(result):
        gaps.append({"field": "star_result", "label": exp.TEXT_LABELS["star_result"],
                     "question": "결과에 숫자가 없어요. 실제로 잰 값(%·건수·기간·금액)이 있을 때만 적어 주세요. 없다면 그대로 두세요."})
    return gaps


def check_draft(draft: dict, source: str) -> tuple[dict, list[str]]:
    """AI가 만든 STAR 초안 점검: 원문에 없는 숫자가 들어간 칸은 비우고 이유를 남김(성과·수치 지어내기 방지)."""
    src_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", source or ""))
    clean, notes = {}, []
    for f in STAR_QUESTIONS:
        text = (draft.get(f) or "").strip()
        new_numbers = [n for n in re.findall(r"\d+(?:[.,]\d+)?", text) if n not in src_numbers]
        if new_numbers:
            notes.append(f"{f}: 원문에 없는 숫자({', '.join(new_numbers[:3])})가 있어 이 칸은 비웠어요. 직접 적어 주세요.")
            text = ""
        clean[f] = text[:3000]
    return clean, notes


def experience_usage(exp) -> dict:
    """이 경험이 쓰인 곳: 근거로 쓰인 공고(요건 수) · 답변에 쓴 자소서 문항. 저장된 분석·답변에서 바로 계산.
    공고·면접은 쉬는 기능(LEGACY_FEATURES)이 꺼져 있으면 세지 않음(열 수 없는 화면으로 연결하지 않도록)."""
    from flask import current_app

    from ..applications.models import ApplicationRecord
    from ..applications.services import used_experiences
    from ..core.scoping import owned
    from .models import PostingAnalysis
    legacy = current_app.config["LEGACY_FEATURES"]
    postings = []
    for pa in owned(PostingAnalysis).order_by(PostingAnalysis.created_at.desc()).all() if legacy else []:
        r = pa.result
        support = next((s for s in (r.get("requirements") or {}).get("support", []) if s.get("id") == exp.id), None)
        recommended = any(x.get("id") == exp.id for x in r.get("recommendations", []))
        if support or recommended:
            postings.append({"id": pa.id, "name": pa.company or pa.title, "status": pa.status or "",
                             "met": support["met"] if support else 0, "items": (support or {}).get("items", [])[:3]})
    essays = []
    for rec in owned(ApplicationRecord).order_by(ApplicationRecord.created_at.desc()).all():
        for item in rec.qa:
            if exp in used_experiences(item.get("a", ""), [exp], item.get("exps")):
                essays.append({"id": rec.id, "company": rec.company, "question": item.get("q") or "문항"})
    from ..interview.models import InterviewQuestion, InterviewSession
    interviews = []
    for q in owned(InterviewQuestion).order_by(InterviewQuestion.created_at.desc()).all() if legacy else []:
        if exp.id in q.exp_id_list and (q.answer or "").strip():
            s = owned(InterviewSession).filter(InterviewSession.id == q.session_id).first()
            if s:
                interviews.append({"id": s.id, "title": s.title, "question": q.question})
    return {"postings": postings, "essays": essays, "interviews": interviews,
            "total": len(postings) + len(essays) + len(interviews)}


def check_ai_competencies(items: list[dict], source: str) -> list[dict]:
    """AI가 붙인 역량 근거가 내 글에 실제로 있는 문장일 때만 남김(띄어쓰기·문장부호 무시)."""
    norm = lambda s: re.sub(r"[\s.,·\"'“”‘’]", "", (s or "").lower())  # noqa: E731
    src = norm(source)
    return [{"name": i["name"][:40], "evidence": i["evidence"][:200]} for i in items
            if i.get("name") and len(norm(i.get("evidence"))) >= 4 and norm(i.get("evidence")) in src]
