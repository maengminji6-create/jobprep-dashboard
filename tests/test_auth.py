from .conftest import login


def test_register_and_home(client):
    r = client.post("/auth/register", data={"email": "new@test.com", "name": "신입", "password": "password123"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "경험 분석" in r.get_data(as_text=True)


def test_login_required(client):
    r = client.get("/experiences/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_wrong_password(client, user):
    r = login(client, user.email, "wrong-password")
    assert "올바르지 않습니다" in r.get_data(as_text=True)


def test_all_pages_render(auth_client):
    assert auth_client.get("/").status_code == 302  # 첫 화면 = 경험 분석
    for url in ["/experiences/", "/experiences/posting"]:
        assert auth_client.get(url).status_code == 200, url
    for url in ["/schedule/", "/jobs/", "/pipeline/", "/news/refresh"]:  # 정리한 탭
        assert auth_client.get(url).status_code == 404, url
