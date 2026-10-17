"""강점 진단 결과 읽기 · 내 경험과 연결하기.

1) parse_strengths(): 결과지 텍스트에서 강점 이름·설명을 뽑습니다.
   - 'TOP 5 강점' 목록, 'Top1. 신중함' 같은 세부 가이드 제목, '정의' 문단을 먼저 찾고
   - 형식이 다른 결과지는 강점 단어 사전(STRENGTH_LEXICON)에서 자주 나온 단어로 대신합니다.
2) link_strengths(): 강점마다 그 강점이 드러나는 내 경험을 '행동 단서 단어'로 찾아 연결합니다(키 없이 동작).
3) AI 키가 있으면 integrations.ai_client.link_strengths_ai() 로 더 자연스러운 연결·자소서 팁을 받습니다.
"""
import hashlib
import json
import re

from ..core.scoping import owned

# 강점 이름 → 경험에서 그 강점이 드러나는 행동 단서. 이름이 사전에 없으면 이름 자체로 찾습니다.
STRENGTH_LEXICON = {
    "신중함": ["신중", "꼼꼼", "점검", "확인", "검토", "실수", "착오", "정확", "대비", "체크"],
    "효과성": ["효율", "효과", "단축", "절감", "개선", "자동화", "빠르", "줄였", "간소화", "최적"],
    "주도": ["주도", "팀장", "리더", "이끌", "먼저", "제안", "총괄", "맡아", "추진"],
    "계획성": ["계획", "일정", "마일스톤", "스케줄", "체크리스트", "미리", "준비", "데일리스크럼", "일정관리"],
    "조화력": ["조율", "의견 취합", "의견을 취합", "협업", "갈등", "소통", "팀원", "화합", "중재", "분위기"],
    "책임감": ["책임", "끝까지", "완수", "마감", "맡은"],
    "성실": ["성실", "근면", "꾸준", "매일", "지각"],
    "소통": ["소통", "설명", "발표", "응대", "커뮤니케이션", "통역", "전달"],
    "공감": ["공감", "배려", "경청", "고객 입장", "도움"],
    "분석력": ["분석", "데이터", "리서치", "조사", "통계", "계산", "비교"],
    "실행력": ["실행", "바로", "즉시", "행동", "옮겼", "시도"],
    "추진력": ["추진", "밀고", "이끌", "성사", "돌파"],
    "리더십": ["리더", "팀장", "이끌", "총괄", "역할배분", "역할 배분"],
    "창의성": ["아이디어", "창의", "새로운", "기획", "제안", "독특", "유니크"],
    "적응력": ["적응", "해외", "현지", "새로운 환경", "교환학생", "낯선"],
    "끈기": ["끈기", "포기", "반복", "극복", "버텨"],
    "협업": ["협업", "팀", "함께", "공동", "협력"],
    "학습": ["배우", "공부", "학습", "교육", "자격", "취득", "받아적"],
    "정리력": ["정리", "문서화", "기록", "회의록", "노션", "체계"],
    "고객지향": ["고객", "손님", "응대", "만족", "클레임", "컴플레인"],
    "정확성": ["정확", "오차", "착오", "검수", "확인"],
    "긍정성": ["긍정", "웃", "분위기", "즐겁"],
}
GENERIC_STRENGTHS = list(STRENGTH_LEXICON)

# 공고가 '이런 사람을 원한다'고 쓸 때의 표현. 공고 형광펜(초록)은 이 표현에만 칠합니다.
POSTING_SIGNALS = {
    "신중함": ["꼼꼼", "세심", "정확성", "정확한", "리스크", "검토"],
    "효과성": ["효율", "업무 개선", "프로세스 개선", "최적화", "원가 절감", "비용 절감", "생산성"],
    "주도": ["주도적", "주도하", "리더십", "주인의식", "오너십", "능동적", "적극적", "자기주도"],
    "계획성": ["계획 수립", "계획적", "일정 관리", "체계적", "우선순위"],
    "조화력": ["협업", "조율", "유관부서", "팀워크", "원활한 소통", "커뮤니케이션"],
    "책임감": ["책임감", "끝까지"],
    "성실": ["성실"],
    "소통": ["커뮤니케이션", "원활한 소통", "대인관계"],
    "공감": ["공감", "고객 입장"],
    "분석력": ["분석력", "데이터 분석", "분석 능력", "인사이트"],
    "실행력": ["실행력", "추진력"],
    "추진력": ["추진력", "실행력"],
    "리더십": ["리더십"],
    "창의성": ["창의", "아이디어", "기획력"],
    "적응력": ["적응력", "변화에 유연", "다양한 환경"],
    "끈기": ["끈기", "인내"],
    "협업": ["협업", "팀워크", "유관부서"],
    "학습": ["학습", "자기계발", "빠르게 배우"],
    "정리력": ["문서화", "문서 작성", "보고서 작성"],
    "고객지향": ["고객 응대", "고객 만족", "고객 중심", "고객 서비스", "CS"],
    "정확성": ["정확성", "꼼꼼"],
    "긍정성": ["긍정"],
}


def posting_signals(name: str) -> list[str]:
    """공고에서 이 강점을 원한다는 표현. 사전에 없는 강점은 강점 이름(어간)만 사용."""
    if name in POSTING_SIGNALS:
        return POSTING_SIGNALS[name]
    stem = re.sub(r"(함|력|성|감)$", "", name)
    return [name] + ([stem] if len(stem) >= 2 else [])

TOP_LIST_RE = re.compile(r"(\d)\s+([가-힣A-Za-z]{2,8})\s+(.+?)(?=\s+\d\s+[가-힣A-Za-z]{2,8}\s|$)")
GUIDE_RE = re.compile(r"Top\s*(\d)\s*[\.\)]\s*([가-힣A-Za-z]{2,8})")
AREA_RE = re.compile(r"강점이 나타날 때\?\s*\n?\s*([가-힣]{2,4})\s*[—\-–]\s*(.+)")
ROLE_RE = re.compile(r"강점 역할은\?\s*\n?\s*([가-힣]{2,4})\s*[—\-–]\s*(.+)")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_strengths(text: str) -> dict:
    """{"strengths": [{"name", "summary", "rank"}], "area": "...", "role": "...", "method": "list|dictionary"}"""
    text = text or ""
    found: dict[str, dict] = {}

    # ① 'TOP 5 강점' 같은 줄에서 "1 신중함 잘못될 일을 미리 살핍니다 2 효과성 ..." 형태
    for line_start in [m.end() for m in re.finditer(r"TOP\s*\d+[^\n]*강점[^\n]*\n", text, re.IGNORECASE)]:
        lines = []
        for ln in text[line_start:line_start + 800].splitlines():  # '1 신중함 …' 처럼 숫자로 시작하는 줄만 이어 붙임
            if not re.match(r"\s*\d\s+[가-힣A-Za-z]", ln):
                break
            lines.append(ln.strip())
        block = " ".join(lines)
        for m in TOP_LIST_RE.finditer(block):
            name = m.group(2)
            if name not in found and len(found) < 10:
                found[name] = {"name": name, "summary": _clean(m.group(3))[:80], "rank": int(m.group(1))}

    # ② 'DNA 세부 가이드 Top1. 신중함' 형태의 제목과 그 아래 '정의' 첫 문장
    for m in GUIDE_RE.finditer(text):
        name = m.group(2)
        item = found.setdefault(name, {"name": name, "summary": "", "rank": int(m.group(1))})
        if not item.get("definition"):
            after = text[m.end():m.end() + 1500]
            d = re.search(r"정의\s*\n(.+?)(?:\n|$)", after)
            if d:
                item["definition"] = _clean(d.group(1))[:200]

    method = "list"
    if not found:
        # ③ 형식을 모르는 결과지: 사전의 강점 단어가 2번 이상 나오면 강점으로 봄
        method = "dictionary"
        counts = {name: text.count(name) for name in GENERIC_STRENGTHS}
        for rank, (name, n) in enumerate(sorted(counts.items(), key=lambda kv: kv[1], reverse=True), 1):
            if n < 2 or len(found) == 6:
                break
            found[name] = {"name": name, "summary": f"결과지에 {n}번 등장", "rank": rank}

    strengths = sorted(found.values(), key=lambda s: s.get("rank", 99))
    for s in strengths:
        if not s.get("summary") and s.get("definition"):
            s["summary"] = s["definition"][:80]
    area = AREA_RE.search(text)
    role = ROLE_RE.search(text)
    return {"strengths": strengths, "method": method,
            "area": f"{area.group(1)} — {_clean(area.group(2))}" if area else "",
            "role": f"{role.group(1)} — {_clean(role.group(2))}" if role else ""}


def _clues(name: str) -> list[str]:
    if name in STRENGTH_LEXICON:
        return STRENGTH_LEXICON[name]
    stem = re.sub(r"(함|력|성|감)$", "", name)
    return [name] + ([stem] if len(stem) >= 2 else [])


def link_strengths(strengths: list[dict], exps: list) -> list[dict]:
    """강점마다 연결되는 경험(최대 3개)과 근거 단어. 매트릭스용 점수도 함께 돌려줍니다."""
    out = []
    for s in strengths:
        clues = _clues(s["name"])
        matches = []
        for e in exps:
            text = e.full_text
            words = [w for w in clues if w in text]
            score = len(words) + (2 if s["name"] in (e.keywords or "") + (e.strengths or "") else 0)
            if score:
                matches.append({"id": e.id, "title": e.title, "category": e.category, "words": words[:4], "score": score})
        matches.sort(key=lambda m: m["score"], reverse=True)
        tip = ""
        if matches:
            m = matches[0]
            tip = (f"'{m['title']}'에서 {', '.join(m['words'][:2]) or s['name']} 같은 행동이 '{s['name']}' 강점을 보여 줘요. "
                   f"자소서에서는 강점 → 그 경험에서 한 구체적 행동 → 결과 순서로 쓰세요.")
        out.append({**s, "matches": matches[:3], "all_scores": {m["id"]: m["score"] for m in matches}, "tip": tip})
    return out


def matrix(linked: list[dict], exps: list, limit: int = 8) -> dict:
    """강점(행) × 경험(열) 연결 점수표. 강점과 많이 이어지는 경험부터 최대 limit개."""
    totals = {e.id: sum(s["all_scores"].get(e.id, 0) for s in linked) for e in exps}
    cols = [e for e in sorted(exps, key=lambda e: totals[e.id], reverse=True) if totals[e.id] > 0][:limit]
    top = max([s["all_scores"].get(e.id, 0) for s in linked for e in cols] or [1])
    rows = [{"name": s["name"], "cells": [round(s["all_scores"].get(e.id, 0) / top * 100) for e in cols]} for s in linked]
    return {"cols": cols, "rows": rows}


def experiences_hash(exps, role: str, profile_id: int) -> str:
    raw = f"{role}|{profile_id}|" + "|".join(e.content_hash for e in sorted(exps, key=lambda e: e.id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def latest_profile():
    from flask_login import current_user

    from .models import StrengthProfile
    if not current_user.is_authenticated:
        return None
    q = owned(StrengthProfile)
    return (q.filter(StrengthProfile.is_active.is_(True)).order_by(StrengthProfile.created_at.desc()).first()
            or q.order_by(StrengthProfile.created_at.desc()).first())


def profile_history():
    from .models import StrengthProfile
    return owned(StrengthProfile).order_by(StrengthProfile.created_at.desc()).all()


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)
