"""경험 구조화: 핵심 역량 추천 · STAR 빈 칸 질문 · AI 초안 검증 · 경험 활용 내역.

원칙: 사용자가 적은 글에 근거가 있는 것만 추천하고, 성과·수치는 만들지 않습니다.
정보가 비어 있으면 채워 달라고 '질문'으로 요청합니다.
"""
import re

# 역량 이름 → 내 글에서 찾는 단서
COMPETENCIES = {
    "글로벌 커뮤니케이션": ["영어", "중국어", "일본어", "해외", "바이어", "현지", "외국인", "통역", "번역", "영문", "글로벌"],
    "무역 실무": ["수출", "수입", "선적", "통관", "인코텀즈", "신용장", "오더", "원산지", "b/l", "포워딩"],
    "고객 응대": ["고객", "응대", "cs", "클레임", "컴플레인", "상담", "문의"],
    "협업·조율": ["협업", "조율", "소통", "회의", "팀원", "부서", "협의", "공유"],
    "문제 해결": ["문제", "해결", "개선", "원인", "대안", "극복", "보완"],
    "데이터 분석": ["엑셀", "데이터", "분석", "통계", "리포트", "피벗", "vlookup", "sql", "파이썬"],
    "기획·실행력": ["기획", "제안", "실행", "추진", "설계", "구상", "도입"],
    "리더십": ["팀장", "리더", "회장", "대표", "이끌", "총괄"],
    "꼼꼼함·문서 관리": ["서류", "문서", "정리", "검수", "체크", "기록", "회의록", "관리"],
    "책임감·성실함": ["책임", "마감", "끝까지", "성실", "꾸준", "기한"],
}

STAR_QUESTIONS = {
    "star_situation": "언제·어디서·어떤 상황이었나요? (예: 인턴 2개월 차, 호주 법인 영업팀에서)",
    "star_task": "맡은 과제나 해결해야 했던 문제는 무엇이었나요?",
    "star_action": "내가 직접 한 행동을 순서대로 적어 주세요. 팀이 한 일과 내가 한 일을 나눠 적으면 좋아요.",
    "star_result": "결과는 어땠나요? 바뀐 점이나 받은 피드백을 적어 주세요.",
}
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
    """비어 있는 STAR 칸과 채울 때 도움이 되는 질문. 결과에 숫자가 없으면 있을 때만 적으라고 안내."""
    gaps = [{"field": f, "label": exp.TEXT_LABELS[f], "question": q}
            for f, q in STAR_QUESTIONS.items() if not (getattr(exp, f) or "").strip()]
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
    """이 경험이 쓰인 곳: 근거로 쓰인 공고(요건 수) · 답변에 쓴 자소서 문항. 저장된 분석·답변에서 바로 계산."""
    from ..applications.models import ApplicationRecord
    from ..applications.services import used_experiences
    from ..core.scoping import owned
    from .models import PostingAnalysis
    postings = []
    for pa in owned(PostingAnalysis).order_by(PostingAnalysis.created_at.desc()).all():
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
    for q in owned(InterviewQuestion).order_by(InterviewQuestion.created_at.desc()).all():
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
