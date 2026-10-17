"""이미지로 된 공고: 이미지 고르기 · 긴 이미지 자르기 · 캡처 업로드/링크 이미지를 AI(가짜)로 읽어 분석에 반영."""
import io

from bs4 import BeautifulSoup
from PIL import Image

from app.experiences import posting_images as pim
from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db

VISION = {
    "company": "한미약품", "title": "2026 하반기 채용", "period": "10.20 ~ 11.03",
    "positions": [{"division": "본사", "name": "구매", "type": "경력",
                   "duties": ["구매 전략 수립 및 조달 운영 관리", "공급업체 관리 및 계약 협상"],
                   "requirements": ["학사 이상", "영어 능통자(구술, 서술)"],
                   "preferred": ["구매/무역 관련 교육 이수 및 자격증 소지자", "MS Office 활용 능력 우수자"]}],
    "common": {"requirements": [], "preferred": []}, "process": ["서류전형", "면접"], "other": [],
}


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_collect_and_chunk():
    html = ('<div><img src="/logo.png"><img src="/a.jpg" width="900"><img src="/icon_x.png">'
            '<img data-src="https://cdn.x.com/posting.jpg"><img src="/b.svg"><img src="/small.jpg" width="40"></div>')
    urls = pim.collect_image_urls(BeautifulSoup(html, "html.parser"), "https://site.com/job/1")
    assert urls == ["https://site.com/a.jpg", "https://cdn.x.com/posting.jpg"]
    chunks = pim.to_chunks([_png(2200, 6000)])  # 가로 1100으로 줄이면 세로 3000 → 1400씩 겹쳐 3조각
    assert len(chunks) == 3 and all(c.startswith("data:image/jpeg;base64,") for c in chunks)
    assert pim.is_posting_sized(_png(800, 1200)) and not pim.is_posting_sized(_png(120, 60))
    text = pim.vision_to_text(VISION)
    assert "[모집부문] 본사 · 구매 · 경력" in text and "우대사항\n- 구매/무역 관련 교육 이수 및 자격증 소지자" in text


def test_upload_screenshot_is_read_and_matched(app, auth_client, user, monkeypatch):
    db.session.add(Experience(user_id=user.id, title="소싱 인턴", category="인턴·실무",
                              role="공급업체 단가 협상과 발주, 구매 계약 서류 관리, 영어 이메일 응대",
                              content="", strengths="", keywords="", reflection=""))
    db.session.commit()
    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    seen = {}

    def fake(chunks):
        seen["n"] = len(chunks)
        return VISION
    monkeypatch.setattr(ai_client, "read_posting_images", fake)
    r = auth_client.post("/experiences/posting", data={"images": [(io.BytesIO(_png(900, 1600)), "posting.png")]},
                         content_type="multipart/form-data", follow_redirects=True)
    page = r.get_data(as_text=True)
    assert seen["n"] == 2 and "이미지 속 공고까지 읽어" in page
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    assert pa.company == "한미약품" and pa.vision["positions"][0]["name"] == "구매"
    assert "소싱 인턴" in [x["title"] for x in pa.result["recommendations"]]  # 이미지 속 '구매·공급업체'로 매칭
    assert "이미지에서 읽은 공고" in page, "label"
    assert "pos-card" in page, "card"
    import re
    assert "구매 전략 수립" in re.sub(r"<[^>]+>", "", page), "duty"
    assert "<mark" in page.split("pos-card")[1]  # 이미지 속 직무내용도 내 경험과 겹치면 강조
    assert pa.result["main_role"] == "sourcing"


def test_link_images_without_key_shows_notice(app, auth_client, user, monkeypatch):
    db.session.add(Experience(user_id=user.id, title="무역 인턴", category="인턴·실무", role="수출 오더 관리, 해외 바이어 응대",
                              content="", strengths="", keywords="", reflection=""))
    db.session.commit()
    import app.experiences.routes as routes
    text = ("한빛무역 해외영업 채용\n주요업무\n- 해외 바이어 발굴 및 수출 오더 관리\n자격요건\n- 영어 가능자\n우대사항\n- 무역영어 자격 보유자\n"
            "근무조건\n- 서울 본사 정규직, 주 5일 근무, 4대보험 및 성과급 지급")
    monkeypatch.setattr(routes, "fetch_posting_full", lambda url: {"title": "공고", "text": text,
                                                                    "images": ["https://example.com/p.jpg"]})
    monkeypatch.setattr(pim, "download_image", lambda url: _png(900, 2000))
    r = auth_client.post("/experiences/posting", data={"url": "https://example.com/job"}, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "OPENAI_API_KEY" in page
    pa = db.session.query(PostingAnalysis).filter_by(user_id=user.id).one()
    assert pa.images == ["https://example.com/p.jpg"] and not pa.vision
    assert "본문 이미지가 1장" in page and "원본 이미지 1장 보기" in page


def test_old_posting_rereads_link_images_and_keeps_vision(app, auth_client, user, monkeypatch):
    """이미지 읽기 전에 저장한 공고: 링크를 다시 열어 이미지를 찾아 읽고, 다시 열어도 이미지에서 읽은 내용은 지워지지 않음."""
    db.session.add(Experience(user_id=user.id, title="소싱 인턴", category="인턴·실무",
                              role="공급업체 단가 협상과 발주, 구매 계약 서류 관리", content="", strengths="", keywords="",
                              reflection=""))
    pa = PostingAnalysis(user_id=user.id, url="https://example.com/job", title="한미그룹 공채",
                         posting_text="[모집분야]\n-[한미약품] 구매\n-[한미약품] 해외영업", result_json="{}")
    db.session.add(pa)
    db.session.commit()
    page = auth_client.get(f"/experiences/posting/{pa.id}").get_data(as_text=True)
    assert "링크에서 본문 이미지를 찾아" in page
    import app.experiences.routes as routes
    from app.integrations import ai_client
    app.config["OPENAI_API_KEY"] = "test-key"
    monkeypatch.setattr(routes, "fetch_posting_full", lambda url: {"title": "", "text": "", "images": ["https://example.com/p.jpg"]})
    monkeypatch.setattr(pim, "download_image", lambda url: _png(900, 1600))
    monkeypatch.setattr(ai_client, "read_posting_images", lambda chunks: VISION)
    auth_client.post(f"/experiences/posting/{pa.id}/read-images")
    db.session.refresh(pa)
    assert pa.images == ["https://example.com/p.jpg"] and pa.vision["positions"][0]["name"] == "구매"
    auth_client.get(f"/experiences/posting/{pa.id}")
    auth_client.post(f"/experiences/posting/{pa.id}/reanalyze")
    db.session.refresh(pa)
    assert pim.VISION_MARK in pa.posting_text and "구매 전략 수립" in pa.posting_text
    assert "소싱 인턴" in [r["title"] for r in pa.result["recommendations"]]
