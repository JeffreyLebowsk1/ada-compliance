"""
Layer 4 — Keyboard navigation & focus management auditor.

Checks performed:
  - 2.1.1  Keyboard: interactive elements must be keyboard reachable.
  - 2.1.2  No Keyboard Trap: elements should not use tabindex < 0 unnecessarily.
  - 2.4.3  Focus Order: positive tabindex values (disrupts natural order).
  - 2.4.7  Focus Visible: no outline:none / outline:0 on focusable elements.
  - 2.1.4  Character Key Shortcuts (advisory): accesskey collisions.

These checks are performed statically on the HTML.  Full keyboard-trap
detection requires a live browser and is delegated to AxeAuditor.
"""

from __future__ import annotations

import re
from collections import Counter

from bs4 import BeautifulSoup, Tag

from .base import AuditIssue, BaseAuditor, PageAuditResult, Severity, WCAGLevel

_WCAG_HELP = "https://www.w3.org/WAI/WCAG22/Understanding/"

_FOCUSABLE_TAGS = {"a", "button", "input", "select", "textarea", "details", "summary"}


def _sel(tag: Tag) -> str:
    name = tag.name
    id_ = tag.get("id", "")
    if id_:
        return f"{name}#{id_}"
    classes = tag.get("class", [])
    return f"{name}.{classes[0]}" if classes else name


class KeyboardAuditor(BaseAuditor):
    """Static keyboard navigation checks."""

    LAYER_NAME = "keyboard_navigation"

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)
        if not html:
            result.error = "No HTML content"
            return result

        soup = BeautifulSoup(html, "lxml")
        issues = result.issues
        passed = result.passed_rules

        self._check_tabindex(soup, url, issues, passed)
        self._check_focus_outline(soup, url, issues, passed)
        self._check_accesskey(soup, url, issues, passed)
        self._check_onclick_non_interactive(soup, url, issues, passed)
        self._check_tabindex_negative(soup, url, issues, passed)

        return result

    # ------------------------------------------------------------------

    def _check_tabindex(self, soup, url, issues, passed):
        positive_tabindex: list[Tag] = []
        for tag in soup.find_all(tabindex=True):
            try:
                ti = int(tag["tabindex"])
            except (ValueError, TypeError):
                continue
            if ti > 0:
                positive_tabindex.append(tag)

        if positive_tabindex:
            for tag in positive_tabindex[:5]:
                issues.append(AuditIssue(
                    rule_id="tabindex-positive",
                    description=(
                        f"Element has tabindex={tag['tabindex']} (positive value). "
                        "Positive tabindex values disrupt the natural focus order."
                    ),
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.MODERATE,
                    wcag_criteria=["2.4.3"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "focus-order",
                    fix_suggestion=(
                        "Remove the positive tabindex value and rely on the natural "
                        "DOM order instead. Use tabindex='0' to make an element "
                        "focusable without affecting order."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
        else:
            passed.append("tabindex-positive")

    def _check_tabindex_negative(self, soup, url, issues, passed):
        """Elements that should be reachable but are hidden from keyboard."""
        for tag in soup.find_all(tabindex=True):
            try:
                ti = int(tag["tabindex"])
            except (ValueError, TypeError):
                continue
            if ti < 0 and tag.name in _FOCUSABLE_TAGS:
                # Only flag if not hidden via aria or CSS
                if tag.get("aria-hidden") == "true":
                    continue
                if "hidden" in tag.get("class", []):
                    continue
                # Check for display:none / visibility:hidden in style
                style = tag.get("style", "").lower()
                if "display:none" in style.replace(" ", "") or \
                   "visibility:hidden" in style.replace(" ", ""):
                    continue
                issues.append(AuditIssue(
                    rule_id="tabindex-negative-focusable",
                    description=(
                        f"Interactive <{tag.name}> has tabindex='{ti}', making it "
                        "unreachable via keyboard navigation."
                    ),
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.SERIOUS,
                    wcag_criteria=["2.1.1"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "keyboard",
                    fix_suggestion=(
                        "Remove the negative tabindex or change it to tabindex='0' "
                        "so the element is reachable via keyboard."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))

    def _check_focus_outline(self, soup, url, issues, passed):
        """Check for outline:none or outline:0 on focusable elements."""
        outline_zero = re.compile(r"outline\s*:\s*(none|0)", re.I)
        found = False
        for tag in soup.find_all(style=True):
            style = tag.get("style", "")
            if outline_zero.search(style) and tag.name in _FOCUSABLE_TAGS:
                found = True
                issues.append(AuditIssue(
                    rule_id="focus-visible",
                    description=(
                        f"<{tag.name}> has inline style 'outline:none' or 'outline:0', "
                        "removing the visible keyboard focus indicator."
                    ),
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.SERIOUS,
                    wcag_criteria=["2.4.7", "2.4.11"],
                    wcag_level=WCAGLevel.AA,
                    help_url=_WCAG_HELP + "focus-visible",
                    fix_suggestion=(
                        "Remove 'outline:none' from interactive elements. Use CSS to "
                        "provide a custom visible focus indicator instead of removing it."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
        if not found:
            passed.append("focus-visible")

    def _check_accesskey(self, soup, url, issues, passed):
        keys: list[str] = []
        for tag in soup.find_all(accesskey=True):
            raw = tag["accesskey"]
            # BeautifulSoup may return AttributeValueList or str
            key = (str(raw[0]) if hasattr(raw, "__iter__") and not isinstance(raw, str)
                   else str(raw)).strip().lower()
            keys.append(key)
        duplicates = [k for k, count in Counter(keys).items() if count > 1]
        if duplicates:
            for dup in duplicates:
                issues.append(AuditIssue(
                    rule_id="accesskey-conflict",
                    description=(
                        f"Duplicate accesskey='{dup}' found on multiple elements."
                    ),
                    page_url=url,
                    element_selector=f"[accesskey='{dup}']",
                    severity=Severity.MINOR,
                    wcag_criteria=["2.1.4"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "character-key-shortcuts",
                    fix_suggestion=(
                        "Ensure all accesskey values are unique across the page to "
                        "avoid conflicts."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
        else:
            passed.append("accesskey-unique")

    def _check_onclick_non_interactive(self, soup, url, issues, passed):
        """Div/span/p elements with click handlers but no keyboard equivalent."""
        non_interactive = {"div", "span", "p", "li", "td", "th", "section", "article"}
        for tag in soup.find_all(True):
            if tag.name not in non_interactive:
                continue
            has_onclick = tag.get("onclick") or tag.get("ng-click") or \
                          tag.get("@click") or tag.get("v-on:click")
            if not has_onclick:
                continue
            # Check for compensating ARIA role
            role = tag.get("role", "")
            tabindex = tag.get("tabindex")
            if role in ("button", "link", "menuitem", "option", "checkbox", "radio", "tab"):
                continue
            if tabindex is not None:
                continue  # at least keyboard reachable
            issues.append(AuditIssue(
                rule_id="non-interactive-click-handler",
                description=(
                    f"<{tag.name}> has a click handler but is not keyboard accessible "
                    "(no interactive role or tabindex)."
                ),
                page_url=url,
                element_selector=_sel(tag),
                element_html=str(tag)[:200],
                severity=Severity.SERIOUS,
                wcag_criteria=["2.1.1", "4.1.2"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "keyboard",
                fix_suggestion=(
                    "Use a <button> or <a> element instead of a div/span with an "
                    "onclick handler. If you must use a non-interactive element, "
                    "add role='button' and tabindex='0' and handle the keydown event "
                    "for Enter and Space."
                ),
                audit_layer=self.LAYER_NAME,
            ))
