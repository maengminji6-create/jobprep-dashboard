"""면접 준비: 예상 질문 만들기(규칙 · 근거 포함) · 답변 점검 · AI 질문 검증.

질문마다 근거를 붙입니다 — 공고 요건·담당 업무 문장, 또는 그 질문을 받을 만한 내 경험.
답변 점검은 답변에 실제로 있는 것만 봅니다(길이 · 결과 · 내 행동 · 경험 연결).
"""
import re

ONE_MINUTE = (250, 450)  # 1분 답변 분량(공백 포함 글자 수, 대략)
ACTION_WORDS = ("했습니다", "했고", "했다", "만들", "정리", "제안", "조율", "분석", "개선", "응대", "관리", "진행", "주도", "작성")
RESULT_WORDS = ("결과", "덕분", "그래서", "줄었", "늘었", "개선", "달성", "단축", "피드백", "배웠", "성과")


def _q(category, question, basis="", exp_ids=None):
    return {"category": category, "question": question, "basis": basis, "exp_ids": exp_ids or []}


def rule_questions(company: str, role_name: str, posting=None, exps: list | None = None,
                   analyses: dict | None = None) -> list[dict]:
    """공고(있으면)의 요건·업무와 내 경험으로 예상 질문. 중복 질문은 뺌."""
    exps, analyses = exps or [], analyses or {}
    out = []
    r = posting.result if posting is not None else {}
    req = r.get("requirements") or {}
    for it in [i for i in req.get("items", []) if i["kind"] == "required"][:3] + \
              [i for i in req.get("items", []) if i["kind"] == "preferred"][:1]:
        ids = [ev["experience_id"] for ev in it.get("evidence", [])[:2]]
        out.append(_q("직무 역량", f"공고에 '{it['text']}'라고 되어 있는데, 이와 관련해 직접 해 본 경험이 있나요?",
                      f"공고 {'자격요건' if it['kind'] == 'required' else '우대사항'}: {it['text']}", ids))
    for duty in (r.get("structure") or {}).get("duties", [])[:2]:
        d = duty.strip(" -•·")
        if len(d) >= 6:
            out.append(_q("직무 역량", f"입사하면 '{d}' 업무를 맡게 됩니다. 어떻게 해 나갈 건가요?", f"공고 담당 업무: {d}"))

    support = [s["id"] for s in req.get("support", [])[:2]]
    by_id = {e.id: e for e in exps}
    picked = [by_id[i] for i in support if i in by_id]
    if len(picked) < 2:  # 공고가 없거나 근거 경험이 적으면 면접·자소서에 쓰기 좋은 경험
        ranked = sorted(exps, key=lambda e: max((analyses.get(e.id) or {}).get("usage", {"x": 0}).values()), reverse=True)
        picked += [e for e in ranked if e not in picked][:2 - len(picked)]
    for e in picked:
        out.append(_q("경험", f"'{e.title}'에서 맡은 역할과 가장 어려웠던 점, 그리고 결과를 말씀해 주세요.", f"내 경험: {e.title}", [e.id]))

    tough = sorted(exps, key=lambda e: (analyses.get(e.id) or {}).get("usage", {}).get("interview", 0), reverse=True)
    tough = [e for e in tough if (analyses.get(e.id) or {}).get("usage", {}).get("interview", 0) > 0][:1]
    for e in tough:
        out.append(_q("문제 해결", f"'{e.title}'에서 갈등이나 예상하지 못한 문제를 어떻게 해결했나요?",
                      f"내 경험: {e.title}(어려움·갈등을 적은 경험)", [e.id]))
    out.append(_q("문제 해결", "업무 중 예상하지 못한 문제가 생겼을 때 해결한 경험을 말씀해 주세요.", "자주 나오는 질문"))

    name = company or "우리 회사"
    out.append(_q("지원 동기", f"{name}에 지원한 이유는 무엇인가요?", "자주 나오는 질문"))
    out.append(_q("지원 동기", f"입사 후 {role_name} 직무에서 이루고 싶은 목표는 무엇인가요?", "자주 나오는 질문"))
    seen, uniq = set(), []
    for q in out:
        if q["question"] not in seen:
            seen.add(q["question"])
            uniq.append(q)
    return uniq


def check_answer(answer: str, linked_exps: list) -> dict:
    """답변 구성 점검(규칙). 답변에 있는 것만 보고, 없는 것은 '있다면 넣어 보라'고만 안내."""
    text = (answer or "").strip()
    n = len(text.replace("\n", ""))
    items = []
    if not text:
        return {"length": 0, "items": [{"ok": False, "text": "아직 답변이 없어요. 추천 경험의 STAR 뼈대로 시작해 보세요."}]}
    lo, hi = ONE_MINUTE
    items.append({"ok": lo <= n <= hi, "text": f"길이 {n}자 · 1분 답변은 대략 {lo}~{hi}자예요."
                  + (" 조금 더 구체적으로 말해 보세요." if n < lo else (" 핵심만 남겨 줄여 보세요." if n > hi else ""))})
    first = re.split(r"(?<=[.!?。])\s+", text)[0]
    items.append({"ok": len(first) <= 80, "text": "첫 문장에 결론(무엇을 했고 무엇을 배웠는지)을 먼저 말하면 좋아요."
                  if len(first) > 80 else "첫 문장이 짧고 분명해요."})
    has_action = any(w in text for w in ACTION_WORDS)
    items.append({"ok": has_action, "text": "내가 직접 한 행동이 드러나요." if has_action
                  else "'제가 ~했습니다'처럼 내가 한 행동을 넣어 보세요."})
    has_result = any(w in text for w in RESULT_WORDS) or bool(re.search(r"\d", text))
    items.append({"ok": has_result, "text": "결과·배운 점이 들어 있어요." if has_result
                  else "결과나 배운 점이 없어요. 실제로 있었던 결과가 있다면 덧붙이세요(없는 숫자는 만들지 마세요)."})
    if linked_exps:
        named = [e.title for e in linked_exps if any(t in text for t in re.split(r"[\s·()/]+", e.title) if len(t) >= 2)]
        items.append({"ok": bool(named), "text": f"경험({', '.join(named)})이 답변에 드러나요." if named
                      else "고른 경험의 이름이나 상황이 답변에 드러나지 않아요. 어떤 경험인지 먼저 밝혀 주세요."})
    return {"length": n, "items": items}


def check_ai_questions(items: list[dict], source: str) -> list[dict]:
    """AI 질문 중 근거(basis)가 공고·경험 글에 실제로 있는 것만 남김(띄어쓰기·문장부호 무시)."""
    from ..interview.models import CATEGORIES
    norm = lambda s: re.sub(r"[\s.,·\"'“”‘’()]", "", (s or "").lower())  # noqa: E731
    src = norm(source)
    out = []
    for i in items:
        basis = (i.get("basis") or "").strip()
        if not i.get("question") or len(norm(basis)) < 4 or norm(basis) not in src:
            continue
        out.append({"category": i.get("category") if i.get("category") in CATEGORIES else "기타",
                    "question": i["question"][:500], "basis": basis[:300], "exp_ids": []})
    return out[:8]
