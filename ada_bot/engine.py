"""
ADA Compliance Audit Engine.

Orchestrates the multi-pass audit:

  Pass 1 — Crawl the site to discover all pages.
  Pass 2 — Layer 2: Static HTML structure audit (HtmlAuditor).
  Pass 3 — Layer 3: Color contrast audit (ColorContrastAuditor).
  Pass 4 — Layer 4: Keyboard navigation audit (KeyboardAuditor).
  Pass 5 — Layer 5: ARIA / landmark audit (AriaAuditor).
  Pass 6 — Layer 1: axe-core automated audit in Playwright (AxeAuditor).
             (Runs after static passes so static issues inform browser setup.)
  Pass 7 — Layer 6: AI Vision audit via GPT-4o (VisionAuditor).
             (Optional, requires OPENAI_API_KEY.)
  Pass 8 — Final confirmation pass: re-audits pages flagged as having
             critical issues with HtmlAuditor + AriaAuditor to confirm
             findings haven't changed.

All results are merged into a single :class:`ReportData` object and
written to HTML + JSON reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from .auditors.base import PageAuditResult
from .auditors.html_auditor import HtmlAuditor
from .auditors.color_auditor import ColorContrastAuditor
from .auditors.keyboard_auditor import KeyboardAuditor
from .auditors.aria_auditor import AriaAuditor
from .auditors.axe_auditor import AxeAuditor
from .auditors.vision_auditor import VisionAuditor
from .crawler import Crawler, PageInfo
from .reporter import ReportData, ReportGenerator


@dataclass
class AuditConfig:
    """Configuration for a full site audit."""

    # Target
    url: str

    # Crawler settings
    max_pages: int = 100
    max_depth: int = 8
    crawl_timeout: int = 30
    respect_robots: bool = True
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    # Auditor toggles
    run_html_audit: bool = True
    run_color_audit: bool = True
    run_keyboard_audit: bool = True
    run_aria_audit: bool = True
    run_axe_audit: bool = True
    run_vision_audit: bool = False  # requires OPENAI_API_KEY

    # axe / Playwright settings
    axe_timeout_ms: int = 30_000
    headless: bool = True
    axe_script_path: Optional[str] = None

    # Vision settings
    openai_api_key: Optional[str] = None
    vision_screenshot_dir: str = "ada_reports/screenshots"

    # Output
    output_dir: str = "ada_reports"

    # Callbacks
    on_progress: Optional[Callable[[str], None]] = None


class AuditEngine:
    """Runs the full multi-pass ADA compliance audit."""

    def __init__(self, config: AuditConfig) -> None:
        self.config = config

    def run(self) -> tuple[ReportData, dict[str, str]]:
        """
        Execute all audit passes and generate reports.

        Returns
        -------
        (report_data, report_paths)
        """
        cfg = self.config
        self._log(f"🔍 Starting ADA compliance audit of: {cfg.url}")

        # ------------------------------------------------------------------ #
        # Pass 1 — Crawl
        # ------------------------------------------------------------------ #
        self._log("Pass 1/8 — Crawling site…")
        crawler = Crawler(
            cfg.url,
            max_pages=cfg.max_pages,
            max_depth=cfg.max_depth,
            timeout=cfg.crawl_timeout,
            respect_robots=cfg.respect_robots,
            include_patterns=cfg.include_patterns,
            exclude_patterns=cfg.exclude_patterns,
            on_page_discovered=lambda p: self._log(f"  Found: {p.url}"),
        )
        pages: list[PageInfo] = crawler.crawl()
        html_pages = [(p.url, p.html, p.title) for p in pages if p.html]
        self._log(f"  Discovered {len(html_pages)} HTML pages.")

        all_results: list[PageAuditResult] = []

        # ------------------------------------------------------------------ #
        # Pass 2 — HTML structure
        # ------------------------------------------------------------------ #
        if cfg.run_html_audit:
            self._log("Pass 2/8 — HTML structure audit…")
            auditor = HtmlAuditor()
            results = auditor.audit_pages(html_pages)
            for r in results:
                self._log(f"  {r.url}: {len(r.issues)} issues")
            all_results.extend(results)

        # ------------------------------------------------------------------ #
        # Pass 3 — Color contrast
        # ------------------------------------------------------------------ #
        if cfg.run_color_audit:
            self._log("Pass 3/8 — Color contrast audit…")
            auditor = ColorContrastAuditor()
            results = auditor.audit_pages(html_pages)
            for r in results:
                self._log(f"  {r.url}: {len(r.issues)} issues")
            all_results.extend(results)

        # ------------------------------------------------------------------ #
        # Pass 4 — Keyboard navigation
        # ------------------------------------------------------------------ #
        if cfg.run_keyboard_audit:
            self._log("Pass 4/8 — Keyboard navigation audit…")
            auditor = KeyboardAuditor()
            results = auditor.audit_pages(html_pages)
            for r in results:
                self._log(f"  {r.url}: {len(r.issues)} issues")
            all_results.extend(results)

        # ------------------------------------------------------------------ #
        # Pass 5 — ARIA / landmarks
        # ------------------------------------------------------------------ #
        if cfg.run_aria_audit:
            self._log("Pass 5/8 — ARIA and landmark audit…")
            auditor = AriaAuditor()
            results = auditor.audit_pages(html_pages)
            for r in results:
                self._log(f"  {r.url}: {len(r.issues)} issues")
            all_results.extend(results)

        # ------------------------------------------------------------------ #
        # Pass 6 — axe-core (browser)
        # ------------------------------------------------------------------ #
        if cfg.run_axe_audit:
            self._log("Pass 6/8 — axe-core browser audit…")
            axe_auditor = AxeAuditor(
                timeout_ms=cfg.axe_timeout_ms,
                axe_script=cfg.axe_script_path,
                headless=cfg.headless,
                screenshot_dir=os.path.join(cfg.output_dir, "screenshots"),
            )
            for url, _, title in html_pages:
                self._log(f"  axe: {url}")
                r = axe_auditor.audit_page(url, "", title)
                if r.error:
                    self._log(f"    ⚠ {r.error}")
                else:
                    self._log(f"    {len(r.issues)} issues")
                all_results.append(r)

        # ------------------------------------------------------------------ #
        # Pass 7 — AI Vision
        # ------------------------------------------------------------------ #
        if cfg.run_vision_audit:
            self._log("Pass 7/8 — AI Vision audit (GPT-4o)…")
            api_key = cfg.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
            vision_auditor = VisionAuditor(
                screenshot_dir=cfg.vision_screenshot_dir,
                openai_api_key=api_key,
                headless=cfg.headless,
            )
            for url, _, title in html_pages:
                self._log(f"  vision: {url}")
                r = vision_auditor.audit_page(url, "", title)
                if r.error:
                    self._log(f"    ⚠ {r.error}")
                else:
                    self._log(f"    {len(r.issues)} issues")
                all_results.append(r)
        else:
            self._log("Pass 7/8 — AI Vision audit skipped (use --vision flag to enable).")

        # ------------------------------------------------------------------ #
        # Pass 8 — Final confirmation re-audit of critical pages
        # ------------------------------------------------------------------ #
        self._log("Pass 8/8 — Final confirmation pass…")
        critical_urls = {
            r.url
            for r in all_results
            if r.critical_count > 0
        }
        if critical_urls:
            self._log(
                f"  Re-auditing {len(critical_urls)} page(s) with critical issues…"
            )
            confirm_pages = [
                (url, html, title)
                for url, html, title in html_pages
                if url in critical_urls
            ]
            for AuditorClass in (HtmlAuditor, AriaAuditor):
                auditor = AuditorClass()
                for r in auditor.audit_pages(confirm_pages):
                    r.layer = f"confirmation_{r.layer}"
                    all_results.append(r)
        else:
            self._log("  No critical issues found — confirmation pass skipped.")

        # ------------------------------------------------------------------ #
        # Generate reports
        # ------------------------------------------------------------------ #
        self._log("Generating reports…")
        report_data = ReportData(target_url=cfg.url, pages=all_results)
        generator = ReportGenerator(output_dir=cfg.output_dir)
        paths = generator.generate(report_data)

        self._log(f"\n✅ Audit complete!")
        self._log(f"   Compliance score : {report_data.compliance_score}/100")
        self._log(f"   Total issues     : {report_data.total_issues}")
        self._log(f"   HTML report      : {paths['html']}")
        self._log(f"   JSON report      : {paths['json']}")

        return report_data, paths

    def _log(self, msg: str) -> None:
        if self.config.on_progress:
            self.config.on_progress(msg)
        else:
            print(msg)
