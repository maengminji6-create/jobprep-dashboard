"""가장 중요한 테스트: 사용자 A는 사용자 B의 데이터를 보거나 고칠 수 없다."""
from app.experiences.models import Experience, PostingAnalysis
from app.extensions import db

from .conftest import login, make_user


def test_user_cannot_access_others_data(app, client):
    a = make_user("a@test.com")
    b = make_user("b@test.com")
    exp = Experience(user_id=b.id, title="B의 경험", content="비밀")
    pa = PostingAnalysis(user_id=b.id, title="B의 공고", result_json="{}")
    db.session.add_all([exp, pa])
    db.session.commit()

    login(client, a.email)
    assert client.get(f"/experiences/{exp.id}/edit").status_code == 404
    assert client.post(f"/experiences/{exp.id}/delete").status_code == 404
    assert client.get(f"/experiences/posting/{pa.id}").status_code == 404
    # 남의 경험에 내용 덧붙이기 시도
    assert client.post("/experiences/save", data={"target_id": exp.id, "role": "끼워넣기"}).status_code == 404
    # 같은 제목으로 저장해도 남의 경험과 합쳐지지 않고 내 경험이 새로 생김
    client.post("/experiences/save", data={"title": "B의 경험", "role": "내 역할"})
    db.session.refresh(exp)
    assert "내 역할" not in (exp.role or "")

    page = client.get("/experiences/").get_data(as_text=True)
    assert "비밀" not in page
