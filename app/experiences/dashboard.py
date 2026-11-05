"""홈 대시보드: 저장된 실제 데이터(경험 · AI 분석 · 강점 연결 · 직무 기준표)만으로 계산합니다. 점수는 만들지 않습니다."""
import re
from collections import Counter

from ..core.job_competencies import JOBS
from .models import CATEGORIES

YEAR = re.compile(r"(19|20)\d{2}")


def by_year(exps: list) -> list[tuple[str, int]]:
    """경험 기간의 시작 연도별 개수(기간을 적지 않은 경험은 '기간 미입력')."""
    counts = Counter()
    for e in exps:
        m = YEAR.search(e.period or "")
        counts[m.group(0) if m else "기간 미입력"] += 1
    years = sorted(k for k in counts if k != "기간 미입력")
    return [(y, counts[y]) for y in years] + ([("기간 미입력", counts["기간 미입력"])] if counts["기간 미입력"] else [])


def build(exps: list, saved: dict, profile, links: list) -> dict:
    from ..analysis.services import integrated, overview, pending
    from ..jobfit.services import job_view
    view = overview(exps, saved)
    cats = [(c, sum(1 for e in exps if e.category == c)) for c in CATEGORIES]
    jobs = []
    for j in JOBS:
        v = job_view(j["code"], exps, saved)
        jobs.append({"code": j["code"], "name": j["name"], "confirmed": v["confirmed"], "total": v["total"],
                     "names": [r["name"] for r in v["rows"] if r["status"] == "confirmed"]})
    strength = None
    if profile and profile.strengths:
        res = integrated(profile, links, view, exps)
        strength = {"total": len(profile.strengths), "matched": res["matched"], "weak": res["weak"]}
    waiting = pending(exps, saved)
    return {"total": len(exps), "analyzed": view["analyzed"], "stale": sum(1 for e in waiting if e.id in saved),
            "categories": [(c, n) for c, n in cats if n], "cat_max": max([n for _c, n in cats] or [1]) or 1,
            "years": by_year(exps), "competencies": view["competencies"][:8], "jobs": jobs, "strength": strength,
            "recent": sorted(exps, key=lambda e: e.created_at, reverse=True)[:5],
            "waiting": waiting[:6], "waiting_total": len(waiting),
            "star_full": sum(1 for e in exps if e.star_filled == 4)}
