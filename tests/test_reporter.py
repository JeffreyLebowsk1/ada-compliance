"""Tests for the reporter module."""
import json
import os
import tempfile
import pytest
from ada_bot.auditors.base import AuditIssue, PageAuditResult, Severity, WCAGLevel
from ada_bot.reporter import ReportData, ReportGenerator


def make_issue(rule_id="test-rule", severity=Severity.SERIOUS, url="https://example.com"):
    return AuditIssue(
        rule_id=rule_id,
        description="Test issue",
        page_url=url,
        severity=severity,
        wcag_criteria=["1.1.1"],
        wcag_level=WCAGLevel.A,
        fix_suggestion="Fix it.",
        audit_layer="html_structure",
    )


def make_page(url="https://example.com", issues=None, title="Test Page"):
    page = PageAuditResult(url=url, title=title, layer="html_structure")
    if issues:
        page.issues = issues
    return page


class TestReportData:
    def test_empty_report(self):
        data = ReportData("https://example.com", [])
        assert data.total_pages == 0
        assert data.total_issues == 0
        assert data.compliance_score == 100

    def test_compliance_score_decreases_with_issues(self):
        page = make_page(issues=[make_issue(severity=Severity.CRITICAL)])
        data = ReportData("https://example.com", [page])
        assert data.compliance_score < 100

    def test_critical_penalty_highest(self):
        page_c = make_page(issues=[make_issue(severity=Severity.CRITICAL)])
        page_m = make_page(issues=[make_issue(severity=Severity.MINOR)])
        data_c = ReportData("https://example.com", [page_c])
        data_m = ReportData("https://example.com", [page_m])
        assert data_c.compliance_score < data_m.compliance_score

    def test_score_floored_at_zero(self):
        issues = [make_issue(severity=Severity.CRITICAL)] * 10
        page = make_page(issues=issues)
        data = ReportData("https://example.com", [page])
        assert data.compliance_score == 0

    def test_by_severity_counts(self):
        issues = [
            make_issue(severity=Severity.CRITICAL),
            make_issue(severity=Severity.SERIOUS),
            make_issue(severity=Severity.MODERATE),
            make_issue(severity=Severity.MINOR),
        ]
        page = make_page(issues=issues)
        data = ReportData("https://example.com", [page])
        assert data.by_severity["critical"] == 1
        assert data.by_severity["serious"] == 1
        assert data.by_severity["moderate"] == 1
        assert data.by_severity["minor"] == 1

    def test_deduplication(self):
        issue = make_issue()
        # Same issue on same page — should deduplicate
        page = make_page(issues=[issue, issue])
        data = ReportData("https://example.com", [page])
        assert data.unique_issue_count == 1
        assert data.total_issues == 2  # total still counts duplicates

    def test_to_dict_structure(self):
        page = make_page(issues=[make_issue()])
        data = ReportData("https://example.com", [page])
        d = data.to_dict()
        assert "target_url" in d
        assert "generated_at" in d
        assert "summary" in d
        assert "pages" in d
        assert d["summary"]["total_issues"] == 1


class TestReportGenerator:
    def test_generates_json_and_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            page = make_page(issues=[make_issue()])
            data = ReportData("https://example.com", [page])
            gen = ReportGenerator(output_dir=tmpdir)
            paths = gen.generate(data)

            assert os.path.exists(paths["json"])
            assert os.path.exists(paths["html"])

    def test_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            page = make_page(issues=[make_issue()])
            data = ReportData("https://example.com", [page])
            gen = ReportGenerator(output_dir=tmpdir)
            paths = gen.generate(data)

            with open(paths["json"]) as f:
                parsed = json.load(f)
            assert parsed["target_url"] == "https://example.com"
            assert len(parsed["pages"]) == 1

    def test_html_contains_key_elements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            page = make_page(issues=[make_issue(rule_id="image-alt")])
            data = ReportData("https://example.com", [page])
            gen = ReportGenerator(output_dir=tmpdir)
            paths = gen.generate(data)

            with open(paths["html"], encoding="utf-8") as f:
                html = f.read()
            assert "ADA Compliance Audit Report" in html
            assert "https://example.com" in html
            assert "image-alt" in html

    def test_html_is_self_accessible(self):
        """The report HTML itself should have basic accessibility features."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data = ReportData("https://example.com", [])
            gen = ReportGenerator(output_dir=tmpdir)
            paths = gen.generate(data)

            with open(paths["html"], encoding="utf-8") as f:
                html = f.read()
            # Must have lang attribute
            assert 'lang="en"' in html
            # Must have a title
            assert "<title>" in html
            # Must have skip link
            assert "skip-link" in html or "Skip to main" in html
            # Must have main landmark
            assert 'role="main"' in html or "<main" in html
