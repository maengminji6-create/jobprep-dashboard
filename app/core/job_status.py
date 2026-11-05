"""지원 진행 상태: 채용공고(공고 매칭)와 지원 기록(자소서 보관함)이 함께 쓰는 단계."""
from datetime import date

STATUSES = ["관심 공고", "지원 예정", "서류 준비 중", "지원 완료", "서류 합격", "면접 진행", "최종 합격", "불합격"]
DONE = {"최종 합격", "불합격"}  # 마감 알림이 필요 없는 상태
# 예전 자소서 보관함 상태 → 새 단계(예전 저장본 파일을 불러올 때도 사용)
LEGACY = {"작성 중": "서류 준비 중", "제출 완료": "지원 완료"}


def normalize(status: str | None, default: str = STATUSES[0]) -> str:
    s = (status or "").strip()
    s = LEGACY.get(s, s)
    return s if s in STATUSES else default


def d_day(deadline: date | None, today: date | None = None) -> int | None:
    """마감까지 남은 날(오늘 마감 = 0, 지남 = 음수). 마감일이 없으면 None."""
    if not deadline:
        return None
    return (deadline - (today or date.today())).days


def urgency(deadline: date | None, status: str = "", today: date | None = None) -> str:
    """화면 강조: 'over'(지남) · 'soon'(3일 이내) · 'week'(7일 이내) · ''(여유 또는 해당 없음)."""
    left = d_day(deadline, today)
    if left is None or status in DONE or status in ("지원 완료", "서류 합격", "면접 진행"):
        return ""
    if left < 0:
        return "over"
    return "soon" if left <= 3 else ("week" if left <= 7 else "")
