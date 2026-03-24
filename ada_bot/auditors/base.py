"""Shared types and base class for all audit layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"
    INFO = "info"


class WCAGLevel(str, Enum):
    A = "A"
    AA = "AA"
    AAA = "AAA"


@dataclass
class AuditIssue:
    """A single accessibility issue found on a page."""

    # Identification
    rule_id: str
    description: str

    # Location
    page_url: str
    element_selector: str = ""
    element_html: str = ""
    element_context: str = ""

    # Classification
    severity: Severity = Severity.MODERATE
    wcag_criteria: list[str] = field(default_factory=list)
    wcag_level: WCAGLevel = WCAGLevel.AA

    # Guidance
    help_text: str = ""
    help_url: str = ""
    fix_suggestion: str = ""

    # Audit layer that found this
    audit_layer: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "page_url": self.page_url,
            "element_selector": self.element_selector,
            "element_html": self.element_html,
            "element_context": self.element_context,
            "severity": self.severity.value,
            "wcag_criteria": self.wcag_criteria,
            "wcag_level": self.wcag_level.value,
            "help_text": self.help_text,
            "help_url": self.help_url,
            "fix_suggestion": self.fix_suggestion,
            "audit_layer": self.audit_layer,
        }


@dataclass
class PageAuditResult:
    """All audit issues for a single page."""

    url: str
    title: str
    issues: list[AuditIssue] = field(default_factory=list)
    passed_rules: list[str] = field(default_factory=list)
    layer: str = ""
    error: Optional[str] = None

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def serious_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.SERIOUS)

    @property
    def moderate_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.MODERATE)

    @property
    def minor_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.MINOR)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "layer": self.layer,
            "error": self.error,
            "issues": [i.to_dict() for i in self.issues],
            "passed_rules": self.passed_rules,
            "issue_counts": {
                "critical": self.critical_count,
                "serious": self.serious_count,
                "moderate": self.moderate_count,
                "minor": self.minor_count,
                "total": len(self.issues),
            },
        }


class BaseAuditor:
    """Abstract base class for all audit layers."""

    LAYER_NAME = "base"

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        """Audit a single page and return findings.

        Subclasses must override this method.
        """
        raise NotImplementedError

    def audit_pages(
        self, pages: list[tuple[str, str, str]]
    ) -> list[PageAuditResult]:
        """Audit multiple pages.  *pages* is a list of (url, html, title)."""
        results = []
        for url, html, title in pages:
            results.append(self.audit_page(url, html, title))
        return results
