"""
Layer 3 — Color contrast auditor.

Checks WCAG 1.4.3 (AA) and 1.4.6 (AAA) color contrast ratios for text
elements by:
  1. Parsing inline styles and <style> blocks.
  2. Computing foreground / background colour pairs.
  3. Using the wcag-contrast-ratio library (or our own calculation) to
     evaluate the ratio against WCAG thresholds.

WCAG thresholds (contrast ratio):
  - Normal text (<18pt / <14pt bold): 4.5:1 (AA), 7:1 (AAA)
  - Large text (≥18pt / ≥14pt bold):  3:1  (AA), 4.5:1 (AAA)
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from .base import AuditIssue, BaseAuditor, PageAuditResult, Severity, WCAGLevel

_WCAG_HELP = "https://www.w3.org/WAI/WCAG22/Understanding/"

# Common CSS named colours (subset — enough for test coverage)
_NAMED_COLORS: dict[str, str] = {
    "white": "#ffffff", "black": "#000000", "red": "#ff0000",
    "green": "#008000", "blue": "#0000ff", "yellow": "#ffff00",
    "orange": "#ffa500", "grey": "#808080", "gray": "#808080",
    "silver": "#c0c0c0", "navy": "#000080", "teal": "#008080",
    "lime": "#00ff00", "aqua": "#00ffff", "cyan": "#00ffff",
    "fuchsia": "#ff00ff", "magenta": "#ff00ff", "maroon": "#800000",
    "olive": "#808000", "purple": "#800080", "transparent": "#ffffff",
    "inherit": None, "initial": None, "unset": None,
}


def _hex_to_rgb(hex_color: str) -> Optional[tuple[int, int, int]]:
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) == 6:
        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return (r, g, b)
        except ValueError:
            return None
    return None


def _rgb_str_to_tuple(rgb_str: str) -> Optional[tuple[int, int, int]]:
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", rgb_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _parse_color(value: str) -> Optional[tuple[int, int, int]]:
    value = value.strip().lower()
    if value.startswith("#"):
        return _hex_to_rgb(value)
    if value.startswith("rgb"):
        return _rgb_str_to_tuple(value)
    named = _NAMED_COLORS.get(value)
    if named is None:
        return None
    return _hex_to_rgb(named)


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG relative luminance formula."""
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(
    fg: tuple[int, int, int], bg: tuple[int, int, int]
) -> float:
    """Return the WCAG contrast ratio between two RGB tuples."""
    l1 = _relative_luminance(*fg)
    l2 = _relative_luminance(*bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _is_large_text(style: str) -> bool:
    """Heuristic: is the text 'large' (≥18pt or ≥14pt bold)?"""
    # bold
    bold = re.search(r"font-weight\s*:\s*(bold|[7-9]\d{2}|[1-9]\d{3})", style)
    size_m = re.search(r"font-size\s*:\s*([0-9.]+)(pt|px|em|rem)", style)
    if size_m:
        value = float(size_m.group(1))
        unit = size_m.group(2)
        # Convert to pt (approximate)
        if unit == "px":
            pt = value * 0.75
        elif unit == "em" or unit == "rem":
            pt = value * 12  # assume 16px base → 12pt
        else:
            pt = value
        if pt >= 18:
            return True
        if pt >= 14 and bold:
            return True
    return False


class ColorContrastAuditor(BaseAuditor):
    """Checks foreground/background colour contrast from inline styles."""

    LAYER_NAME = "color_contrast"

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)
        if not html:
            result.error = "No HTML content"
            return result

        soup = BeautifulSoup(html, "lxml")
        issues = result.issues
        passed = result.passed_rules

        checked = 0
        failures = 0

        for tag in soup.find_all(style=True):
            if tag.name in ("script", "style"):
                continue

            style = tag.get("style", "")
            fg_raw = self._extract_property(style, "color")
            bg_raw = self._extract_property(style, "background-color") or \
                     self._extract_property(style, "background")

            if not fg_raw or not bg_raw:
                continue

            fg = _parse_color(fg_raw)
            bg = _parse_color(bg_raw)

            if fg is None or bg is None:
                continue

            ratio = contrast_ratio(fg, bg)
            large = _is_large_text(style)
            aa_threshold = 3.0 if large else 4.5
            aaa_threshold = 4.5 if large else 7.0

            checked += 1

            if ratio < aa_threshold:
                failures += 1
                issues.append(AuditIssue(
                    rule_id="color-contrast",
                    description=(
                        f"Insufficient color contrast ratio: {ratio:.2f}:1 "
                        f"(required: {aa_threshold}:1 for "
                        f"{'large' if large else 'normal'} text)."
                    ),
                    page_url=url,
                    element_selector=self._sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.SERIOUS,
                    wcag_criteria=["1.4.3"],
                    wcag_level=WCAGLevel.AA,
                    help_url=_WCAG_HELP + "contrast-minimum",
                    fix_suggestion=(
                        f"Adjust the foreground color ({fg_raw}) or background color "
                        f"({bg_raw}) to achieve a contrast ratio of at least "
                        f"{aa_threshold}:1. "
                        f"Current ratio: {ratio:.2f}:1."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
            elif ratio < aaa_threshold:
                issues.append(AuditIssue(
                    rule_id="color-contrast-aaa",
                    description=(
                        f"Color contrast ratio {ratio:.2f}:1 meets AA but not AAA "
                        f"(required: {aaa_threshold}:1 for "
                        f"{'large' if large else 'normal'} text)."
                    ),
                    page_url=url,
                    element_selector=self._sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.MINOR,
                    wcag_criteria=["1.4.6"],
                    wcag_level=WCAGLevel.AAA,
                    help_url=_WCAG_HELP + "contrast-enhanced",
                    fix_suggestion=(
                        f"For enhanced (AAA) accessibility, adjust colors to achieve "
                        f"a ratio of at least {aaa_threshold}:1."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))

        if checked > 0 and failures == 0:
            passed.append("color-contrast")

        return result

    @staticmethod
    def _extract_property(style: str, prop: str) -> Optional[str]:
        pattern = rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)"
        m = re.search(pattern, style, re.IGNORECASE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _sel(tag: Tag) -> str:
        name = tag.name
        id_ = tag.get("id", "")
        if id_:
            return f"{name}#{id_}"
        classes = tag.get("class", [])
        if classes:
            return f"{name}.{classes[0]}"
        return name
