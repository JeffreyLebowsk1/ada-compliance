"""
Layer 6 — AI Vision auditor.

Captures full-page screenshots of each URL using Playwright and sends
them to Perplexity (vision) for a holistic visual accessibility inspection.

The prompt instructs the model to look for:
  - Text that appears to have low contrast (not detectable from CSS alone)
  - Visual-only information (conveyed purely via colour or shape)
  - Cluttered or confusing layouts that could impair cognitive accessibility
  - Missing or ambiguous visual focus indicators
  - Images of text used in place of real text
  - Any visual element that looks like it may not meet ADA/WCAG guidelines

Requirements:
  - PERPLEXITY_API_KEY environment variable must be set
  - playwright + chromium must be installed

Usage:
    auditor = VisionAuditor(screenshot_dir="/tmp/screenshots")
    result = auditor.audit_page(url="https://example.com", html="", title="Example")
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from typing import Optional

from .base import AuditIssue, BaseAuditor, PageAuditResult, Severity, WCAGLevel

_WCAG_HELP = "https://www.w3.org/WAI/WCAG22/Understanding/"

_VISION_PROMPT = """\
You are an expert web accessibility auditor with deep knowledge of WCAG 2.2, \
ADA Section 508, and best practices for inclusive design.

You are given a full-page screenshot of a webpage. Carefully inspect it and \
identify any accessibility issues that cannot be detected through automated \
HTML/CSS analysis alone. Focus specifically on:

1. **Color contrast** – text or UI controls that appear to have insufficient \
   contrast against their background (even if CSS reports the correct value, \
   e.g. text on complex gradients or images).
2. **Color as the only means of conveying information** (WCAG 1.4.1) – e.g., \
   error states shown only in red, links distinguished only by color.
3. **Focus indicators** – are visible focus rings present on interactive \
   elements? Do they look prominent enough?
4. **Images of text** (WCAG 1.4.5) – text rendered as images rather than real \
   HTML text.
5. **Cognitive accessibility** – extremely cluttered layouts, blinking/moving \
   content, or confusing visual hierarchies.
6. **Touch/pointer targets** – interactive elements (buttons, links) that look \
   too small to tap comfortably (< 24×24 px or clustered too tightly).
7. **Visual-only instructions** – instructions that rely on shape, size, or \
   visual location without text description.
8. **Decorative vs informative images** – images that appear to convey \
   meaningful information but may lack alt text.

For each issue found, provide:
- A concise description of the issue
- The WCAG success criterion it violates (e.g., "1.4.3 Contrast (Minimum)")
- The approximate location on the page (e.g., "top navigation", "hero banner", \
  "footer")
- A concrete fix suggestion

Format your response as a JSON array of objects with these keys:
  "rule_id", "description", "wcag_criterion", "location", "severity", \
  "fix_suggestion"

Where "severity" is one of: "critical", "serious", "moderate", "minor".

If no accessibility issues are found, return an empty JSON array: []

Respond ONLY with the JSON array, no other text.
"""


class VisionAuditor(BaseAuditor):
    """Perplexity vision-based accessibility auditor."""

    LAYER_NAME = "ai_vision"

    def __init__(
        self,
        *,
        screenshot_dir: Optional[str] = None,
        perplexity_api_key: Optional[str] = None,
        model: str = "llama-3.2-90b-vision-instruct",
        timeout_ms: int = 30_000,
        headless: bool = True,
    ) -> None:
        self.screenshot_dir = screenshot_dir or tempfile.mkdtemp(prefix="ada_vision_")
        self.perplexity_api_key = perplexity_api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self.model = model
        self.timeout_ms = timeout_ms
        self.headless = headless

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)

        screenshot_path = self._take_screenshot(url, result)
        if result.error:
            return result

        vision_issues = self._run_vision(url, screenshot_path, result)
        if result.error:
            return result

        for item in vision_issues:
            severity_str = item.get("severity", "moderate").lower()
            severity_map = {
                "critical": Severity.CRITICAL,
                "serious": Severity.SERIOUS,
                "moderate": Severity.MODERATE,
                "minor": Severity.MINOR,
            }
            sev = severity_map.get(severity_str, Severity.MODERATE)

            wcag_raw = item.get("wcag_criterion", "")
            wcag_criteria = [wcag_raw] if wcag_raw else []

            result.issues.append(AuditIssue(
                rule_id=f"vision-{item.get('rule_id', 'visual-issue')}",
                description=item.get("description", "Visual accessibility issue detected."),
                page_url=url,
                element_selector=item.get("location", ""),
                severity=sev,
                wcag_criteria=wcag_criteria,
                wcag_level=WCAGLevel.AA,
                fix_suggestion=item.get("fix_suggestion", ""),
                audit_layer=self.LAYER_NAME,
            ))

        if not vision_issues:
            result.passed_rules.append("vision-inspection")

        return result

    # ------------------------------------------------------------------

    def _take_screenshot(self, url: str, result: PageAuditResult) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            result.error = (
                "playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            )
            return None

        os.makedirs(self.screenshot_dir, exist_ok=True)
        safe_name = hashlib.md5(url.encode()).hexdigest()[:12] + ".png"
        path = os.path.join(self.screenshot_dir, safe_name)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_default_timeout(self.timeout_ms)
                try:
                    page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                except Exception:
                    page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.screenshot(path=path, full_page=True)
                browser.close()
            return path
        except Exception as exc:
            result.error = f"Screenshot capture failed: {exc}"
            return None

    def _run_vision(
        self, url: str, screenshot_path: str, result: PageAuditResult
    ) -> list[dict]:
        if not self.perplexity_api_key:
            result.error = (
                "PERPLEXITY_API_KEY is not set. Vision audit requires a Perplexity API key."
            )
            return []

        try:
            from openai import OpenAI
        except ImportError:
            result.error = "openai package is not installed. Run: pip install openai"
            return []

        try:
            with open(screenshot_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            client = OpenAI(
                api_key=self.perplexity_api_key,
                base_url="https://api.perplexity.ai",
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _VISION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    # Perplexity does not support the "detail" parameter
                                    "url": f"data:image/png;base64,{img_b64}",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=4096,
            )
            content = response.choices[0].message.content.strip()
            # Strip markdown code blocks if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            import json
            return json.loads(content)
        except Exception as exc:
            result.error = f"Vision analysis failed: {exc}"
            return []
