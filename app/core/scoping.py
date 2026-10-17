"""'내 데이터만' 조회·수정하는 헬퍼. 사용자 데이터는 반드시 이 함수들로만 읽습니다."""
from flask import abort
from flask_login import current_user

from ..extensions import db


def owned(model):
    """현재 로그인 사용자의 행만 걸러낸 쿼리."""
    return db.session.query(model).filter(model.user_id == current_user.id)


def get_owned_or_404(model, obj_id):
    """남의 데이터면 존재 자체를 숨기기 위해 404를 돌려줍니다."""
    obj = owned(model).filter(model.id == obj_id).first()
    if obj is None:
        abort(404)
    return obj


def create_owned(model, **fields):
    """user_id 는 폼이 아니라 서버에서 채웁니다."""
    obj = model(user_id=current_user.id, **fields)
    db.session.add(obj)
    return obj
