"""공고 산업군 분류. 공고 글에 나오는 단어로 자동 분류하고, 화면에서 직접 바꿀 수도 있어요.
산업을 추가하려면 INDUSTRIES 에 (코드, 이름, 단서 단어들) 한 줄을 더하세요."""

INDUSTRIES = [
    ("trading", "종합상사·무역", ["상사", "무역회사", "수출입", "트레이딩", "trading", "오퍼상", "무역"]),
    ("logistics", "물류·해운·항공", ["물류", "포워딩", "해운", "선사", "항공화물", "택배", "3pl", "logistics", "운송"]),
    ("beauty", "화장품·뷰티", ["화장품", "뷰티", "코스메틱", "스킨케어", "k-뷰티", "k뷰티", "cosmetic", "odm", "oem"]),
    ("food", "식품·외식", ["식품", "음료", "외식", "f&b", "농산물", "수산물", "제과", "주류"]),
    ("electronics", "전자·반도체·IT기기", ["반도체", "전자", "가전", "디스플레이", "배터리", "부품", "semiconductor"]),
    ("auto", "자동차·기계", ["자동차", "완성차", "모빌리티", "기계", "장비", "타이어"]),
    ("materials", "철강·화학·에너지", ["철강", "화학", "소재", "석유", "정유", "에너지", "가스", "플라스틱"]),
    ("fashion", "패션·섬유", ["패션", "의류", "섬유", "어패럴", "apparel", "잡화"]),
    ("retail", "유통·이커머스", ["유통", "이커머스", "커머스", "리테일", "마켓", "쇼핑", "아마존", "쿠팡", "md"]),
    ("travel", "여행·호텔·플랫폼", ["여행", "호텔", "숙박", "항공권", "ota", "관광", "예약"]),
    ("it", "IT·플랫폼·서비스", ["플랫폼", "소프트웨어", "sw", "saas", "it", "앱", "데이터", "ai"]),
    ("finance", "금융·보험", ["은행", "금융", "보험", "증권", "카드", "외환"]),
    ("public", "공공기관·협회", ["공사", "공단", "진흥원", "kotra", "무역협회", "공공기관", "재단"]),
    ("etc", "기타", []),
]
INDUSTRY_BY_CODE = {c: n for c, n, _ in INDUSTRIES}


def detect_industry(text: str) -> str:
    """단서 단어가 가장 많이 나오는 산업 코드. 없으면 'etc'."""
    import re
    low = (text or "").lower()
    best, best_n = "etc", 0
    for code, _name, words in INDUSTRIES:
        n = 0
        for w in words:
            # 짧은 영문 단서(it, ai, md, sw)는 단어 경계로만
            n += len(re.findall(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low)) if w.isascii() and len(w) <= 3 else low.count(w)
        if n > best_n:
            best, best_n = code, n
    return best
