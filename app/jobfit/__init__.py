from flask import Blueprint

bp = Blueprint("jobfit", __name__, url_prefix="/jobfit")

from . import routes  # noqa: E402,F401
