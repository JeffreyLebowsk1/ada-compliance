"""
Flask web application for ADA Compliance Bot.

Routes
------
GET  /                          Landing page with audit submission form.
POST /audit                     Submit a new audit job; redirects to status page.
GET  /audit/<job_id>            Real-time status and progress page.
GET  /audit/<job_id>/stream     Server-Sent Events stream of progress messages.
GET  /audit/<job_id>/result     JSON summary of completed audit (for AJAX polling).
GET  /audit/<job_id>/report     View the full HTML accessibility report.
GET  /audit/<job_id>/report.json Download the full JSON report.

Running
-------
Development::

    flask --app ada_bot.webapp run --debug

Production (gunicorn)::

    gunicorn --bind 0.0.0.0:8080 --workers 4 --timeout 300 ada_bot.webapp:app
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
    url_for,
)

from .engine import AuditConfig, AuditEngine

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))

# ---------------------------------------------------------------------------
# In-memory job store  (LRU-capped at _MAX_JOBS to avoid unbounded growth)
# ---------------------------------------------------------------------------

_MAX_JOBS = 100
_jobs: OrderedDict[str, dict] = OrderedDict()
_jobs_lock = threading.Lock()

# Matches job IDs: alphanumeric only, 1–64 characters.
# Prevents path-traversal characters (/, .., %) while staying flexible enough
# for both production UUIDs (uuid4().hex) and shorter test IDs.
_JOB_ID_RE = re.compile(r"^[0-9a-zA-Z]{1,64}$")


def _is_valid_job_id(job_id: str) -> bool:
    """Return True if *job_id* looks like a valid job identifier."""
    return bool(_JOB_ID_RE.match(job_id))


def _store_job(job: dict) -> None:
    with _jobs_lock:
        _jobs[job["id"]] = job
        # Evict oldest jobs when the cap is exceeded
        while len(_jobs) > _MAX_JOBS:
            _jobs.popitem(last=False)


def _get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        return _jobs.get(job_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Landing page: form to submit a URL for auditing."""
    return render_template("web_index.html")


@app.route("/audit", methods=["POST"])
def start_audit():
    """Validate the form, create a background job, redirect to its status page."""
    raw_url = request.form.get("url", "").strip()
    if not raw_url:
        return render_template("web_index.html", error="Please enter a URL to audit."), 400

    # Prepend scheme if omitted
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    # Basic URL sanity check
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", raw_url):
        return render_template("web_index.html", error="That doesn't look like a valid URL."), 400

    # Parse audit options from form
    try:
        max_pages = max(1, min(int(request.form.get("max_pages", 25)), 500))
    except ValueError:
        max_pages = 25

    try:
        max_depth = max(1, min(int(request.form.get("max_depth", 3)), 15))
    except ValueError:
        max_depth = 3

    run_axe = request.form.get("run_axe") == "on"
    run_html = request.form.get("run_html", "on") != "off"
    run_color = request.form.get("run_color", "on") != "off"
    run_keyboard = request.form.get("run_keyboard", "on") != "off"
    run_aria = request.form.get("run_aria", "on") != "off"

    # Create temp output directory for this job's reports
    output_dir = tempfile.mkdtemp(prefix="ada_report_")

    job_id = uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "url": raw_url,
        "status": "running",   # "running" | "completed" | "error"
        "messages": [],
        "output_dir": output_dir,
        "report_data": None,
        "report_paths": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        # Summary fields populated on completion:
        "score": None,
        "total_pages": None,
        "total_issues": None,
        "by_severity": {},
    }
    _store_job(job)

    cfg = AuditConfig(
        url=raw_url,
        max_pages=max_pages,
        max_depth=max_depth,
        run_html_audit=run_html,
        run_color_audit=run_color,
        run_keyboard_audit=run_keyboard,
        run_aria_audit=run_aria,
        run_axe_audit=run_axe,
        run_vision_audit=False,
        output_dir=output_dir,
        on_progress=lambda msg: _append_message(job_id, msg),
    )

    thread = threading.Thread(target=_run_audit_job, args=(job_id, cfg), daemon=True)
    thread.start()

    return redirect(url_for("audit_status", job_id=job_id))


@app.route("/audit/<job_id>")
def audit_status(job_id: str):
    """Real-time status page.  JavaScript streams progress via SSE."""
    if not _is_valid_job_id(job_id):
        abort(404)
    job = _get_job(job_id)
    if not job:
        abort(404)
    return render_template("web_status.html", job=job)


@app.route("/audit/<job_id>/stream")
def audit_stream(job_id: str):
    """Server-Sent Events endpoint — streams progress messages to the browser."""
    if not _is_valid_job_id(job_id) or not _get_job(job_id):
        abort(404)

    def generate():
        idx = 0
        while True:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if not job:
                    break
                msgs = list(job["messages"])
                status = job["status"]

            # Send any new messages since last iteration
            while idx < len(msgs):
                line = msgs[idx].replace("\n", " ").replace("\r", "")
                yield f"data: {line}\n\n"
                idx += 1

            # When the job is done and all messages have been sent, close stream
            if status in ("completed", "error"):
                if idx >= len(msgs):
                    yield "data: __DONE__\n\n"
                    break

            time.sleep(0.15)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable nginx buffering
    }
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers=headers,
    )


@app.route("/audit/<job_id>/result")
def audit_result(job_id: str):
    """Return a JSON summary of the job — polled by the browser after __DONE__."""
    from flask import jsonify

    if not _is_valid_job_id(job_id):
        abort(404)
    job = _get_job(job_id)
    if not job:
        abort(404)

    return jsonify(
        {
            "id": job_id,
            "url": job["url"],
            "status": job["status"],
            "error": job.get("error"),
            "started_at": job["started_at"],
            "finished_at": job.get("finished_at"),
            "score": job.get("score"),
            "total_pages": job.get("total_pages"),
            "total_issues": job.get("total_issues"),
            "by_severity": job.get("by_severity", {}),
        }
    )


@app.route("/audit/<job_id>/report")
def audit_report_html(job_id: str):
    """Serve the full HTML accessibility report inline."""
    if not _is_valid_job_id(job_id):
        abort(404)
    job = _get_job(job_id)
    if not job or job["status"] != "completed" or not job.get("report_paths"):
        abort(404)
    return send_file(job["report_paths"]["html"], mimetype="text/html")


@app.route("/audit/<job_id>/report.json")
def audit_report_json(job_id: str):
    """Download the full JSON accessibility report."""
    if not _is_valid_job_id(job_id):
        abort(404)
    job = _get_job(job_id)
    if not job or job["status"] != "completed" or not job.get("report_paths"):
        abort(404)
    return send_file(
        job["report_paths"]["json"],
        mimetype="application/json",
        as_attachment=True,
        download_name="ada-report.json",
    )


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------

def _append_message(job_id: str, msg: str) -> None:
    """Thread-safe append of a progress message."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["messages"].append(msg)


def _run_audit_job(job_id: str, cfg: AuditConfig) -> None:
    """Execute the audit engine in a background thread."""
    try:
        report_data, paths = AuditEngine(cfg).run()
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "completed"
                job["report_data"] = report_data
                job["report_paths"] = paths
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                job["score"] = report_data.compliance_score
                job["total_pages"] = report_data.total_pages
                job["total_issues"] = report_data.total_issues
                job["by_severity"] = dict(report_data.by_severity)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        # Expected operational errors (I/O failures, bad data, etc.)
        _set_job_error(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        # Unexpected errors — log a traceback and surface a clean message
        import traceback
        tb = traceback.format_exc()
        app.logger.error("Unexpected error in audit job %s:\n%s", job_id, tb)
        _set_job_error(job_id, f"Unexpected error: {exc}")


def _set_job_error(job_id: str, message: str) -> None:
    """Mark a job as failed with an error message."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "error"
            job["error"] = message
            job["finished_at"] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Dev server entry-point  (used by `flask run` / direct invocation)
# ---------------------------------------------------------------------------

def run_dev_server() -> None:
    """Start the Flask development server on port 5000."""
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)


if __name__ == "__main__":
    run_dev_server()
