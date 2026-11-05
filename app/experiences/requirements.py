"""공고 요건 하나하나를 내 경험과 대조합니다(규칙 기반, 외부 API 없음).

판정은 세 가지뿐이고, 근거가 없으면 확정하지 않습니다.
- met(충족): 요건의 핵심어 2개 이상(핵심어가 1개뿐이면 그 1개)이 내 경험의 한 문장에 함께 나오거나, 요구 자격증을 내가 가짐
- check(확인 필요): 일부 핵심어만 겹침 / 학력·전공·경력 연수·병역 등 경험 기록으로는 알 수 없는 조건
- none(근거 없음): 내 경험 기록에서 찾지 못함 — '없다'는 뜻이 아니라 '적혀 있지 않다'는 뜻
항목마다 공고 문장 · 내 경험 문장 · 겹친 단어를 근거로 붙입니다.
"""
import re

# 경험 기록으로 판단할 수 없는 조건(사용자가 직접 확인)
UNDECIDABLE = re.compile(
    r"(학사|석사|박사|대졸|초대졸|고졸|학위|졸업|전공|학과|경력\s*\d|\d+\s*년\s*(이상|차)|신입|병역|군필|면제|운전\s*면허|"
    r"결격\s*사유|출국|거주|통근|근무\s*가능|입사\s*가능|연령|나이|degree|bachelor|master|major|years?\s+of)", re.I)

# 판정에 쓰지 않는 말(어느 요건에나 붙는 말)
STOP = set("""및 등 또는 이상 이하 보유 보유자 가능 가능자 가능한 우대 필수 능력 역량 경험 경험자 소지 소지자 관련 해당 분야 업무
있는 있으신 분 자 이해 기본 기본적인 원활 원활한 능통 능통자 우수 우수자 수준 활용 사용 지식 대한 위한 통한 함께 갖춘 지닌
성향 태도 마인드 사람 인재 지원 지원자 채용 모집 담당 수행 관리 진행 직무 the and or with for of to in a an experience
skills skill ability strong good excellent knowledge plus preferred required requirements qualifications""".split())

# 영어 공고 ↔ 한국어 경험: 자주 쓰는 직무 용어 대응(양방향으로 씀)
GLOSSARY = {
    "buyer": ["바이어"], "buyers": ["바이어"], "export": ["수출"], "exports": ["수출"], "import": ["수입"],
    "shipping": ["선적", "운송", "배송"], "shipment": ["선적"], "logistics": ["물류"], "sales": ["영업", "세일즈"],
    "marketing": ["마케팅"], "customer": ["고객"], "customers": ["고객"], "client": ["고객", "거래처"],
    "negotiation": ["협상"], "contract": ["계약"], "contracts": ["계약"], "sourcing": ["소싱"], "purchasing": ["구매"],
    "procurement": ["구매", "조달"], "supplier": ["공급업체", "협력사"], "suppliers": ["공급업체", "협력사"],
    "english": ["영어", "영문"], "chinese": ["중국어"], "japanese": ["일본어"], "excel": ["엑셀"],
    "data": ["데이터"], "analysis": ["분석"], "communication": ["소통", "커뮤니케이션"], "documents": ["서류", "문서"],
    "documentation": ["서류", "문서"], "trade": ["무역"], "inventory": ["재고"], "order": ["오더", "발주", "주문"],
    "orders": ["오더", "발주", "주문"], "schedule": ["일정"], "schedules": ["일정"], "report": ["보고", "리포트"],
    "reporting": ["보고", "리포트"], "presentation": ["발표"], "project": ["프로젝트"], "overseas": ["해외"],
    "global": ["글로벌", "해외"], "market": ["시장"], "research": ["조사", "리서치"], "customs": ["통관", "관세"],
    "translation": ["번역"], "email": ["메일", "이메일"], "planning": ["기획"], "event": ["행사", "이벤트"],
}
_KO_TO_EN = {}
for _en, _kos in GLOSSARY.items():
    for _ko in _kos:
        _KO_TO_EN.setdefault(_ko, set()).add(_en)

_JOSA = re.compile(r"(으로|에서|에게|까지|부터|이나|이며|이고|하고|하는|하며|하여|해서|된|되는|적인|적|을|를|이|가|은|는|의|에|와|과|도|로|자)$")


def _split_items(lines: list[str]) -> list[str]:
    """한 줄에 쉼표로 여러 요건이 있으면 나눔(괄호 안 쉼표는 그대로)."""
    out = []
    for ln in lines:
        ln = ln.strip(" -•·*○◦ㆍ※\t")
        if len(ln) < 3:
            continue
        parts, depth, buf = [], 0, ""
        for ch in ln:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch in ",;" and depth <= 0:
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        parts.append(buf)
        parts = [p.strip(" .") for p in parts if len(p.strip(" .")) >= 3]
        out += parts if len(parts) > 1 and all(len(p) <= 60 for p in parts) else [ln.strip(" .")]
    return out[:20]


def terms(text: str) -> list[str]:
    """요건·문장의 핵심어: 한글 2자 이상(조사 뗌) · 영문 3자 이상, 흔한 말 제외, 순서 유지."""
    out = []
    for raw in re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z+#.]{2,}", text or ""):
        w = raw.lower().strip(".")
        if re.match(r"[가-힣]", w):
            w = _JOSA.sub("", w) if len(w) > 2 else w
        if len(w) < 2 or w in STOP or w in out:
            continue
        out.append(w)
    return out


def _variants(term: str) -> set[str]:
    v = {term}
    v.update(GLOSSARY.get(term, []))
    v.update(_KO_TO_EN.get(term, set()))
    return v


def _appears(word: str, low: str) -> bool:
    """두 글자 한국어는 낱말 첫머리에서만('사업계획서'의 '업계'는 아님), 영어는 낱말 경계에서, 세 글자 이상 한국어는 어디서나."""
    if re.match(r"[가-힣]", word):
        return word in low if len(word) >= 3 else bool(re.search(rf"(?<![가-힣]){re.escape(word)}", low))
    return bool(re.search(rf"(?<![a-z]){re.escape(word)}", low))


def _hits(item_terms: list[str], sentence: str) -> list[str]:
    """요건 핵심어 가운데 이 문장에 나오는 것 — 문장에 실제로 적힌 말로(영어 요건 'buyers' → 경험의 '바이어')."""
    low = sentence.lower()
    found = []
    for t in item_terms:
        hit = next((x for x in sorted(_variants(t), key=len, reverse=True) if _appears(x, low)), None)
        if hit and hit not in found:
            found.append(hit)
    return found


def _sentences(text: str) -> list[str]:
    out = []
    for ln in (text or "").splitlines():
        for part in re.split(r"(?<=[.!?。])\s+|\s*/\s+", ln):
            part = part.strip(" -•·")
            if 4 <= len(part) <= 240:
                out.append(part)
    return out


def _cert_hit(item: str, certs: list) -> object | None:
    low = item.lower().replace(" ", "")
    for c in certs:
        base = re.sub(r"\s*(\d\s*급|\d+\s*점?|level\s*\d+|lv\.?\s*\d+)\s*$", "", (c.name or "").strip(), flags=re.I)
        base = base.lower().replace(" ", "")
        if len(base) >= 2 and base in low:
            return c
    return None


def _suggest(item: str, item_terms: list[str]) -> str:
    low = item.lower()
    if re.search(r"(영어|중국어|일본어|어학|토익|toeic|opic|오픽|english|language)", low):
        return "어학 점수가 있다면 '자격증·어학'에 추가하고, 외국어로 일한 경험(메일·통화·발표)을 경험 내용에 적어 주세요."
    if re.search(r"(자격증|자격|certificate|license|무역영어|국제무역사|관세사|물류관리사)", low):
        return "해당 자격증이 있다면 '자격증·어학'에 추가하세요. 없다면 취득 계획을 세우거나 관련 교육 이수를 적어 보세요."
    if re.search(r"(엑셀|excel|sap|erp|ppt|파워포인트|sql|python|tableau|툴|tool)", low):
        return "그 도구를 쓴 경험(무엇을 만들었는지·얼마나 줄였는지)이 있다면 경험 내용에 구체적으로 적어 주세요."
    key = ", ".join(item_terms[:3]) or "이 요건"
    return f"'{key}'와 관련해 직접 한 일이 있다면 경험의 역할·내용에 행동과 결과로 적어 주세요."


def check_requirements(sections: list[dict], experiences: list, certs: list | None = None) -> dict:
    """sections: posting.split_sections() 결과 · experiences: Experience 목록.
    {"items": [...], "summary": {...}, "support": [경험별 받쳐 주는 요건 수]}"""
    certs = certs or []
    exp_sents = [(e, s) for e in experiences for s in _sentences(e.full_text)]
    items = []
    for kind in ("자격요건", "우대사항"):
        lines = [ln for sec in sections if sec["name"] == kind for ln in sec["lines"]]
        for text in _split_items(lines):
            it = {"kind": "required" if kind == "자격요건" else "preferred", "text": text, "terms": terms(text),
                  "status": "none", "reason": "", "evidence": [], "suggestion": ""}
            cert = _cert_hit(text, certs)
            if cert:
                it.update(status="met", reason=f"요구한 자격을 갖고 있어요: {cert.name}{' ' + cert.score if cert.score else ''}")
                items.append(it)
                continue
            scored = []
            for e, s in exp_sents:
                h = _hits(it["terms"], s)
                if h:
                    scored.append((len(h), e, s, h))
            scored.sort(key=lambda x: x[0], reverse=True)
            best, seen = [], set()
            for n, e, s, h in scored:
                if e.id in seen:
                    continue
                seen.add(e.id)
                best.append({"experience_id": e.id, "title": e.title, "sentence": s, "words": h})
                if len(best) >= 2:
                    break
            it["evidence"] = best
            need = 1 if len(it["terms"]) <= 1 else 2
            top = len(best[0]["words"]) if best else 0
            if UNDECIDABLE.search(text):
                it.update(status="check", reason="학력·전공·경력 연수 같은 조건은 경험 기록만으로 판단할 수 없어요. 직접 확인해 주세요.")
            elif top >= need:
                it.update(status="met", reason=f"'{best[0]['title']}' 경험에 {', '.join(best[0]['words'])}이(가) 함께 나와요.")
            elif top:
                it.update(status="check", reason=f"'{best[0]['title']}'에 {', '.join(best[0]['words'])}만 겹쳐요. 요건을 다 보여 주는지 확인해 주세요.")
            else:
                it.update(reason="내 경험 기록에서 이 요건을 보여 주는 문장을 찾지 못했어요(경험이 없다는 뜻은 아니에요).")
            if it["status"] != "met":
                it["suggestion"] = "" if UNDECIDABLE.search(text) else _suggest(text, it["terms"])
            items.append(it)

    def count(kind, status=None):
        return sum(1 for i in items if i["kind"] == kind and (status is None or i["status"] == status))
    summary = {k: {"total": count(k), "met": count(k, "met"), "check": count(k, "check"), "none": count(k, "none")}
               for k in ("required", "preferred")}
    support = {}
    for i in items:
        if i["status"] in ("met", "check"):
            for ev in i["evidence"][:1]:
                s = support.setdefault(ev["experience_id"], {"id": ev["experience_id"], "title": ev["title"], "met": 0,
                                                            "check": 0, "items": []})
                s[i["status"]] += 1
                s["items"].append(i["text"])
    ranked = sorted(support.values(), key=lambda s: (s["met"], s["check"]), reverse=True)[:5]
    return {"items": items, "summary": summary, "support": ranked, "enough": bool(items)}


EMPLOYMENT = re.compile(r"(정규직|계약직|인턴|파견직|프리랜서|채용\s*연계형|전환형|full[\s-]?time|part[\s-]?time|contract|intern(ship)?)", re.I)
LOCATION_LINE = re.compile(r"(근무\s*지|근무\s*지역|근무\s*장소|location|office)", re.I)


def posting_structure(sections: list[dict], text: str) -> dict:
    """공고 구조: 담당 업무 · 필수 · 우대 · 근무 형태 · 근무지 · 근무 조건(원문 줄 그대로)."""
    pick = lambda name: [ln for sec in sections if sec["name"] == name for ln in sec["lines"]][:15]  # noqa: E731
    conditions = pick("근무조건")
    employment = sorted({m.group(0) for m in EMPLOYMENT.finditer(text or "")}, key=str.lower)[:4]
    location = next((ln for ln in (text or "").splitlines() if LOCATION_LINE.search(ln) and len(ln) <= 80), "")
    return {"duties": pick("업무"), "required": pick("자격요건"), "preferred": pick("우대사항"),
            "conditions": conditions, "employment": employment, "location": location.strip(" -•·")}
