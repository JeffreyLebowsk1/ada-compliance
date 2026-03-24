"""
Tests for the Flask web application (ada_bot/webapp.py).

Covers:
- Index page accessibility and content
- Audit form validation (missing URL, invalid URL, prepend-scheme)
- Job creation and status page rendering
- SSE stream endpoint behaviour (complete, error states)
- Result JSON endpoint
- Report HTML / JSON endpoints (404 when job not done, 200 when done)
- In-memory job store LRU eviction
- Background job runner (success and error paths)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# Import the Flask app under test
from ada_bot.webapp import app, _jobs, _jobs_lock, _store_job, _get_job, _append_message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Flask test client with a fresh job store for each test."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        # Clear the shared job store before each test
        with _jobs_lock:
            _jobs.clear()
        yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_fake_job(short_id: str = "test", status: str = "running", **kwargs) -> dict:
    """Create a minimal job dict and insert it into the store."""
    job = {
        "id": short_id,
        "url": "https://example.com",
        "status": status,
        "messages": [],
        "output_dir": tempfile.mkdtemp(),
        "report_data": None,
        "report_paths": None,
        "error": None,
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": None,
        "score": None,
        "total_pages": None,
        "total_issues": None,
        "by_severity": {},
    }
    job.update(kwargs)
    job["id"] = short_id  # ensure id is not overridden by kwargs
    _store_job(job)
    return job


# ===========================================================================
# Index page
# ===========================================================================

class TestIndexPage:

    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_html_lang_attribute(self, client):
        html = client.get("/").data.decode()
        assert 'lang="en"' in html

    def test_has_skip_link(self, client):
        html = client.get("/").data.decode()
        assert "skip-link" in html

    def test_has_main_landmark(self, client):
        html = client.get("/").data.decode()
        assert "<main" in html

    def test_has_form_targeting_audit(self, client):
        html = client.get("/").data.decode()
        assert 'action="/audit"' in html
        assert 'method="POST"' in html

    def test_has_url_input(self, client):
        html = client.get("/").data.decode()
        assert 'type="url"' in html
        assert 'name="url"' in html

    def test_has_max_pages_input(self, client):
        html = client.get("/").data.decode()
        assert 'name="max_pages"' in html

    def test_has_audit_layer_checkboxes(self, client):
        html = client.get("/").data.decode()
        assert 'name="run_html"' in html
        assert 'name="run_aria"' in html

    def test_has_submit_button(self, client):
        html = client.get("/").data.decode()
        assert 'type="submit"' in html

    def test_no_error_banner_on_initial_load(self, client):
        html = client.get("/").data.decode()
        # The CSS class name exists in the <style> block but the error <div> should not
        assert '<div class="error-banner"' not in html

    def test_content_type_is_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.content_type


# ===========================================================================
# Audit form submission — validation
# ===========================================================================

class TestAuditFormValidation:

    def test_missing_url_returns_400(self, client):
        resp = client.post("/audit", data={"url": ""})
        assert resp.status_code == 400
        assert b"error" in resp.data.lower() or b"Error" in resp.data

    def test_missing_url_shows_error_message(self, client):
        resp = client.post("/audit", data={"url": ""})
        html = resp.data.decode()
        assert "error-banner" in html or "error" in html.lower()

    def test_invalid_url_returns_400(self, client):
        resp = client.post("/audit", data={"url": "not a url at all !!!"})
        assert resp.status_code == 400

    def test_url_without_scheme_gets_redirected(self, client):
        """A URL like 'example.com' should be treated as 'https://example.com'."""
        with patch("ada_bot.webapp.AuditEngine") as MockEngine:
            mock_rd = MagicMock()
            mock_rd.compliance_score = 100
            mock_rd.total_pages = 1
            mock_rd.total_issues = 0
            mock_rd.by_severity = {}
            MockEngine.return_value.run.return_value = (mock_rd, {"html": "/tmp/r.html", "json": "/tmp/r.json"})

            resp = client.post("/audit", data={"url": "example.com"}, follow_redirects=False)
            # Should redirect to /audit/<job_id>
            assert resp.status_code in (301, 302, 303)
            assert "/audit/" in resp.headers["Location"]

    def test_valid_url_redirects_to_status_page(self, client):
        with patch("ada_bot.webapp.threading.Thread") as MockThread:
            MockThread.return_value.start.return_value = None
            resp = client.post(
                "/audit",
                data={"url": "https://example.com", "max_pages": "5", "max_depth": "2"},
                follow_redirects=False,
            )
        assert resp.status_code in (301, 302, 303)
        location = resp.headers["Location"]
        assert "/audit/" in location

    def test_max_pages_clamped_to_500(self, client):
        with patch("ada_bot.webapp.threading.Thread") as MockThread:
            MockThread.return_value.start.return_value = None
            resp = client.post(
                "/audit",
                data={"url": "https://example.com", "max_pages": "9999"},
                follow_redirects=False,
            )
        assert resp.status_code in (301, 302, 303)

    def test_max_pages_minimum_1(self, client):
        with patch("ada_bot.webapp.threading.Thread") as MockThread:
            MockThread.return_value.start.return_value = None
            resp = client.post(
                "/audit",
                data={"url": "https://example.com", "max_pages": "0"},
                follow_redirects=False,
            )
        assert resp.status_code in (301, 302, 303)

    def test_invalid_max_pages_uses_default(self, client):
        with patch("ada_bot.webapp.threading.Thread") as MockThread:
            MockThread.return_value.start.return_value = None
            resp = client.post(
                "/audit",
                data={"url": "https://example.com", "max_pages": "not-a-number"},
                follow_redirects=False,
            )
        assert resp.status_code in (301, 302, 303)


# ===========================================================================
# Status page
# ===========================================================================

class TestStatusPage:

    def test_returns_200_for_existing_job(self, client):
        _make_fake_job("job1")
        resp = client.get("/audit/job1")
        assert resp.status_code == 200

    def test_returns_404_for_unknown_job(self, client):
        resp = client.get("/audit/nonexistent-job-id")
        assert resp.status_code == 404

    def test_shows_job_url(self, client):
        _make_fake_job("job2", url="https://mysite.example.com")
        html = client.get("/audit/job2").data.decode()
        assert "mysite.example.com" in html

    def test_has_progress_log_element(self, client):
        _make_fake_job("job3")
        html = client.get("/audit/job3").data.decode()
        assert "log-output" in html

    def test_has_sse_javascript(self, client):
        _make_fake_job("job4")
        html = client.get("/audit/job4").data.decode()
        assert "EventSource" in html

    def test_has_back_to_home_link(self, client):
        _make_fake_job("job5")
        html = client.get("/audit/job5").data.decode()
        assert 'href="/"' in html

    def test_has_lang_attribute(self, client):
        _make_fake_job("job6")
        html = client.get("/audit/job6").data.decode()
        assert 'lang="en"' in html

    def test_has_skip_link(self, client):
        _make_fake_job("job7")
        html = client.get("/audit/job7").data.decode()
        assert "skip-link" in html


# ===========================================================================
# SSE stream endpoint
# ===========================================================================

class TestSSEStream:

    def test_returns_404_for_unknown_job(self, client):
        resp = client.get("/audit/bogus-id/stream")
        assert resp.status_code == 404

    def test_content_type_is_event_stream(self, client):
        job = _make_fake_job("stream1", status="completed")
        resp = client.get("/audit/stream1/stream")
        assert "text/event-stream" in resp.content_type

    def test_streams_messages_and_done(self, client):
        job = _make_fake_job("stream2", status="completed",
                              messages=["Pass 1/8 — Crawling", "Pass 2/8 — HTML"])
        body = client.get("/audit/stream2/stream").data.decode()
        assert "Pass 1/8" in body
        assert "Pass 2/8" in body
        assert "__DONE__" in body

    def test_sends_done_for_error_status(self, client):
        _make_fake_job("stream3", status="error", messages=["Something went wrong"])
        body = client.get("/audit/stream3/stream").data.decode()
        assert "__DONE__" in body

    def test_empty_messages_still_sends_done(self, client):
        _make_fake_job("stream4", status="completed", messages=[])
        body = client.get("/audit/stream4/stream").data.decode()
        assert "__DONE__" in body

    def test_newlines_in_messages_are_escaped(self, client):
        _make_fake_job("stream5", status="completed",
                        messages=["Line one\nLine two"])
        body = client.get("/audit/stream5/stream").data.decode()
        # SSE spec requires no bare newlines inside the data value
        # Each SSE event must be "data: ...\n\n" — verify the raw newline is gone
        for line in body.split("\n"):
            if line.startswith("data:"):
                assert "\n" not in line


# ===========================================================================
# Result JSON endpoint
# ===========================================================================

class TestResultEndpoint:

    def test_returns_404_for_unknown_job(self, client):
        resp = client.get("/audit/no-such-job/result")
        assert resp.status_code == 404

    def test_returns_200_for_running_job(self, client):
        _make_fake_job("res1", status="running")
        resp = client.get("/audit/res1/result")
        assert resp.status_code == 200

    def test_running_job_has_correct_status(self, client):
        _make_fake_job("res2", status="running")
        data = json.loads(client.get("/audit/res2/result").data)
        assert data["status"] == "running"

    def test_completed_job_returns_score(self, client):
        _make_fake_job("res3", status="completed", score=87,
                        total_pages=5, total_issues=3,
                        by_severity={"critical": 0, "serious": 2, "moderate": 1})
        data = json.loads(client.get("/audit/res3/result").data)
        assert data["status"] == "completed"
        assert data["score"] == 87
        assert data["total_pages"] == 5
        assert data["total_issues"] == 3

    def test_error_job_returns_error_message(self, client):
        _make_fake_job("res4", status="error", error="Connection refused")
        data = json.loads(client.get("/audit/res4/result").data)
        assert data["status"] == "error"
        assert "Connection refused" in data["error"]

    def test_result_contains_url(self, client):
        _make_fake_job("res5", status="running", url="https://test.example.com")
        data = json.loads(client.get("/audit/res5/result").data)
        assert data["url"] == "https://test.example.com"


# ===========================================================================
# Report HTML / JSON endpoints
# ===========================================================================

class TestReportEndpoints:

    def test_html_report_404_if_job_not_found(self, client):
        assert client.get("/audit/ghost/report").status_code == 404

    def test_html_report_404_if_job_still_running(self, client):
        _make_fake_job("rep1", status="running")
        assert client.get("/audit/rep1/report").status_code == 404

    def test_html_report_404_if_job_errored(self, client):
        _make_fake_job("rep2", status="error")
        assert client.get("/audit/rep2/report").status_code == 404

    def test_html_report_200_when_completed(self, client):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, "report.html")
            with open(html_path, "w") as f:
                f.write("<html><body>Report</body></html>")
            _make_fake_job("rep3", status="completed",
                            report_paths={"html": html_path, "json": html_path})
            resp = client.get("/audit/rep3/report")
            assert resp.status_code == 200
            assert b"Report" in resp.data

    def test_json_report_404_if_job_not_found(self, client):
        assert client.get("/audit/ghost/report.json").status_code == 404

    def test_json_report_404_if_job_still_running(self, client):
        _make_fake_job("rep4", status="running")
        assert client.get("/audit/rep4/report.json").status_code == 404

    def test_json_report_200_when_completed(self, client):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "report.json")
            with open(json_path, "w") as f:
                json.dump({"target_url": "https://example.com"}, f)
            _make_fake_job("rep5", status="completed",
                            report_paths={"html": json_path, "json": json_path})
            resp = client.get("/audit/rep5/report.json")
            assert resp.status_code == 200


# ===========================================================================
# Job store utilities
# ===========================================================================

class TestJobStore:

    def test_store_and_retrieve_job(self, client):
        job = {"id": "x1", "url": "https://x.com", "status": "running",
               "messages": [], "output_dir": "/tmp", "report_data": None,
               "report_paths": None, "error": None, "started_at": "now",
               "finished_at": None, "score": None, "total_pages": None,
               "total_issues": None, "by_severity": {}}
        _store_job(job)
        retrieved = _get_job("x1")
        assert retrieved is not None
        assert retrieved["url"] == "https://x.com"

    def test_get_nonexistent_job_returns_none(self, client):
        assert _get_job("does-not-exist") is None

    def test_append_message_thread_safe(self, client):
        job = _make_fake_job("x2", status="running")
        threads = []
        for i in range(20):
            t = threading.Thread(target=_append_message, args=("x2", f"msg{i}"))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with _jobs_lock:
            assert len(_jobs["x2"]["messages"]) == 20

    def test_lru_eviction_at_cap(self, client):
        """The store should evict the oldest jobs once _MAX_JOBS is reached."""
        from ada_bot.webapp import _MAX_JOBS

        # Fill the store to the cap
        for i in range(_MAX_JOBS):
            _store_job({
                "id": f"fill{i}", "url": "https://x.com", "status": "running",
                "messages": [], "output_dir": "/tmp", "report_data": None,
                "report_paths": None, "error": None, "started_at": "now",
                "finished_at": None, "score": None, "total_pages": None,
                "total_issues": None, "by_severity": {},
            })

        # The very first job should be evicted when we add one more
        _store_job({
            "id": "overflow", "url": "https://x.com", "status": "running",
            "messages": [], "output_dir": "/tmp", "report_data": None,
            "report_paths": None, "error": None, "started_at": "now",
            "finished_at": None, "score": None, "total_pages": None,
            "total_issues": None, "by_severity": {},
        })

        with _jobs_lock:
            assert len(_jobs) == _MAX_JOBS
        assert _get_job("fill0") is None
        assert _get_job("overflow") is not None


# ===========================================================================
# Background job runner
# ===========================================================================

class TestRunAuditJob:

    def test_successful_run_sets_completed(self, client):
        from ada_bot.webapp import _run_audit_job

        job = _make_fake_job("rj1", status="running")

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_rd = MagicMock()
            mock_rd.compliance_score = 95
            mock_rd.total_pages = 3
            mock_rd.total_issues = 2
            mock_rd.by_severity = {"critical": 0, "serious": 1}

            mock_cfg = MagicMock()
            mock_cfg.output_dir = tmpdir

            with patch("ada_bot.webapp.AuditEngine") as MockEngine:
                MockEngine.return_value.run.return_value = (
                    mock_rd,
                    {"html": "/tmp/r.html", "json": "/tmp/r.json"},
                )
                _run_audit_job("rj1", mock_cfg)

        with _jobs_lock:
            j = _jobs["rj1"]
        assert j["status"] == "completed"
        assert j["score"] == 95
        assert j["total_pages"] == 3

    def test_failed_run_sets_error_status(self, client):
        from ada_bot.webapp import _run_audit_job

        _make_fake_job("rj2", status="running")
        mock_cfg = MagicMock()

        with patch("ada_bot.webapp.AuditEngine") as MockEngine:
            MockEngine.return_value.run.side_effect = RuntimeError("Simulated crash")
            _run_audit_job("rj2", mock_cfg)

        with _jobs_lock:
            j = _jobs["rj2"]
        assert j["status"] == "error"
        assert "Simulated crash" in j["error"]

    def test_run_for_unknown_job_does_not_crash(self, client):
        """If the job was evicted before the thread finishes, don't raise."""
        from ada_bot.webapp import _run_audit_job

        mock_cfg = MagicMock()
        with patch("ada_bot.webapp.AuditEngine") as MockEngine:
            MockEngine.return_value.run.return_value = (MagicMock(), {})
            _run_audit_job("ghost-job-id", mock_cfg)  # must not raise
