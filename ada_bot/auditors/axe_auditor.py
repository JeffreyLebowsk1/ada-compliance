"""
Layer 1 — axe-core automated WCAG audit via Playwright.

Uses axe-core (injected as a script) to run hundreds of automated
accessibility rules against each page in a real browser context.

Requires playwright to be installed:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .base import AuditIssue, BaseAuditor, PageAuditResult, Severity, WCAGLevel

# axe-core CDN URL (pinned to latest 4.x)
_AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"

# Axe impact → our severity
_IMPACT_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "serious": Severity.SERIOUS,
    "moderate": Severity.MODERATE,
    "minor": Severity.MINOR,
}


def _wcag_tags(tags: list[str]) -> list[str]:
    """Extract WCAG criterion strings from axe tags (e.g. 'wcag111' → '1.1.1')."""
    criteria = []
    for tag in tags:
        m = re.match(r"wcag(\d)(\d+)", tag)
        if m:
            major = m.group(1)
            rest = m.group(2)
            criterion = f"{major}.{'.'.join(rest)}"
            criteria.append(criterion)
    return criteria


def _wcag_level(tags: list[str]) -> WCAGLevel:
    if "wcag2aaa" in tags or "wcag21aaa" in tags or "wcag22aaa" in tags:
        return WCAGLevel.AAA
    if "wcag2aa" in tags or "wcag21aa" in tags or "wcag22aa" in tags:
        return WCAGLevel.AA
    return WCAGLevel.A


class AxeAuditor(BaseAuditor):
    """Runs axe-core in a headless Chromium browser via Playwright."""

    LAYER_NAME = "axe_core"

    def __init__(
        self,
        *,
        timeout_ms: int = 30_000,
        axe_script: Optional[str] = None,
        headless: bool = True,
        screenshot_dir: Optional[str] = None,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.axe_script = axe_script  # path to local axe.min.js, or None to fetch from CDN
        self.headless = headless
        self.screenshot_dir = screenshot_dir

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        """Audit a single URL using axe-core in a browser.

        Note: *html* is not used here — axe loads the live URL directly so
        JavaScript-rendered content is evaluated.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)
            result.error = (
                "playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            )
            return result

        result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)

                try:
                    page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                except Exception:
                    page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)

                if not title:
                    result.title = page.title()

                # Take screenshot if requested
                if self.screenshot_dir:
                    import os
                    import hashlib
                    os.makedirs(self.screenshot_dir, exist_ok=True)
                    safe_name = hashlib.md5(url.encode()).hexdigest()[:12] + ".png"
                    page.screenshot(
                        path=os.path.join(self.screenshot_dir, safe_name),
                        full_page=True,
                    )

                # Inject axe-core
                if self.axe_script:
                    with open(self.axe_script, "r", encoding="utf-8") as f:
                        axe_js = f.read()
                    page.evaluate(axe_js)
                else:
                    page.add_script_tag(url=_AXE_CDN)
                    page.wait_for_function("typeof axe !== 'undefined'", timeout=10_000)

                # Run axe
                axe_result = page.evaluate("""async () => {
                    const results = await axe.run(document, {
                        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] }
                    });
                    return results;
                }""")

                browser.close()

            # Parse violations
            for violation in axe_result.get("violations", []):
                severity = _IMPACT_MAP.get(violation.get("impact", "moderate"), Severity.MODERATE)
                wcag = _wcag_tags(violation.get("tags", []))
                level = _wcag_level(violation.get("tags", []))
                help_url = violation.get("helpUrl", "")

                for node in violation.get("nodes", []):
                    html_snippet = node.get("html", "")
                    target = node.get("target", [])
                    selector = target[0] if target else ""
                    failure_summary = node.get("failureSummary", "")

                    result.issues.append(AuditIssue(
                        rule_id=f"axe-{violation['id']}",
                        description=violation.get("description", violation["id"]),
                        page_url=url,
                        element_selector=selector,
                        element_html=html_snippet[:300],
                        severity=severity,
                        wcag_criteria=wcag,
                        wcag_level=level,
                        help_text=violation.get("help", ""),
                        help_url=help_url,
                        fix_suggestion=failure_summary,
                        audit_layer=self.LAYER_NAME,
                    ))

            # Record passes
            for passed in axe_result.get("passes", []):
                result.passed_rules.append(f"axe-{passed['id']}")

        except Exception as exc:
            result.error = f"axe-core audit failed: {exc}"

        return result
