"""이력 PDF: 긴 글을 문단 · 목록 · 머리말로 나눠 읽기 좋게."""
from app.core.text_format import text_blocks


def test_blocks_split_structure():
    text = ("/<대시보드 설명>\n- AI제형 모델링: 개발요청서 AI 들려서 예상 제형 시각화\n- 원가/마진 시뮬레이션\n\n"
            "강점: 결정한 일을 빠르게 실행\n\n약점: 체력(오전 10:00부터)\n"
            "1. 팀장의 역할: 팀원 의견을 취합\n2. 프로젝트 성과: 현직자 인터뷰")
    b = text_blocks(text)
    assert [x["kind"] for x in b] == ["h", "ul", "p", "p", "ol"]
    assert b[0]["text"] == "대시보드 설명"
    assert b[1]["items"][0] == {"lead": "AI제형 모델링", "text": "개발요청서 AI 들려서 예상 제형 시각화"}
    assert b[2]["lines"][0]["lead"] == "강점"
    assert b[3]["lines"][0]["lead"] == "약점" and "10:00" in b[3]["lines"][0]["text"]
    assert [i["n"] for i in b[4]["items"]] == [1, 2] and b[4]["items"][1]["lead"] == "프로젝트 성과"


def test_heading_markers_and_semicolon():
    b = text_blocks("<대시보드 설명>/\n- 규제; R&D 검수 지원\n/<대시보드 설명>\n끝")
    assert [x["kind"] for x in b] == ["h", "ul", "p"]
    assert b[1]["items"][0]["lead"] == "규제"


def test_no_false_leads():
    assert text_blocks("자세한 건 https://example.com 참고")[0]["lines"][0]["lead"] is None
    assert text_blocks("회의는 10:30 에 시작")[0]["lines"][0]["lead"] is None
    assert text_blocks("") == [] and text_blocks(None) == []


def test_report_renders_structured(client):
    client.post("/experiences/save", data={"title": "부트캠프 프로젝트",
                                           "role": "1. 팀장의 역할: 의견 취합\n2. 성과: 인터뷰 진행"})
    page = client.get("/experiences/report").get_data(as_text=True)
    assert '<li value="2"><b class="r-lead">성과</b> 인터뷰 진행</li>' in page


def test_report_escapes_html(client):
    client.post("/experiences/save", data={"title": "x", "role": "- <script>alert(1)</script>"})
    page = client.get("/experiences/report").get_data(as_text=True)
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
