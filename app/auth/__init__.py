from flask import Blueprint

bp = Blueprint("auth", __name__, url_prefix="/me")

from . import routes  # noqa: E402,F401
