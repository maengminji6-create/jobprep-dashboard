"""자격증·어학 → 직무별 관련도(0–100).

경험은 문장 속 키워드로 직무 적합도를 매기지만, 자격증은 이름만으로 어떤 직무에 쓰이는지가 정해져 있어
아래 표로 따로 평가합니다. 표에 없는 자격증은 이름·메모를 직무 키워드 사전으로 비교해 추정합니다.
자격증을 추가하려면 CERT_RULES 에 (이름에 들어가는 단어들, 직무별 관련도, 설명) 한 줄을 더하세요.
"""
import re

LANG_ROLES = {"overseas_sales": 75, "overseas_marketing": 70, "biz_dev": 65, "trade_support": 60, "forwarding": 55,
              "shipping_air": 55, "sourcing": 55, "sales_support": 50, "trade_admin": 50, "compliance": 40,
              "scm": 40, "trade_finance": 40, "customs": 35, "fta_origin": 35, "hr": 30, "biz_support": 30}

CERT_RULES = [
    (["국제무역사"], {"trade_admin": 100, "overseas_sales": 85, "trade_support": 80, "forwarding": 70, "fta_origin": 70,
                    "sourcing": 70, "sales_support": 70, "trade_finance": 70, "customs": 65, "biz_dev": 60,
                    "shipping_air": 60, "compliance": 60, "scm": 55, "overseas_marketing": 50, "biz_support": 35, "hr": 15},
     "인코텀즈·신용장·선적서류 등 무역 실무 전반을 안다는 증명"),
    (["무역영어"], {"trade_admin": 90, "overseas_sales": 85, "trade_support": 70, "sales_support": 65, "forwarding": 65,
                  "sourcing": 65, "trade_finance": 55, "biz_dev": 55, "overseas_marketing": 55, "shipping_air": 55,
                  "fta_origin": 50, "customs": 50, "compliance": 50, "scm": 45, "biz_support": 30, "hr": 15},
     "무역 서신·계약 영어와 무역 실무 용어 활용 능력"),
    (["관세사"], {"customs": 100, "fta_origin": 85, "compliance": 80, "trade_admin": 75, "forwarding": 60, "sourcing": 50,
                "trade_support": 60, "overseas_sales": 45},
     "통관·관세·품목분류 전문 자격"),
    (["원산지관리사", "원산지"], {"fta_origin": 100, "customs": 80, "trade_admin": 70, "compliance": 70, "sourcing": 50,
                           "trade_support": 55, "overseas_sales": 45},
     "FTA 원산지 판정·증명 실무 자격"),
    (["물류관리사"], {"forwarding": 95, "shipping_air": 85, "scm": 85, "sourcing": 55, "trade_admin": 55, "sales_support": 40},
     "물류·운송·보관 전반 이해"),
    (["보세사"], {"customs": 80, "forwarding": 75, "shipping_air": 60, "trade_admin": 50},
     "보세구역·보세화물 관리 자격"),
    (["외환전문역", "외환"], {"trade_finance": 100, "trade_admin": 60, "biz_support": 50, "overseas_sales": 35},
     "외환·무역금융(신용장·송금) 전문 지식"),
    (["유통관리사"], {"sales_support": 60, "scm": 55, "sourcing": 55, "overseas_marketing": 40, "overseas_sales": 35},
     "유통·구매·영업관리 기초 지식"),
    (["cpim", "cscp", "cpsm", "scmp", "공급망관리"], {"scm": 95, "sourcing": 85, "forwarding": 50, "trade_admin": 40},
     "국제 공급망·구매 관리 자격"),
    (["컴퓨터활용능력", "컴활", "mos", "itq", "엑셀"], {"biz_support": 70, "sales_support": 65, "trade_admin": 60, "scm": 50,
                                                "hr": 45, "sourcing": 45, "trade_finance": 40},
     "엑셀 등 사무 데이터 처리 능력"),
    (["erp", "sap"], {"scm": 70, "biz_support": 70, "sales_support": 60, "trade_admin": 60, "sourcing": 55, "hr": 35},
     "ERP 시스템으로 주문·재고·회계를 다루는 능력"),
    (["전산회계", "전산세무", "fat", "tat", "재경관리사", "회계관리", "회계"],
     {"biz_support": 90, "trade_finance": 65, "sales_support": 40, "hr": 30},
     "회계·세무 실무 능력"),
    (["사회조사분석사", "adsp", "sqld", "빅데이터", "데이터분석"],
     {"overseas_marketing": 60, "scm": 60, "biz_dev": 55, "biz_support": 50, "hr": 40, "sales_support": 45},
     "데이터 수집·분석 능력"),
    (["gtq", "구글애널리틱스", "google analytics", "마케팅", "검색광고"], {"overseas_marketing": 70, "biz_dev": 40},
     "디지털 마케팅·콘텐츠 제작 능력"),
    (["직업상담사", "인적자원", "공인노무사", "노무", "hrm", "phr", "shrm"], {"hr": 95, "biz_support": 50},
     "인사·노무·채용 전문 지식"),
    (["토익스피킹", "toeic speaking", "토스", "opic", "오픽", "toefl", "토플", "ielts", "teps", "텝스", "toeic", "토익",
      "hsk", "jlpt", "jpt", "flex", "dele", "delf", "zd", "tocfl", "bct"], LANG_ROLES,
     "외국어 능력(해외 바이어·현지 소통)"),
]


def _level(name: str, score: str) -> float:
    """어학 점수·등급에 따라 관련도를 조정(높을수록 그대로, 낮을수록 줄임). 점수가 없으면 0.85."""
    low, s = name.lower(), (score or "").upper().replace(" ", "")
    if any(k in low for k in ("toeic", "토익")) and not any(k in low for k in ("speaking", "스피킹")):
        m = re.search(r"\d{3}", s)
        if m:
            n = int(m.group())
            return 1.0 if n >= 900 else 0.9 if n >= 850 else 0.8 if n >= 750 else 0.6
    if any(k in low for k in ("opic", "오픽")):
        for grade, f in (("AL", 1.0), ("IH", 0.95), ("IM3", 0.85), ("IM2", 0.8), ("IM", 0.75), ("IL", 0.6)):
            if grade in s:
                return f
    if any(k in low for k in ("hsk", "jlpt")):
        m = re.search(r"(\d)", s)
        if m:
            n = int(m.group())
            return 1.0 if ("hsk" in low and n >= 5) or ("jlpt" in low and n <= 2) else 0.75
    return 0.85


def evaluate(name: str, score: str = "", note: str = "") -> dict:
    """{"roles": {직무코드: 관련도}, "reason": 설명, "known": 표에 있는 자격증인지}"""
    low = f"{name} {note}".lower().replace(" ", "")
    for words, roles, reason in CERT_RULES:
        if any(w.replace(" ", "") in low for w in words):
            is_lang = roles is LANG_ROLES
            factor = _level(name, score) if is_lang else (0.9 if "2급" in name or "3급" in name else 1.0)
            return {"roles": {k: round(v * factor) for k, v in roles.items()}, "reason": reason, "known": True}
    # 표에 없는 자격증: 이름·메모를 직무 키워드 사전과 비교
    from ..experiences.analyzer import role_scores
    scores = role_scores(f"{name}\n{note}")
    return {"roles": {k: min(60, v["score"]) for k, v in scores.items() if v["score"] > 0},
            "reason": "이름·메모로 추정한 관련 직무", "known": False}


def cert_bonus(evaluations: list[dict], role_code: str) -> int:
    """직무 적합도에 더하는 자격증 가산점: 그 직무와 관련도가 높은 자격증 2개 × 15% (최대 25점)."""
    top = sorted((ev["roles"].get(role_code, 0) for ev in evaluations), reverse=True)[:2]
    return min(25, round(sum(top) * 0.15))
