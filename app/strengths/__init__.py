from flask import Blueprint

bp = Blueprint("strengths", __name__, url_prefix="/strengths")

from . import routes  # noqa: E402,F401
