from flask import Blueprint

bp = Blueprint("experiences", __name__, url_prefix="/experiences")

from . import routes  # noqa: E402,F401
