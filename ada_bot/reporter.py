"""
Report generator — produces HTML and JSON reports from audit results.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .auditors.base import AuditIssue, PageAuditResult, Severity


class ReportData:
    """Aggregated data across all pages and audit layers."""

    def __init__(
        self,
        target_url: str,
        pages: list[PageAuditResult],
        *,
        generated_at: Optional[str] = None,
    ) -> None:
        self.target_url = target_url
        self.pages = pages
        self.generated_at = generated_at or datetime.now(timezone.utc).isoformat()

        # Flatten all issues
        self.all_issues: list[AuditIssue] = [
            issue for page in pages for issue in page.issues
        ]

        # Deduplicate: same rule_id + element_selector counts as one unique issue
        seen: set[tuple] = set()
        self.unique_issues: list[AuditIssue] = []
        for issue in self.all_issues:
            key = (issue.rule_id, issue.element_selector, issue.page_url)
            if key not in seen:
                seen.add(key)
                self.unique_issues.append(issue)

        # Counts
        self.total_pages = len(set(p.url for p in pages if not p.error))
        self.total_issues = len(self.all_issues)
        self.unique_issue_count = len(self.unique_issues)

        self.by_severity: dict[str, int] = defaultdict(int)
        for issue in self.all_issues:
            self.by_severity[issue.severity.value] += 1

        self.by_wcag: dict[str, int] = defaultdict(int)
        for issue in self.all_issues:
            for crit in issue.wcag_criteria:
                self.by_wcag[crit] += 1

        self.by_rule: dict[str, int] = defaultdict(int)
        for issue in self.all_issues:
            self.by_rule[issue.rule_id] += 1

        self.by_layer: dict[str, int] = defaultdict(int)
        for issue in self.all_issues:
            self.by_layer[issue.audit_layer] += 1

        # Compliance score (0–100)
        # Critical = -20, Serious = -10, Moderate = -5, Minor = -1
        # Base score = 100, floored at 0
        penalty = (
            self.by_severity.get("critical", 0) * 20
            + self.by_severity.get("serious", 0) * 10
            + self.by_severity.get("moderate", 0) * 5
            + self.by_severity.get("minor", 0) * 1
        )
        self.compliance_score = max(0, 100 - penalty)

    def to_dict(self) -> dict:
        return {
            "target_url": self.target_url,
            "generated_at": self.generated_at,
            "summary": {
                "total_pages_audited": self.total_pages,
                "total_issues": self.total_issues,
                "unique_issues": self.unique_issue_count,
                "compliance_score": self.compliance_score,
                "by_severity": dict(self.by_severity),
                "by_wcag_criterion": dict(self.by_wcag),
                "top_rules_by_frequency": sorted(
                    self.by_rule.items(), key=lambda x: x[1], reverse=True
                )[:20],
                "by_audit_layer": dict(self.by_layer),
            },
            "pages": [p.to_dict() for p in self.pages],
        }


class ReportGenerator:
    """Generates HTML and JSON accessibility reports."""

    _TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

    def __init__(self, output_dir: str = "ada_reports") -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self._env = Environment(
            loader=FileSystemLoader(self._TEMPLATE_DIR),
            autoescape=select_autoescape(["html"]),
        )
        self._env.filters["severity_class"] = self._severity_class
        self._env.filters["pct"] = lambda v, total: f"{v/total*100:.1f}" if total else "0.0"

    def generate(self, report_data: ReportData) -> dict[str, str]:
        """Generate both HTML and JSON reports, returning paths."""
        paths = {}
        paths["json"] = self._write_json(report_data)
        paths["html"] = self._write_html(report_data)
        return paths

    def _write_json(self, data: ReportData) -> str:
        path = os.path.join(self.output_dir, "report.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, indent=2, ensure_ascii=False)
        return path

    def _write_html(self, data: ReportData) -> str:
        template = self._env.get_template("report.html")
        html = template.render(
            data=data,
            Severity=Severity,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        path = os.path.join(self.output_dir, "report.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    @staticmethod
    def _severity_class(severity: str) -> str:
        return {
            "critical": "danger",
            "serious": "warning",
            "moderate": "info",
            "minor": "secondary",
        }.get(severity, "secondary")
