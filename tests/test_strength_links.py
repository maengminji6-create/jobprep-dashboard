"""강점 연결: 강점을 증명하는 내 문장 · 활용할 직무 · 자소서 소재 · 연결된 경험 없음 표시 · 직접 입력."""
from app.experiences.models import Experience
from app.extensions import db
from app.strengths.models import StrengthProfile
from app.strengths.services import link_strengths, parse_manual

from .conftest import login, make_user


class _Exp:
    def __init__(self, i, title, text, keywords="", strengths="", competencies=""):
        self.id, self.title, self.full_text = i, title, text
        self.keywords, self.strengths, self.competencies, self.category = keywords, strengths, competencies, "기타"


def test_link_gives_action_roles_and_essay_or_says_none():
    exps = [_Exp(1, "AX마스터", "팀장으로 회의록을 노션에 정리하고 역할배분을 했다.\n마감 전 체크리스트로 꼼꼼하게 점검했다.")]
    linked = {s["name"]: s for s in link_strengths([{"name": "신중함"}, {"name": "창의성"}], exps)}
    careful = linked["신중함"]
    assert careful["matches"][0]["action"] == "마감 전 체크리스트로 꼼꼼하게 점검했다."  # 글에 있는 그대로
    assert len(careful["roles"]) == 3  # 신중함 → 대응표의 직무 3개
    assert careful["essay"]["question"] == "직무역량·전문성" and careful["essay"]["title"] == "AX마스터"
    none = linked["창의성"]
    assert none["matches"] == [] and none["roles"] == [] and none["essay"] is None  # 근거 없으면 추천도 없음


def test_parse_manual_formats():
    got = parse_manual("1. 신중함: 잘못될 일을 미리 살펴요\n효과성 - 더 나은 방법\n주도")
    assert [s["name"] for s in got["strengths"]] == ["신중함", "효과성", "주도"]
    assert got["strengths"][0]["summary"] == "잘못될 일을 미리 살펴요" and got["method"] == "manual"
    assert [s["name"] for s in parse_manual("신중함, 효과성")["strengths"]] == ["신중함", "효과성"]
    assert parse_manual("   ")["strengths"] == []


def test_manual_input_saves_profile_and_page_shows_links(auth_client, user):
    db.session.add(Experience(user_id=user.id, title="AX마스터", category="프로젝트",
                              role="마감 전 체크리스트로 꼼꼼하게 점검했다.", content="", strengths="", keywords="",
                              reflection=""))
    db.session.commit()
    page = auth_client.post("/strengths/manual", data={"manual": "신중함: 잘못될 일을 미리 살펴요\n창의성"},
                            follow_redirects=True).get_data(as_text=True)
    assert "강점 2개를 저장했어요" in page
    assert "강점을 증명하는 행동" in page and "체크리스트로" in page and "자소서 소재" in page
    assert "연결된 경험 없음" in page  # 창의성은 근거가 없음
    prof = db.session.query(StrengthProfile).filter_by(user_id=user.id).one()
    assert prof.is_active and prof.filename == "직접 입력한 강점"


def test_manual_empty_is_rejected(auth_client, user):
    r = auth_client.post("/strengths/manual", data={"manual": " "}, follow_redirects=True)
    assert "한 줄에 하나씩" in r.get_data(as_text=True)


def test_manual_profile_is_mine_only(app, client):
    a, b = make_user("a@test.com"), make_user("b@test.com")
    login(client, a.email)
    client.post("/strengths/manual", data={"manual": "A만의 강점"})
    other = app.test_client()  # B는 다른 브라우저
    login(other, b.email)
    assert "A만의 강점" not in other.get("/strengths/").get_data(as_text=True)
