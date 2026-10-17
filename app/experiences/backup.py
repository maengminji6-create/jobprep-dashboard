"""내 데이터 저장·불러오기.

저장본(Snapshot) = 지금의 경험 + 자격증 + 사용 중인 강점 결과지 + 자소서 보관함을 통째로 담은 JSON.
- 앱 안에 저장해 두고 나중에 불러오기(불러오기 전 현재 상태는 자동 저장)
- .json 파일로 내려받아 보관하거나, 다른 컴퓨터·배포한 사이트에서 파일을 올려 그대로 옮기기
"""
import json
from datetime import datetime

from ..core.scoping import create_owned, owned
from ..extensions import db
from .models import CATEGORIES, Certificate, Experience, Snapshot

FORMAT = "growly-backup"
VERSION = 1
EXP_FIELDS = ("title", "category", "organization", "period", "role", "content", "strengths", "keywords", "reflection")
CERT_FIELDS = ("name", "score", "acquired", "issuer", "note")
STRENGTH_FIELDS = ("filename", "extracted_text", "parsed_json", "ai_json", "ai_role")
APP_FIELDS = ("company", "position", "role_code", "status", "applied_at", "deadline", "url", "company_info", "talent",
              "notes", "qa_json")
MAX_FILE_BYTES = 5 * 1024 * 1024


def build_data(include_strength: bool = True) -> dict:
    from ..applications.models import ApplicationRecord
    from ..strengths.services import latest_profile
    exps = owned(Experience).order_by(Experience.created_at).all()
    apps = owned(ApplicationRecord).order_by(ApplicationRecord.created_at).all()
    certs = owned(Certificate).order_by(Certificate.created_at).all()
    profile = latest_profile() if include_strength else None
    return {
        "format": FORMAT, "version": VERSION, "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "experiences": [{f: getattr(e, f) or "" for f in EXP_FIELDS} for e in exps],
        "certificates": [{f: getattr(c, f) or "" for f in CERT_FIELDS} for c in certs],
        "strength_profile": {f: getattr(profile, f) or "" for f in STRENGTH_FIELDS} if profile else None,
        "applications": [{f: getattr(a, f) or "" for f in APP_FIELDS} for a in apps],
    }


def save_snapshot(name: str, data: dict | None = None) -> Snapshot:
    data = data if data is not None else build_data()
    snap = create_owned(Snapshot, name=(name or "저장본").strip()[:120] or "저장본",
                        data_json=json.dumps(data, ensure_ascii=False),
                        exp_count=len(data.get("experiences", [])), cert_count=len(data.get("certificates", [])),
                        has_strength=bool(data.get("strength_profile")))
    return snap


def validate(data) -> dict:
    """올린 파일이 GROWLY 저장본인지 확인하고, 필드를 정리한 dict 를 돌려줍니다."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("GROWLY에서 내려받은 저장본(.json) 파일이 아니에요.")
    exps, certs = data.get("experiences") or [], data.get("certificates") or []
    if not isinstance(exps, list) or not isinstance(certs, list):
        raise ValueError("저장본 형식이 올바르지 않아요.")
    clean = {"format": FORMAT, "version": VERSION, "saved_at": str(data.get("saved_at", ""))[:20],
             "experiences": [], "certificates": [], "strength_profile": None, "applications": []}
    for e in exps:
        if isinstance(e, dict) and str(e.get("title", "")).strip():
            item = {f: str(e.get(f) or "") for f in EXP_FIELDS}
            item["category"] = item["category"] if item["category"] in CATEGORIES else "기타"
            clean["experiences"].append(item)
    for c in certs:
        if isinstance(c, dict) and str(c.get("name", "")).strip():
            clean["certificates"].append({f: str(c.get(f) or "") for f in CERT_FIELDS})
    for a in data.get("applications") or []:
        if isinstance(a, dict) and str(a.get("company", "")).strip():
            clean["applications"].append({f: str(a.get(f) or "") for f in APP_FIELDS})
    sp = data.get("strength_profile")
    if isinstance(sp, dict) and sp.get("extracted_text"):
        clean["strength_profile"] = {f: str(sp.get(f) or "") for f in STRENGTH_FIELDS}
    return clean


def restore(data: dict, experiences: bool = True, strength: bool = True, applications: bool = False) -> dict:
    """저장본을 지금 데이터로 불러옵니다. 불러오기 전 상태는 자동으로 저장본에 남깁니다. commit 은 호출한 쪽에서."""
    from ..strengths.models import StrengthProfile
    save_snapshot(f"불러오기 전 자동 저장 · {datetime.now():%m/%d %H:%M}")
    from ..applications.models import ApplicationRecord
    result = {"experiences": 0, "certificates": 0, "strength": False, "applications": 0}
    if experiences:
        for e in owned(Experience).all():
            db.session.delete(e)  # AI 코멘트·TOP 3 제외 기록도 함께 지워짐
        for c in owned(Certificate).all():
            db.session.delete(c)
        db.session.flush()
        for item in data.get("experiences", []):
            create_owned(Experience, source="manual", **{f: item.get(f, "")[:5000] if f not in ("title", "category", "organization", "period")
                                                        else item.get(f, "")[:200] for f in EXP_FIELDS})
            result["experiences"] += 1
        for item in data.get("certificates", []):
            create_owned(Certificate, **{f: item.get(f, "") for f in CERT_FIELDS})
            result["certificates"] += 1
    if applications and data.get("applications"):
        for a in owned(ApplicationRecord).all():
            db.session.delete(a)
        db.session.flush()
        for item in data["applications"]:
            create_owned(ApplicationRecord, **{f: item.get(f, "") for f in APP_FIELDS})
            result["applications"] += 1
    sp = data.get("strength_profile")
    if strength and sp:
        for p in owned(StrengthProfile).all():
            p.is_active = False
        create_owned(StrengthProfile, is_active=True, **{f: sp.get(f, "") for f in STRENGTH_FIELDS})
        result["strength"] = True
    return result
