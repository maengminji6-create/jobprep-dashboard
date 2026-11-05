from flask import render_template, request, session
from flask_login import login_required

from ..analysis.services import links_of, saved_analyses
from ..core.job_competencies import JOB_BY_CODE, JOBS
from ..core.scoping import owned
from ..experiences.models import Experience
from ..strengths.services import latest_profile
from . import bp
from .services import STATUS_LABELS, job_view


@bp.route("/")
@login_required
def index():
    code = request.args.get("job")
    if code in JOB_BY_CODE:
        session["job_role"] = code  # 고른 직무 기억
    else:
        code = session.get("job_role") if session.get("job_role") in JOB_BY_CODE else JOBS[0]["code"]
    exps = owned(Experience).order_by(Experience.created_at).all()
    saved = saved_analyses()
    profile = latest_profile()
    view = job_view(code, exps, saved, profile, links_of(profile) if profile else [])
    return render_template("jobfit/index.html", jobs=JOBS, code=code, view=view, exps=exps,
                           analyzed=sum(1 for e in exps if e.id in saved), profile=profile, labels=STATUS_LABELS)
