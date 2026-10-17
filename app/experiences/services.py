"""경험 추가·업데이트 규칙.

같은 경험(제목이 같거나, 사용자가 '기존 경험에 추가'로 고른 경험)이 이미 있으면 새로 만들지 않고 합칩니다.
- 역할·내용·강점·느낀점: 이미 있는 문장은 건너뛰고 새 문장만 아래에 덧붙임
- 키워드: 중복 없이 합침
- 분류·기관·기간: 새 값이 있으면 새 값으로
분석은 화면을 열 때마다 최신 내용으로 다시 계산되므로 저장만 하면 표·차트에 바로 반영됩니다.
"""
import json
import re

NL = "\n"

from ..core.scoping import create_owned, owned
from .models import CATEGORIES, Experience

SCALAR_FIELDS = ("category", "organization", "period")


def _norm(text: str) -> str:
    return re.sub(r"[\s·\-_/()\[\]【】]+", "", (text or "").lower())


def split_keywords(text: str) -> list[str]:
    return [k for k in (w.strip(" #·") for w in re.split(r"[,#\n/]", text or "")) if k]


def merge_keywords(old: str, new: str) -> str:
    out, seen = [], set()
    for k in split_keywords(old) + split_keywords(new):
        if _norm(k) not in seen:
            seen.add(_norm(k))
            out.append(k)
    return ", ".join(out)


def merge_text(old: str, new: str) -> str:
    """새 글에서 기존 글에 없는 줄만 덧붙입니다."""
    old, new = (old or "").strip(), (new or "").strip()
    if not new:
        return old
    if not old:
        return new
    have = _norm(old)
    fresh = [ln for ln in new.splitlines() if ln.strip() and _norm(ln) not in have]
    return f"{old}\n{chr(10).join(fresh)}" if fresh else old


def find_same(title: str):
    key = _norm(title)
    if not key:
        return None
    return next((e for e in owned(Experience).all() if _norm(e.title) == key), None)


def apply_fields(exp: Experience, fields: dict) -> None:
    for f in SCALAR_FIELDS:
        v = (fields.get(f) or "").strip()
        if v and not (f == "category" and v == "기타" and exp.category not in ("", "기타")):
            setattr(exp, f, v if f != "category" or v in CATEGORIES else "기타")
    for f in Experience.TEXT_FIELDS:
        new = fields.get(f) or ""
        if f == "keywords":
            exp.keywords = merge_keywords(exp.keywords, new)
        else:
            setattr(exp, f, merge_text(getattr(exp, f), new))


def upsert_experience(fields: dict, target: Experience | None = None, source: str = "manual",
                      upload_id: int | None = None) -> tuple[Experience, bool]:
    """(경험, 새로 만들었는지)를 돌려줍니다. commit 은 호출한 쪽에서 합니다."""
    exp = target or find_same(fields.get("title", ""))
    if exp:
        apply_fields(exp, fields)
        return exp, False
    exp = create_owned(Experience, title=(fields.get("title") or "이름 없는 경험")[:200], source=source,
                       upload_id=upload_id, category="기타")
    for f in Experience.TEXT_FIELDS:
        setattr(exp, f, "")
    apply_fields(exp, fields)
    return exp, True


# ── 자격증·어학 ─────────────────────────────────────────────────────

def upsert_certificate(name: str, score: str = "", issuer: str = "", acquired: str = "", note: str = ""):
    """(자격증, 새로 만들었는지). 이름이 같으면(띄어쓰기·대소문자 무시) 새 값으로 업데이트. commit 은 호출한 쪽에서."""
    from .models import Certificate
    name = (name or "").strip()[:120]
    key = _norm(name)
    cert = next((c for c in owned(Certificate).all() if _norm(c.name) == key), None)
    created = cert is None
    if created:
        cert = create_owned(Certificate, name=name)
    for field, value, limit in (("score", score, 60), ("issuer", issuer, 120), ("acquired", acquired, 40), ("note", note, 5000)):
        value = (value or "").strip()
        if value or created:
            setattr(cert, field, value[:limit])
    return cert, created


def certificate_from_item(item: dict) -> dict:
    """파일에서 읽은 '자격증·어학' 행을 자격증 필드로 바꿉니다."""
    score = (item.get("strengths") or "").replace("점수·등급:", "").strip()
    note = NL.join(v for v in (item.get("role"), item.get("content"), item.get("reflection")) if v)
    note = NL.join(ln for ln in note.splitlines() if not ln.startswith("종류:"))
    return {"name": item.get("title", ""), "score": score, "issuer": item.get("organization", ""),
            "acquired": item.get("period", ""), "note": note}


# ── TOP 3 에서 빼기 ──────────────────────────────────────────────────

def excluded_ids(role_code: str) -> set[int]:
    from .models import TopExclusion
    return {x.experience_id for x in owned(TopExclusion).filter(TopExclusion.role_code == role_code)}


# ── 자소서 어필 코멘트 ───────────────────────────────────────────────

def rule_comment(a: dict, role_code: str, role_name: str) -> dict:
    """AI 키가 없을 때 보여 주는 규칙 기반 기본 코멘트(분석기 결과로 만듦)."""
    from .analyzer import essay_question_for
    fit = a["roles"][role_code]
    points = []
    if fit["hits"]:
        points.append(f"'{', '.join(fit['hits'][:3])}' 경험을 {role_name} 실무와 직접 연결해 쓰세요.")
    if a["numbers"]:
        points.append(f"'{a['numbers'][0]}' 같은 수치 성과를 첫 문단에 두세요.")
    for words in list(a["signals"].values())[:1]:
        points.append(f"'{words[0]}' 역량을 근거로 함께 제시하세요.")
    if a["keywords"]:
        points.append(f"직접 적은 키워드({', '.join(a['keywords'][:3])})를 행동 사례로 풀어 쓰세요.")
    if not points:
        points.append("맡은 역할과 그 결과를 상황→행동→결과 순서로 정리해 보세요.")
    return {"summary": f"{role_name} 적합도 {fit['score']}점 경험이에요.",
            "appeal_points": points[:3], "essay_question": essay_question_for(a), "opening_sentence": "",
            "improve": "결과를 숫자(%, 건수, 기간)로 적으면 더 설득력 있어요." if not a["numbers"]
            else "본인이 직접 한 행동과 팀이 한 일을 구분해 적어 보세요."}


def saved_comments(role_code: str) -> dict:
    """{경험 id: ExperienceComment} — 현재 사용자, 현재 직무."""
    from .models import ExperienceComment
    rows = owned(ExperienceComment).filter(ExperienceComment.role_code == role_code).all()
    return {c.experience_id: c for c in rows}


def generate_comments(exps: list, analyses: dict, role_code: str, role_name: str) -> int:
    """AI 코멘트를 받아 저장합니다. 한 요청에 최대 6개씩 보냅니다. commit 은 호출한 쪽에서."""
    from flask import current_app

    from ..integrations.ai_client import comment_experiences
    from .models import ExperienceComment
    existing = saved_comments(role_code)
    done = 0
    for i in range(0, len(exps), 6):
        chunk = exps[i:i + 6]
        items = [(e, analyses[e.id]["roles"][role_code]["hits"]) for e in chunk]
        result = comment_experiences(items, role_name)
        for e in chunk:
            data = result.get(e.id)
            if not data:
                continue
            row = existing.get(e.id) or create_owned(ExperienceComment, experience_id=e.id, role_code=role_code,
                                                     content_hash="")
            row.content_hash = e.content_hash
            row.model = current_app.config["AI_MODEL"]
            row.data_json = json.dumps({k: v for k, v in data.items() if k != "id"}, ensure_ascii=False)
            done += 1
    return done
