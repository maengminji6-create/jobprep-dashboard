"""나의 강점 사용 설명서 · 취업 준비 상황별 활용.

저장된 데이터(진단 강점 · 경험 원문 인용이 확인된 AI 분석 · 강점 × 경험 연결 · 직무 기준표)만 엮습니다.
새 문장을 지어내지 않으므로, 모든 근거는 경험 원문 인용이고 출처(진단/경험)를 함께 표시합니다.
결과는 JSON 으로 바로 저장할 수 있게 ORM 객체 대신 id·제목만 담습니다.
"""
from datetime import datetime

from ..core.job_competencies import JOB_BY_CODE, JOBS
from .services import integrated, overview

LEVEL_ORDER = {"충분": 0, "보통": 1, "약함": 2}


def _exp_ref(e) -> dict:
    return {"id": e.id, "title": e.title, "category": e.category, "star": e.star_filled}


def _jobs_for(competencies: set[str]) -> list[dict]:
    """이 역량들이 직무 기준표의 어느 직무에 쓰이는지 + 그 직무에서의 쓰임."""
    out = []
    for j in JOBS:
        uses = [{"competency": c["name"], "use": c["use"]} for c in j["competencies"] if c["name"] in competencies]
        if uses:
            out.append({"code": j["code"], "name": j["name"], "uses": uses})
    return sorted(out, key=lambda x: len(x["uses"]), reverse=True)


def _comps_of(exp_ids: set[int], saved: dict) -> set[str]:
    return {c["name"] for i in exp_ids if i in saved for c in saved[i].data.get("competencies", [])}


def _keywords(name: str, comps: set[str], exps: list) -> list[str]:
    words = [name] + sorted(comps)
    for e in exps:
        words += e.keyword_list[:3]
    return list(dict.fromkeys(w for w in words if w))[:8]


def _diag_entry(s: dict, links: list, by_id: dict, saved: dict, status: str) -> dict:
    ls = sorted((lk for lk in links if lk.strength_name == s["name"] and lk.experience_id in by_id),
                key=lambda lk: LEVEL_ORDER.get(lk.evidence, 3))
    evidence = [{"exp": _exp_ref(by_id[lk.experience_id]), "quote": lk.quote, "reason": lk.reason, "level": lk.evidence}
                for lk in ls]
    strong_ids = {lk.experience_id for lk in ls if lk.evidence != "약함"}
    comps = _comps_of(strong_ids, saved)
    gaps = []
    if not ls:
        gaps.append("경험 근거 없음 · 이 강점이 드러난 경험이 있다면 경험에 적고 AI 분석에서 연결해 보세요.")
    elif not strong_ids:
        gaps.append("근거가 약한 연결뿐이에요 · 강점이 드러난 행동을 경험에 더 구체적으로 적어 주세요.")
    if ls and not comps:
        gaps.append("연결된 경험을 AI로 분석하면 어느 직무에 쓰일지 보여 드려요.")
    for x in evidence[:2]:
        if x["exp"]["star"] < 4:
            gaps.append(f"'{x['exp']['title']}' STAR {x['exp']['star']}/4칸 · 면접 전에 나머지 칸을 채워 두세요.")
    return {"name": s["name"], "source": "진단", "status": status, "description": s.get("definition") or s.get("summary") or "",
            "evidence": evidence, "jobs": _jobs_for(comps),
            "keywords": _keywords(s["name"], comps, [by_id[i] for i in strong_ids]),
            "interview": [x for x in evidence if x["level"] != "약함" and x["quote"]][:2], "gaps": gaps}


def _exp_entry(c: dict, saved: dict) -> dict:
    """진단에 없거나 진단이 없을 때: 경험에서 확인된 역량을 '경험 기반 강점'으로."""
    items = sorted(c["items"], key=lambda i: LEVEL_ORDER.get(i["level"], 3))
    evidence = [{"exp": _exp_ref(i["exp"]), "quote": i["quotes"][0]["quote"], "reason": i["quotes"][0].get("reason", ""),
                 "level": i["level"]} for i in items]
    gaps = [f"'{x['exp']['title']}' STAR {x['exp']['star']}/4칸 · 면접 전에 나머지 칸을 채워 두세요."
            for x in evidence[:2] if x["exp"]["star"] < 4]
    return {"name": c["name"], "source": "경험", "status": "경험 기반", "description": "", "evidence": evidence,
            "jobs": _jobs_for({c["name"]}), "keywords": _keywords(c["name"], set(), [i["exp"] for i in items]),
            "interview": evidence[:2], "gaps": gaps}


def build_manual(exps: list, saved: dict, profile, links: list, job_code: str) -> dict:
    view = overview(exps, saved)
    by_id = {e.id: e for e in exps}
    active = [lk for lk in links if not lk.removed]
    entries = []
    if profile and profile.strengths:
        res = integrated(profile, links, view, exps)
        diag = {s["name"]: s for s in profile.strengths}
        entries += [_diag_entry(diag[n], active, by_id, saved, "진단 · 경험 일치") for n in res["matched"]]
        entries += [_exp_entry(c, saved) for c in res["extra"][:3]]
        entries += [_diag_entry(diag[n], active, by_id, saved, "진단 · 경험 근거 부족") for n in res["weak"]]
    else:
        entries += [_exp_entry(c, saved) for c in view["competencies"][:5]]
    job = JOB_BY_CODE.get(job_code) or JOBS[0]
    return {"generated_at": datetime.now().strftime("%Y.%m.%d %H:%M"), "job": {"code": job["code"], "name": job["name"]},
            "profile": {"filename": profile.filename, "tool": profile.parsed.get("tool", "")} if profile else None,
            "basis": {"exps": len(exps), "analyzed": view["analyzed"], "links": len(active)},
            "strengths": entries, "situations": situations(entries, exps, saved, job), "missing": view["missing"]}


def _best(exps: list, saved: dict, names: set[str], need_problem: bool = False) -> list[dict]:
    """역량 이름(names) 근거가 있는 경험과 그 인용(충분한 근거 먼저)."""
    out = []
    for e in exps:
        a = saved.get(e.id)
        if not a:
            continue
        d = a.data
        if need_problem and d.get("problem_solving"):
            out.append({"exp": _exp_ref(e), "quote": d["problem_solving"]["quote"], "label": "문제 해결 과정", "level": "보통"})
            continue
        for c in d.get("competencies", []):
            if c["name"] in names:
                out.append({"exp": _exp_ref(e), "quote": c["quotes"][0]["quote"], "label": c["name"], "level": c["level"]})
                break
    return sorted(out, key=lambda x: LEVEL_ORDER.get(x["level"], 3))[:3]


def situations(entries: list, exps: list, saved: dict, job: dict) -> dict:
    """자소서 문항·면접·1분 자기소개에 쓸 강점과 경험 조합(문장은 만들지 않고 소재만)."""
    required = {c["name"]: c["use"] for c in job["competencies"]}
    competency = _best(exps, saved, set(required))
    for x in competency:
        x["use"] = required.get(x["label"], "")
    fit = [{"name": s["name"], "source": s["source"],
            "uses": next((j["uses"] for j in s["jobs"] if j["code"] == job["code"]), []),
            "evidence": s["evidence"][0] if s["evidence"] else None}
           for s in entries if s["status"] != "진단 · 경험 근거 부족"]
    motivation = [f for f in fit if f["uses"]][:3]
    pitch = [f for f in motivation if f["evidence"]][:2] or [f for f in fit if f["evidence"]][:2]
    return {"competency": competency,
            "motivation": motivation,
            "collaboration": _best(exps, saved, {"협업·조율", "협상·설득", "고객 응대"}),
            "problem": _best(exps, saved, {"문제 해결"}, need_problem=True),
            "interview": [{"strength": s["name"], **x} for s in entries for x in s["interview"][:1]][:5],
            "pitch": pitch}
