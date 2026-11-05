from flask import Blueprint

bp = Blueprint("interview", __name__, url_prefix="/interview")

from . import routes  # noqa: E402,F401
