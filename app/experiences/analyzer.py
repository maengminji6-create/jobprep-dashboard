"""경험 → 무역 직무 적합도 · 활용 용도(강점/자소서/면접) 분석.

규칙 기반이라 키 없이도 동작하고, 결과가 왜 그렇게 나왔는지(매칭 단어)를 함께 보여 줍니다.
정확도를 높이려면 app/core/trade_roles.py 의 키워드를 보강하세요.
"""
import re

from ..core.trade_roles import (COMMON_SIGNALS, ESSAY_QUESTIONS, GROUP_BY_CODE, TRADE_ROLES,
                                USAGE_LABELS, USAGE_SIGNALS)

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|퍼센트|억|만\s?원|만|천|건|배|명|개국|개사|달러|usd|원|위|톤|teu)",
                       re.IGNORECASE)

# 공통 신호가 특히 중요한 직무 (신호 → 가산점을 받는 직무들)
SIGNAL_BONUS = {
    "language": ["overseas_sales", "overseas_marketing", "biz_dev", "trade_support", "forwarding",
                 "shipping_air", "sourcing"],
    "tool": ["trade_admin", "scm", "sourcing", "customs", "trade_finance"],
    "global": ["overseas_sales", "overseas_marketing", "biz_dev", "trade_support"],
    "certificate": [],  # 자격증 단어는 각 직무 키워드에 이미 포함
}
ROLE_SCALE = 14  # 이 원점수를 100점으로 환산


def _count(text: str, word: str) -> int:
    return text.count(word.lower())


def signals_of(text: str) -> dict:
    low = text.lower()
    return {code: [w for w in s["words"] if w.lower() in low] for code, s in COMMON_SIGNALS.items()}


def role_scores(text: str, signals: dict | None = None) -> dict:
    low = text.lower()
    signals = signals if signals is not None else signals_of(text)
    out = {}
    for role in TRADE_ROLES:
        raw, hits = 0.0, []
        for kw, weight in role["keywords"].items():
            n = _count(low, kw)
            if n:
                raw += weight * min(n, 2)
                hits.append(kw)
        for sig, roles in SIGNAL_BONUS.items():
            if role["code"] in roles and signals.get(sig):
                raw += 2
        out[role["code"]] = {"score": min(100, round(raw / ROLE_SCALE * 100)), "hits": hits}
    return out


def usage_scores(text: str) -> dict:
    low = text.lower()
    numbers = NUMBER_RE.findall(text)
    strength = sum(1 for w in USAGE_SIGNALS["strength"] if w in low) + len(numbers) * 2
    essay = sum(1 for w in USAGE_SIGNALS["essay"] if w in low) + min(len(text) // 250, 3)
    interview = sum(2 for w in USAGE_SIGNALS["interview"] if w in low) + \
        sum(1 for w in ("문제", "해결", "배운", "깨달") if w in low)
    scores = {"strength": min(100, strength * 12), "essay": min(100, essay * 15),
              "interview": min(100, interview * 12)}
    return {"scores": scores, "numbers": numbers[:5]}


def strength_score(exp, achievement: int) -> int:
    """강점 점수(0–100): 수치 성과·자격 신호 + 직접 적은 강점·성과 + 키워드 수."""
    score = achievement * 0.6
    if (exp.strengths or "").strip():
        score += 30
    score += min(len(exp.keyword_list), 4) * 5
    return min(100, round(score))


def analyze(exp) -> dict:
    text = exp.full_text
    sig = signals_of(text)
    roles = role_scores(text, sig)
    usage = usage_scores(text)
    best_usage = max(usage["scores"], key=usage["scores"].get)
    if usage["scores"][best_usage] == 0:
        best_usage = "essay"
    top_roles = sorted(roles.items(), key=lambda kv: kv[1]["score"], reverse=True)[:3]
    return {
        "id": exp.id, "title": exp.title, "category": exp.category, "period": exp.period,
        "organization": exp.organization or "", "role_text": exp.role or "", "keywords": exp.keyword_list,
        "strength": strength_score(exp, usage["scores"]["strength"]),
        "roles": roles, "top_roles": [(code, v["score"]) for code, v in top_roles],
        "usage": usage["scores"], "best_usage": best_usage, "best_usage_label": USAGE_LABELS[best_usage],
        "numbers": usage["numbers"],
        "signals": {code: words for code, words in sig.items() if words},
    }


def analyze_all(experiences) -> list[dict]:
    return [analyze(e) for e in experiences]


def essay_question_for(a: dict) -> str:
    """경험 성격에 맞는 자소서 문항 유형 추천."""
    sig = a.get("signals", {})
    if a["usage"]["interview"] >= 50:
        return ESSAY_QUESTIONS[2]["name"]
    if a["usage"]["strength"] >= 50 or sig.get("certificate") or sig.get("tool"):
        return ESSAY_QUESTIONS[1]["name"]
    if sig.get("global"):
        return ESSAY_QUESTIONS[0]["name"]
    return ESSAY_QUESTIONS[3]["name"]


def role_options():
    return [{"code": r["code"], "name": r["name"], "group": r["group"],
             "group_name": GROUP_BY_CODE[r["group"]]["name"]} for r in TRADE_ROLES]


def role_profile(analyses: list[dict], certs: list | None = None) -> dict:
    """직무별 내 적합도(0–100): 직무마다 가장 잘 맞는 경험 3개의 평균 + 자격증 가산점."""
    from ..core.certificates import cert_bonus
    evals = [c.evaluation for c in (certs or [])]
    out = {}
    for r in TRADE_ROLES:
        best = sorted((a["roles"][r["code"]]["score"] for a in analyses), reverse=True)[:3]
        base = round(sum(best) / len(best)) if best else 0
        out[r["code"]] = min(100, base + cert_bonus(evals, r["code"]))
    return out


def recommend_roles(analyses: list[dict], n: int = 3, certs: list | None = None) -> list[dict]:
    """직무를 고르지 않아도 모든 이력(경험+자격증)을 보고 추천하는 직무 n개(근거 경험·자격증·키워드 포함)."""
    from ..core.certificates import cert_bonus
    certs = certs or []
    evals = [(c, c.evaluation) for c in certs]
    prof = role_profile(analyses, certs)
    recs = []
    for code, score in sorted(prof.items(), key=lambda kv: kv[1], reverse=True):
        if score <= 0 or len(recs) == n:
            break
        backing = sorted(analyses, key=lambda a: a["roles"][code]["score"], reverse=True)[:2]
        backing = [a for a in backing if a["roles"][code]["score"] > 0]
        words = []
        for a in backing:
            words += [w for w in a["roles"][code]["hits"] if w not in words]
        cert_names = [c.name for c, ev in sorted(evals, key=lambda x: x[1]["roles"].get(code, 0), reverse=True)
                      if ev["roles"].get(code, 0) >= 50][:2]
        role = next(r for r in TRADE_ROLES if r["code"] == code)
        recs.append({"code": code, "name": role["name"], "group_name": GROUP_BY_CODE[role["group"]]["name"],
                     "score": score, "experiences": [a["title"] for a in backing], "keywords": words[:5],
                     "certs": cert_names, "cert_bonus": cert_bonus([ev for _, ev in evals], code)})
    return recs
