"""AI 분석: B(경험 기반 역량) · C(진단 강점 × 경험 연결) · 통합 결과.

원칙: AI가 준 항목은 경험 원문에서 인용(quote)이 확인될 때만 남깁니다. 원문에 없는 숫자가 든 문장도 뺍니다.
진단 순위(결과지)와 경험 근거(인용 수·충분성)는 서로 다른 기준이라 하나의 점수로 합치지 않습니다.
"""
import json
import re

from flask import current_app

from ..core.competencies import COMPETENCY_NAMES
from ..core.scoping import create_owned, owned
from ..extensions import db
from ..integrations import ai_client
from .models import EVIDENCE_LEVELS, ExperienceAnalysis, StrengthLink

BATCH = 5  # AI 요청 한 번에 보내는 경험 수(무료 횟수를 아끼면서 응답 길이 안에 들어가는 양)
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _norm(s: str) -> str:
    return re.sub(r"[\s.,·\"'“”‘’()\[\]~\-]", "", (s or "").lower())


def _fields(exp) -> list[tuple[str, str]]:
    """(칸 이름, 글) — 인용을 찾는 곳. 지원자가 직접 쓴 칸만(분석기 키워드·태그 제외)."""
    out = [("경험 이름", exp.title or "")]
    out += [(exp.TEXT_LABELS[f], getattr(exp, f) or "") for f in exp.TEXT_FIELDS]
    return [(label, text) for label, text in out if text.strip()]


def locate(quote: str, exp) -> str | None:
    """인용이 들어 있는 칸 이름. 원문 어디에도 없으면 None."""
    q = _norm(quote)
    if len(q) < 4:
        return None
    return next((label for label, text in _fields(exp) if q in _norm(text)), None)


def _source(exp) -> str:
    return "\n".join(text for _label, text in _fields(exp))


def _new_numbers(text: str, source: str) -> bool:
    have = set(NUM.findall(source))
    return any(n not in have for n in NUM.findall(text or ""))


def _quoted_item(item: dict, exp, src: str) -> dict | None:
    field = locate(item.get("quote"), exp)
    if not field:
        return None
    text = (item.get("text") or "").strip()
    if not text or _new_numbers(text, src):  # 정리 문장에 원문에 없는 숫자 → 인용만 남김
        text = item["quote"].strip()
    return {"text": text[:300], "quote": item["quote"].strip()[:300], "field": field}


def clean_analysis(raw: dict, exp) -> dict:
    """AI 응답을 원문 근거로 거름. 근거가 없는 항목 수는 dropped 로 남겨 화면에 알림."""
    src = _source(exp)
    dropped = 0

    def keep(items, limit):
        nonlocal dropped
        out = []
        for it in items or []:
            c = _quoted_item(it, exp, src)
            if c:
                out.append(c)
            elif (it.get("quote") or "").strip():
                dropped += 1
        return out[:limit]

    actions = keep(raw.get("actions"), 4)
    results = keep(raw.get("results"), 3)
    ps = raw.get("problem_solving") or {}
    problem = _quoted_item(ps, exp, src) if (ps.get("quote") or "").strip() else None
    if (ps.get("quote") or "").strip() and not problem:
        dropped += 1

    comps: dict[str, list] = {}
    for c in raw.get("competencies") or []:
        field = locate(c.get("quote"), exp)
        if c.get("name") not in COMPETENCY_NAMES or not field:
            dropped += 1
            continue
        quotes = comps.setdefault(c["name"], [])
        if _norm(c["quote"]) not in {_norm(q["quote"]) for q in quotes}:
            quotes.append({"quote": c["quote"].strip()[:300], "field": field, "reason": (c.get("reason") or "")[:200]})
    competencies = [{"name": n, "quotes": qs[:3], "level": "충분" if len(qs) >= 2 else "보통"}
                    for n, qs in list(comps.items())[:5]]

    summary = (raw.get("summary") or "").strip()
    if _new_numbers(summary, src):
        summary, dropped = "", dropped + 1
    needs = [n.strip()[:120] for n in raw.get("needs_info") or [] if (n or "").strip()][:4]
    if not results and not any("결과" in n for n in needs):
        needs.append("결과 정보 필요: 행동 뒤에 무엇이 달라졌는지(실제로 있었던 것만)")
    return {"summary": summary[:300], "actions": actions, "problem_solving": problem, "results": results,
            "competencies": competencies, "needs_info": needs, "dropped": dropped}


def saved_analyses() -> dict[int, ExperienceAnalysis]:
    return {a.experience_id: a for a in owned(ExperienceAnalysis).all()}


def pending(exps: list, saved: dict) -> list:
    """분석 전이거나 내용이 바뀐 경험(먼저 등록한 순)."""
    return [e for e in exps if e.id not in saved or saved[e.id].content_hash != e.content_hash]


def run_analysis(exps: list) -> int:
    """경험 최대 BATCH개를 AI 한 번으로 분석해 저장. 실패하면 AiError(저장 안 함)."""
    exps = exps[:BATCH]
    raw = ai_client.analyze_experiences(exps, COMPETENCY_NAMES)
    saved = saved_analyses()
    n = 0
    for e in exps:
        if e.id not in raw:
            continue
        data = json.dumps(clean_analysis(raw[e.id], e), ensure_ascii=False)
        row = saved.get(e.id)
        if row:
            row.data_json, row.content_hash, row.model = data, e.content_hash, current_app.config["AI_MODEL"]
        else:
            row = create_owned(ExperienceAnalysis, experience_id=e.id, content_hash=e.content_hash, data_json=data)
            row.model = current_app.config["AI_MODEL"]  # create_owned 의 첫 인자 이름도 model 이라 따로 넣음
        n += 1
    return n


def overview(exps: list, saved: dict) -> dict:
    """핵심 역량(경험 근거 모음)과 보완할 점. 내용이 바뀐 경험의 옛 분석도 보여 주되 '갱신 필요'로 표시."""
    by_name: dict[str, list] = {}
    needs, no_result = [], []
    for e in exps:
        a = saved.get(e.id)
        if not a:
            continue
        d = a.data
        stale = a.content_hash != e.content_hash
        for c in d.get("competencies", []):
            by_name.setdefault(c["name"], []).append({"exp": e, "quotes": c["quotes"], "level": c["level"], "stale": stale})
        if d.get("needs_info"):
            needs.append({"exp": e, "items": d["needs_info"]})
        if not d.get("results"):
            no_result.append(e)
    comps = sorted(({"name": n, "items": items, "exp_count": len(items),
                     "strong": sum(1 for i in items if i["level"] == "충분")} for n, items in by_name.items()),
                   key=lambda c: (c["exp_count"], c["strong"]), reverse=True)
    return {"competencies": comps, "missing": [n for n in COMPETENCY_NAMES if n not in by_name],
            "needs": needs, "no_result": no_result, "analyzed": sum(1 for e in exps if e.id in saved)}


# ── C. 진단 강점 × 경험 연결 ────────────────────────────────────────

def links_of(profile) -> list[StrengthLink]:
    return owned(StrengthLink).filter(StrengthLink.profile_id == profile.id).order_by(StrengthLink.id).all()


def _evidence(level: str, quote: str) -> str:
    level = level if level in EVIDENCE_LEVELS else "약함"
    if level == "충분" and len(_norm(quote)) < 8:  # 아주 짧은 구절 하나로는 '충분'이라 하지 않음
        level = "보통"
    return level


def _ai_links(profile, exps: list) -> list[dict]:
    names = {s["name"] for s in profile.strengths}
    by_id = {e.id: e for e in exps}
    out = []
    for lk in ai_client.link_strengths_to_experiences(profile.strengths, exps):
        e = by_id.get(lk.get("experience_id"))
        if lk.get("strength") not in names or not e or not locate(lk.get("quote"), e):
            continue
        out.append({"strength": lk["strength"], "exp": e, "quote": lk["quote"].strip()[:300],
                    "reason": (lk.get("reason") or "")[:300], "evidence": _evidence(lk.get("evidence"), lk["quote"]),
                    "origin": "ai"})
    return out


def _rule_links(profile, exps: list) -> list[dict]:
    """키 없이: 강점 사전의 행동 단서 단어로 찾은 내 문장. 단어 매칭이라 '충분'은 주지 않음."""
    from ..strengths.services import link_strengths
    by_id = {e.id: e for e in exps}
    out = []
    for s in link_strengths(profile.strengths, exps):
        for m in s["matches"]:
            if not m["action"] or not locate(m["action"], by_id[m["id"]]):
                continue
            out.append({"strength": s["name"], "exp": by_id[m["id"]], "quote": m["action"],
                        "reason": f"'{', '.join(m['words'][:3]) or s['name']}' 같은 행동 단서가 이 문장에 있어요.",
                        "evidence": "보통" if len(m["words"]) >= 2 else "약함", "origin": "rule"})
    return out


def generate_links(profile, exps: list, use_ai: bool) -> int:
    """자동 연결 다시 만들기. 사용자가 고친·해제한·직접 만든 연결은 그대로 두고, 그 외 자동 연결만 바꿈."""
    new = _ai_links(profile, exps) if use_ai else _rule_links(profile, exps)
    kept = {}
    for lk in links_of(profile):
        if lk.origin == "user" or lk.edited or lk.removed:
            kept[(lk.strength_name, lk.experience_id)] = lk
        else:
            db.session.delete(lk)
    db.session.flush()
    n = 0
    for item in new:
        key = (item["strength"], item["exp"].id)
        if key in kept:
            continue
        kept[key] = create_owned(StrengthLink, profile_id=profile.id, strength_name=item["strength"][:40],
                                 experience_id=item["exp"].id, quote=item["quote"], reason=item["reason"],
                                 evidence=item["evidence"], origin=item["origin"], content_hash=item["exp"].content_hash)
        n += 1
    return n


def integrated(profile, links: list, view: dict, exps: list) -> dict:
    """C. 통합 결과: 일치하는 강점 · 근거가 부족한 강점 · 진단과 아직 연결되지 않은 경험 역량 · 구체화할 경험."""
    active = [lk for lk in links if not lk.removed]
    by_strength = {s["name"]: [lk for lk in active if lk.strength_name == s["name"]] for s in profile.strengths}
    matched = [n for n, ls in by_strength.items() if any(lk.evidence in ("충분", "보통") for lk in ls)]
    weak = [n for n in by_strength if n not in matched]
    linked_exp = {lk.experience_id for lk in active}
    extra = [c for c in view["competencies"] if not any(i["exp"].id in linked_exp for i in c["items"])]
    by_id = {e.id: e for e in exps}
    weak_exp_ids = {lk.experience_id for lk in active if lk.evidence == "약함"}
    refine = [by_id[i] for i in weak_exp_ids if i in by_id]
    refine += [n["exp"] for n in view["needs"] if n["exp"] not in refine]
    return {"by_strength": by_strength, "matched": matched, "weak": weak, "extra": extra[:6], "refine": refine[:6]}
