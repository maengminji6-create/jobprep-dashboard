"""직무 연결: 고른 직무의 요구 역량(core/job_competencies)마다 내 경험 근거를 붙입니다.

근거의 종류를 섞지 않습니다.
- 확인됨: AI 경험 분석에서 원문 인용이 확인된 역량(analysis.ExperienceAnalysis)
- 태그만 있음: 내가 경험에 단 역량 태그뿐, 근거 문장은 아직 없음
- 미확인: 어느 경험에서도 보이지 않음 → 보완할 경험 안내
점수는 매기지 않고, 필요 역량 중 몇 개가 확인됐는지만 셉니다.
"""
from ..core.job_competencies import JOB_BY_CODE

STATUS_LABELS = {"confirmed": "확인됨", "tagged": "태그만 있음", "missing": "미확인"}


def _evidence_by_competency(exps: list, saved: dict) -> dict:
    """{역량 이름: [{"exp", "quotes", "level", "stale"}]} — AI 분석에서 인용이 확인된 것만."""
    out: dict[str, list] = {}
    for e in exps:
        a = saved.get(e.id)
        if not a:
            continue
        for c in a.data.get("competencies", []):
            out.setdefault(c["name"], []).append({"exp": e, "quotes": c["quotes"], "level": c["level"],
                                                  "stale": a.content_hash != e.content_hash})
    return out


def job_view(code: str, exps: list, saved: dict, profile=None, links: list | None = None) -> dict:
    job = JOB_BY_CODE[code]
    evidence = _evidence_by_competency(exps, saved)
    rows = []
    for c in job["competencies"]:
        items = sorted(evidence.get(c["name"], []), key=lambda i: i["level"] != "충분")
        confirmed_ids = {i["exp"].id for i in items}
        tagged = [e for e in exps if c["name"] in e.competency_list and e.id not in confirmed_ids]
        status = "confirmed" if items else ("tagged" if tagged else "missing")
        rows.append({**c, "status": status, "status_label": STATUS_LABELS[status], "items": items, "tagged": tagged})

    # 연결되는 경험: 이 직무 요구 역량을 1개 이상 보여 준 경험(보여 준 역량 수 순)
    by_exp: dict[int, dict] = {}
    for r in rows:
        for i in r["items"]:
            by_exp.setdefault(i["exp"].id, {"exp": i["exp"], "competencies": []})["competencies"].append(r["name"])
    related = sorted(by_exp.values(), key=lambda x: len(x["competencies"]), reverse=True)
    marked = [e for e in exps if set(e.related_role_list) & set(job["trade_roles"])]  # 내가 '관련 직무'로 표시한 경험
    return {"job": job, "rows": rows, "related": related, "marked": marked,
            "confirmed": sum(r["status"] == "confirmed" for r in rows), "total": len(rows),
            "missing": [r for r in rows if r["status"] != "confirmed"],
            "strengths": strength_usage(job, rows, profile, links or [], saved, exps)}


def strength_usage(job: dict, rows: list, profile, links: list, saved: dict, exps: list) -> list[dict]:
    """진단 강점 → 연결된 경험 → 그 경험에서 확인된 역량 중 이 직무 요구 역량 → 이 직무에서 쓰이는 방식.
    같은 강점이라도 직무마다 요구 역량과 쓰임(use)이 달라 결과가 달라집니다."""
    if not profile:
        return []
    by_id = {e.id: e for e in exps}
    use = {r["name"]: r["use"] for r in rows}
    out = []
    for s in profile.strengths:
        ls = [lk for lk in links if lk.strength_name == s["name"] and not lk.removed and lk.experience_id in by_id]
        uses, unanalyzed = {}, []
        for lk in ls:
            a = saved.get(lk.experience_id)
            if not a:
                unanalyzed.append(by_id[lk.experience_id])
                continue
            for c in a.data.get("competencies", []):
                if c["name"] in use:
                    item = uses.setdefault(c["name"], {"name": c["name"], "use": use[c["name"]], "exps": [], "weak": True})
                    if by_id[lk.experience_id] not in item["exps"]:
                        item["exps"].append(by_id[lk.experience_id])
                    item["weak"] = item["weak"] and lk.evidence == "약함"
        out.append({"name": s["name"], "summary": s.get("summary", ""), "linked": len(ls),
                    "uses": list(uses.values()), "unanalyzed": unanalyzed})
    return out
