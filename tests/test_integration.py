"""
Integration tests against a publicly available website.

These tests make real HTTP requests to https://example.com — a simple,
reliably-available page maintained by IANA — and exercise the full static
audit pipeline (HTML, Color, Keyboard, ARIA) without a browser or API key.

They are separated from unit tests so they can be excluded from offline
CI runs with:  pytest -m "not integration"
"""

from __future__ import annotations

import pytest
import requests

from ada_bot.auditors.aria_auditor import AriaAuditor
from ada_bot.auditors.color_auditor import ColorContrastAuditor
from ada_bot.auditors.html_auditor import HtmlAuditor
from ada_bot.auditors.keyboard_auditor import KeyboardAuditor
from ada_bot.crawler import Crawler, PageInfo
from ada_bot.reporter import ReportData

# Mark every test in this module as integration
pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET = "https://example.com"
_TIMEOUT = 30


def _is_reachable(url: str = TARGET) -> bool:
    """Return True if the target URL can be reached."""
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        return r.status_code < 500
    except requests.RequestException:
        return False


# Skip the entire module if the site is unreachable (e.g. no internet access)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _is_reachable(), reason=f"Cannot reach {TARGET}"),
]


# ---------------------------------------------------------------------------
# Crawler integration
# ---------------------------------------------------------------------------

class TestCrawlerIntegration:

    def test_crawl_example_com_returns_pages(self):
        crawler = Crawler(
            TARGET,
            max_pages=3,
            max_depth=1,
            respect_robots=True,
        )
        pages = crawler.crawl()
        assert len(pages) >= 1

    def test_start_page_is_included(self):
        from urllib.parse import urlparse
        crawler = Crawler(TARGET, max_pages=1, max_depth=0, respect_robots=False)
        pages = crawler.crawl()
        assert urlparse(pages[0].url).netloc == "example.com"

    def test_page_has_html_content(self):
        crawler = Crawler(TARGET, max_pages=1, max_depth=0, respect_robots=False)
        pages = crawler.crawl()
        assert pages[0].html != ""
        assert "<html" in pages[0].html.lower()

    def test_page_has_200_status(self):
        crawler = Crawler(TARGET, max_pages=1, max_depth=0, respect_robots=False)
        pages = crawler.crawl()
        assert pages[0].status_code == 200

    def test_page_has_title(self):
        crawler = Crawler(TARGET, max_pages=1, max_depth=0, respect_robots=False)
        pages = crawler.crawl()
        assert pages[0].title != ""

    def test_page_has_response_time(self):
        crawler = Crawler(TARGET, max_pages=1, max_depth=0, respect_robots=False)
        pages = crawler.crawl()
        assert pages[0].response_time_ms > 0

    def test_no_error_on_successful_fetch(self):
        crawler = Crawler(TARGET, max_pages=1, max_depth=0, respect_robots=False)
        pages = crawler.crawl()
        assert pages[0].error is None

    def test_external_links_not_followed(self):
        from urllib.parse import urlparse
        crawler = Crawler(TARGET, max_pages=10, max_depth=2, respect_robots=False)
        pages = crawler.crawl()
        for page in pages:
            assert urlparse(page.url).netloc == "example.com"


# ---------------------------------------------------------------------------
# HTML Auditor integration
# ---------------------------------------------------------------------------

class TestHtmlAuditorIntegration:

    @pytest.fixture(scope="class")
    def example_page(self):
        resp = requests.get(TARGET, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    @pytest.fixture(scope="class")
    def html_result(self, example_page):
        auditor = HtmlAuditor()
        return auditor.audit_page(TARGET, example_page)

    def test_returns_page_audit_result(self, html_result):
        from ada_bot.auditors.base import PageAuditResult
        assert isinstance(html_result, PageAuditResult)

    def test_result_url_matches(self, html_result):
        assert html_result.url == TARGET

    def test_no_crash_on_real_html(self, html_result):
        # Simply verifying the audit ran without raising
        assert html_result is not None

    def test_issues_have_valid_severities(self, html_result):
        from ada_bot.auditors.base import Severity
        valid = {s.value for s in Severity}
        for issue in html_result.issues:
            assert issue.severity.value in valid

    def test_issues_have_wcag_criteria(self, html_result):
        for issue in html_result.issues:
            assert issue.wcag_criteria  # non-empty list

    def test_issues_have_fix_suggestion(self, html_result):
        for issue in html_result.issues:
            assert issue.fix_suggestion

    def test_passed_rules_recorded(self, html_result):
        # example.com is a minimal but valid page — some rules should pass
        assert len(html_result.passed_rules) > 0


# ---------------------------------------------------------------------------
# Color Contrast Auditor integration
# ---------------------------------------------------------------------------

class TestColorAuditorIntegration:

    @pytest.fixture(scope="class")
    def example_page(self):
        resp = requests.get(TARGET, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def test_no_crash_on_real_html(self, example_page):
        auditor = ColorContrastAuditor()
        result = auditor.audit_page(TARGET, example_page)
        assert result is not None

    def test_result_has_correct_url(self, example_page):
        auditor = ColorContrastAuditor()
        result = auditor.audit_page(TARGET, example_page)
        assert result.url == TARGET

    def test_issues_are_valid_objects(self, example_page):
        from ada_bot.auditors.base import AuditIssue
        auditor = ColorContrastAuditor()
        result = auditor.audit_page(TARGET, example_page)
        for issue in result.issues:
            assert isinstance(issue, AuditIssue)


# ---------------------------------------------------------------------------
# Keyboard Auditor integration
# ---------------------------------------------------------------------------

class TestKeyboardAuditorIntegration:

    @pytest.fixture(scope="class")
    def example_page(self):
        resp = requests.get(TARGET, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def test_no_crash_on_real_html(self, example_page):
        auditor = KeyboardAuditor()
        result = auditor.audit_page(TARGET, example_page)
        assert result is not None

    def test_result_has_correct_url(self, example_page):
        auditor = KeyboardAuditor()
        result = auditor.audit_page(TARGET, example_page)
        assert result.url == TARGET


# ---------------------------------------------------------------------------
# ARIA Auditor integration
# ---------------------------------------------------------------------------

class TestAriaAuditorIntegration:

    @pytest.fixture(scope="class")
    def example_page(self):
        resp = requests.get(TARGET, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def test_no_crash_on_real_html(self, example_page):
        auditor = AriaAuditor()
        result = auditor.audit_page(TARGET, example_page)
        assert result is not None

    def test_result_has_correct_url(self, example_page):
        auditor = AriaAuditor()
        result = auditor.audit_page(TARGET, example_page)
        assert result.url == TARGET

    def test_issues_have_valid_rule_ids(self, example_page):
        auditor = AriaAuditor()
        result = auditor.audit_page(TARGET, example_page)
        for issue in result.issues:
            assert issue.rule_id
            assert isinstance(issue.rule_id, str)


# ---------------------------------------------------------------------------
# Full static pipeline integration
# ---------------------------------------------------------------------------

class TestFullPipelineIntegration:
    """Run all four static auditors against example.com and aggregate results."""

    @pytest.fixture(scope="class")
    def all_results(self):
        resp = requests.get(TARGET, timeout=_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        page_tuples = [(TARGET, html, "Example Domain")]
        results = []
        for AuditorClass in (HtmlAuditor, ColorContrastAuditor, KeyboardAuditor, AriaAuditor):
            results.extend(AuditorClass().audit_pages(page_tuples))
        return results

    def test_all_auditors_produce_results(self, all_results):
        assert len(all_results) == 4  # one result per auditor

    def test_no_results_have_fatal_errors(self, all_results):
        """Errors set on PageAuditResult should not exist for valid HTML."""
        for r in all_results:
            assert r.error is None, f"Auditor error: {r.error}"

    def test_report_data_builds_successfully(self, all_results):
        data = ReportData(TARGET, all_results)
        assert data.target_url == TARGET
        assert data.total_pages >= 1

    def test_compliance_score_is_valid(self, all_results):
        data = ReportData(TARGET, all_results)
        assert 0 <= data.compliance_score <= 100

    def test_report_json_is_serialisable(self, all_results):
        import json
        data = ReportData(TARGET, all_results)
        d = data.to_dict()
        serialised = json.dumps(d)
        assert len(serialised) > 0
        parsed = json.loads(serialised)
        assert parsed["target_url"] == TARGET

    def test_by_severity_sums_to_total(self, all_results):
        data = ReportData(TARGET, all_results)
        sev_total = sum(data.by_severity.values())
        assert sev_total == data.total_issues
