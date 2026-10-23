import json
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from qa_agent.agents.healer import heal_many
from qa_agent.config import Settings, get_effective_settings, get_settings
from qa_agent.core.session import run_qa_session
from qa_agent.db.config_service import ConfigService
from qa_agent.db.log_service import LogService
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.utils.coerce import coerce_value
from qa_agent.web.jobs import JOBS, run_async_job
from qa_agent.web.scanning import load_report, scan_generated_scripts, scan_reports

bp = Blueprint("main", __name__, template_folder="templates", static_folder="static")

PROVIDERS = ["groq", "google", "anthropic", "openai", "huggingface"]
SECRET_SUFFIX = "_api_key"
MASK = "•••• set"
# Dict-typed Settings fields -- edited as raw JSON textareas in the config form.
JSON_FIELDS = {
    "provider_limits",
    "node_candidate_providers",
    "provider_cost_weights",
    "loop_a_pid_gains",
    "loop_b_pid_gains",
}


@bp.route("/")
def index():
    settings = get_effective_settings()
    reports_dir = Path(settings.reports_dir)
    report_count = len(scan_reports(reports_dir))
    script_count = len(scan_generated_scripts(reports_dir, settings.generated_tests_dirname))
    config_enabled = ConfigService.from_settings(get_settings()).enabled
    return render_template(
        "index.html",
        report_count=report_count,
        script_count=script_count,
        config_enabled=config_enabled,
    )


@bp.route("/runs/new", methods=["GET", "POST"])
def new_run():
    settings = get_effective_settings()
    if request.method == "GET":
        return render_template("new_run.html", providers=PROVIDERS, settings=settings)

    url = request.form.get("url", "").strip()
    requirements = request.form.get("requirements_text", "").strip()
    upload = request.files.get("requirements_file")
    if upload and upload.filename:
        requirements = upload.read().decode("utf-8")

    if not url or not requirements:
        flash("Target URL and requirements are both required.")
        return redirect(url_for("main.new_run"))

    job = JOBS.create("run", params={"target_url": url})
    kwargs = {
        "target_url": url,
        "requirements": requirements,
        "provider": request.form.get("provider") or None,
        "model": request.form.get("model") or None,
        "headless": "headless" in request.form,
        "max_retries": int(request.form.get("max_retries") or settings.max_retries),
        "reports_dir": settings.reports_dir,
        "generate_regression_scripts": "generate_regression_scripts" in request.form,
    }
    run_async_job(JOBS, job, lambda: run_qa_session(**kwargs))
    return redirect(url_for("main.job_status", job_id=job.job_id))


@bp.route("/jobs/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if job is None:
        abort(404)
    return render_template("job_status.html", job=job)


@bp.route("/api/jobs/<job_id>")
def job_status_api(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify(error="unknown job"), 404
    return jsonify(
        job_id=job.job_id,
        kind=job.kind,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
    )


@bp.route("/reports")
def reports_list():
    settings = get_effective_settings()
    reports = scan_reports(Path(settings.reports_dir))
    return render_template("reports_list.html", reports=reports)


@bp.route("/reports/<run_id>")
def report_detail(run_id):
    settings = get_effective_settings()
    report = load_report(Path(settings.reports_dir), run_id)
    if report is None:
        abort(404)
    return render_template("report_detail.html", report=report)


@bp.route("/reports/<run_id>/screenshots/<path:filename>")
def report_screenshot(run_id, filename):
    settings = get_effective_settings()
    screenshot_dir = Path(settings.reports_dir) / run_id / "screenshots"
    return send_from_directory(screenshot_dir, filename)


@bp.route("/config", methods=["GET", "POST"])
def config_view():
    bootstrap = get_settings()
    service = ConfigService.from_settings(bootstrap)

    if request.method == "POST":
        if not service.enabled:
            abort(400)
        for name in Settings.model_fields:
            if request.form.get(f"delete_{name}"):
                service.delete(name)
                continue
            raw = request.form.get(name)
            if raw is None or raw == "" or raw == MASK:
                continue
            if name in JSON_FIELDS:
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    flash(f"{name}: not valid JSON, left unchanged.")
                    continue
            else:
                value = coerce_value(raw)
            service.set(name, value)
        flash("Settings saved.")
        return redirect(url_for("main.config_view"))

    effective = get_effective_settings(bootstrap)
    overrides = service.get_all() if service.enabled else {}
    return render_template(
        "config.html",
        settings=effective,
        overrides=overrides,
        service_enabled=service.enabled,
        mask=MASK,
        secret_suffix=SECRET_SUFFIX,
        json_fields=JSON_FIELDS,
    )


@bp.route("/healer", methods=["GET", "POST"])
def healer_view():
    settings = get_effective_settings()
    reports_root = Path(settings.reports_dir).resolve()

    if request.method == "POST":
        targets = []
        for raw in request.form.getlist("script"):
            candidate = Path(raw).resolve()
            if not candidate.is_relative_to(reports_root):
                abort(400)
            targets.append(candidate)
        if not targets:
            flash("Select at least one script to heal.")
            return redirect(url_for("main.healer_view"))

        provider = request.form.get("provider") or None
        model = request.form.get("model") or None
        router = ModelRouter.from_settings(settings, provider=provider, model=model)
        log_service = LogService.from_settings(settings)

        job = JOBS.create("heal", params={"scripts": [str(p) for p in targets]})
        run_async_job(JOBS, job, lambda: heal_many(targets, router, log_service, settings))
        return redirect(url_for("main.job_status", job_id=job.job_id))

    scripts = scan_generated_scripts(reports_root, settings.generated_tests_dirname)
    return render_template("healer.html", scripts=scripts, providers=PROVIDERS)
