from datetime import date, datetime


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def dday(target: date | None) -> str:
    if not target:
        return ""
    if isinstance(target, datetime):
        target = target.date()
    diff = (target - date.today()).days
    if diff == 0:
        return "D-DAY"
    return f"D-{diff}" if diff > 0 else f"D+{-diff}"
