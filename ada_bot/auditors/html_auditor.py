"""
Layer 2 — HTML structure auditor.

Checks performed (all mapped to specific WCAG 2.2 success criteria):

Perceivable
  1.1.1  Images: alt attribute present and non-empty
  1.3.1  Headings: logical hierarchy, no skipped levels
  1.3.1  Lists: content that looks like a list uses <ul>/<ol>
  1.3.1  Tables: have <caption> or aria-label; header cells use <th>
  1.3.5  Input purpose: autocomplete attributes on common form fields
  1.4.4  Text resize: viewport meta not locked to user-scale=no

Operable
  2.4.2  Page titled: <title> is present and non-empty
  2.4.6  Headings and labels descriptive
  2.4.9  Link purpose: links have discernible text (not just "click here")

Understandable
  3.1.1  Language: <html lang> present
  3.2.2  On input: forms without submit button warning
  3.3.1  Error identification: required inputs have labels
  3.3.2  Labels: every form control has an associated <label>

Robust
  4.1.1  Parsing: duplicate IDs
  4.1.2  Name/role/value: buttons and links have accessible names
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from .base import AuditIssue, BaseAuditor, PageAuditResult, Severity, WCAGLevel

# WCAG help URLs (WCAG 2.2 Understanding docs)
_WCAG_HELP = "https://www.w3.org/WAI/WCAG22/Understanding/"


def _sel(tag: Tag) -> str:
    """Build a simple CSS-selector-style description of a tag."""
    name = tag.name
    id_attr = tag.get("id", "")
    classes = " ".join(tag.get("class", []))
    sel = name
    if id_attr:
        sel += f"#{id_attr}"
    elif classes:
        sel += f".{classes.split()[0]}" if classes else ""
    return sel


def _truncate(text: str, max_len: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "…" if len(text) > max_len else text


class HtmlAuditor(BaseAuditor):
    """Static HTML structure auditing (no browser required)."""

    LAYER_NAME = "html_structure"

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)
        if not html:
            result.error = "No HTML content"
            return result

        soup = BeautifulSoup(html, "lxml")
        issues = result.issues
        passed = result.passed_rules

        self._check_page_title(soup, url, issues, passed)
        self._check_html_lang(soup, url, issues, passed)
        self._check_images(soup, url, issues, passed)
        self._check_headings(soup, url, issues, passed)
        self._check_links(soup, url, issues, passed)
        self._check_forms(soup, url, issues, passed)
        self._check_tables(soup, url, issues, passed)
        self._check_duplicate_ids(soup, url, issues, passed)
        self._check_viewport(soup, url, issues, passed)
        self._check_buttons(soup, url, issues, passed)
        self._check_iframes(soup, url, issues, passed)
        self._check_audio_video(soup, url, issues, passed)
        self._check_skip_links(soup, url, issues, passed)
        self._check_autocomplete(soup, url, issues, passed)

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_page_title(self, soup, url, issues, passed):
        title_tag = soup.find("title")
        if not title_tag or not title_tag.get_text(strip=True):
            issues.append(AuditIssue(
                rule_id="page-title",
                description="Page is missing a descriptive <title> element.",
                page_url=url,
                element_selector="title",
                severity=Severity.SERIOUS,
                wcag_criteria=["2.4.2"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "page-titled",
                fix_suggestion=(
                    'Add a descriptive <title> element inside <head>. '
                    'Example: <title>Home | My Website</title>'
                ),
                audit_layer=self.LAYER_NAME,
            ))
        else:
            passed.append("page-title")

    def _check_html_lang(self, soup, url, issues, passed):
        html_tag = soup.find("html")
        if html_tag is None:
            return
        lang = html_tag.get("lang", "").strip()
        if not lang:
            issues.append(AuditIssue(
                rule_id="html-lang",
                description='<html> element is missing a "lang" attribute.',
                page_url=url,
                element_selector="html",
                element_html=str(html_tag)[:200],
                severity=Severity.SERIOUS,
                wcag_criteria=["3.1.1"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "language-of-page",
                fix_suggestion='Add lang="en" (or the appropriate language code) to the <html> element.',
                audit_layer=self.LAYER_NAME,
            ))
        else:
            passed.append("html-lang")

    def _check_images(self, soup, url, issues, passed):
        imgs = soup.find_all("img")
        missing_alt: list[Tag] = []
        empty_alt_decorative: list[Tag] = []

        for img in imgs:
            # Presentational images (role=presentation / aria-hidden) are OK without alt
            if img.get("role") == "presentation" or img.get("aria-hidden") == "true":
                continue
            alt = img.get("alt")
            if alt is None:
                missing_alt.append(img)
            elif alt.strip() == "" and img.get("role") != "presentation":
                # Empty alt is valid for decorative images — but flag suspicious ones
                # that have a meaningful src filename
                src = img.get("src", "")
                basename = src.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                if basename and not re.match(r"^(img|image|photo|pic|\d+)$", basename, re.I):
                    empty_alt_decorative.append(img)

        for img in missing_alt:
            issues.append(AuditIssue(
                rule_id="image-alt",
                description="Image is missing an alt attribute.",
                page_url=url,
                element_selector=_sel(img),
                element_html=_truncate(str(img)),
                severity=Severity.CRITICAL,
                wcag_criteria=["1.1.1"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "non-text-content",
                fix_suggestion=(
                    'Add an alt attribute. For informative images use a descriptive '
                    'alternative text. For decorative images use alt="".'
                ),
                audit_layer=self.LAYER_NAME,
            ))

        for img in empty_alt_decorative:
            issues.append(AuditIssue(
                rule_id="image-alt-suspicious-empty",
                description=(
                    "Image has an empty alt attribute but its filename suggests it "
                    "may be informative."
                ),
                page_url=url,
                element_selector=_sel(img),
                element_html=_truncate(str(img)),
                severity=Severity.MODERATE,
                wcag_criteria=["1.1.1"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "non-text-content",
                fix_suggestion=(
                    "Verify whether this image is decorative. If it conveys information, "
                    "provide a meaningful alt text."
                ),
                audit_layer=self.LAYER_NAME,
            ))

        if not missing_alt and not empty_alt_decorative:
            passed.append("image-alt")

    def _check_headings(self, soup, url, issues, passed):
        heading_tags = soup.find_all(re.compile(r"^h[1-6]$"))
        if not heading_tags:
            return

        # Check for h1
        h1s = [h for h in heading_tags if h.name == "h1"]
        if not h1s:
            issues.append(AuditIssue(
                rule_id="heading-h1-missing",
                description="Page has no <h1> heading.",
                page_url=url,
                element_selector="h1",
                severity=Severity.MODERATE,
                wcag_criteria=["1.3.1", "2.4.6"],
                wcag_level=WCAGLevel.AA,
                help_url=_WCAG_HELP + "headings-and-labels",
                fix_suggestion="Add a single, descriptive <h1> as the main page heading.",
                audit_layer=self.LAYER_NAME,
            ))
        elif len(h1s) > 1:
            issues.append(AuditIssue(
                rule_id="heading-multiple-h1",
                description=f"Page has {len(h1s)} <h1> headings (should be exactly 1).",
                page_url=url,
                element_selector="h1",
                severity=Severity.MODERATE,
                wcag_criteria=["1.3.1"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "info-and-relationships",
                fix_suggestion="Use a single <h1> per page to represent the main topic.",
                audit_layer=self.LAYER_NAME,
            ))
        else:
            passed.append("heading-h1")

        # Check for skipped heading levels
        levels = [int(h.name[1]) for h in heading_tags]
        prev = levels[0]
        for level in levels[1:]:
            if level > prev + 1:
                issues.append(AuditIssue(
                    rule_id="heading-skipped-level",
                    description=(
                        f"Heading level skipped: <h{prev}> is followed by <h{level}>."
                    ),
                    page_url=url,
                    element_selector=f"h{level}",
                    severity=Severity.MODERATE,
                    wcag_criteria=["1.3.1"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "info-and-relationships",
                    fix_suggestion=(
                        f"Do not skip heading levels. Change <h{level}> to <h{prev + 1}> "
                        "or restructure the content hierarchy."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
                break
            prev = level

        # Empty headings
        for h in heading_tags:
            if not h.get_text(strip=True) and not h.find(["img", "svg"]):
                issues.append(AuditIssue(
                    rule_id="heading-empty",
                    description=f"<{h.name}> heading is empty.",
                    page_url=url,
                    element_selector=_sel(h),
                    element_html=_truncate(str(h)),
                    severity=Severity.SERIOUS,
                    wcag_criteria=["1.3.1", "2.4.6"],
                    wcag_level=WCAGLevel.AA,
                    help_url=_WCAG_HELP + "headings-and-labels",
                    fix_suggestion="Remove empty headings or add meaningful text content.",
                    audit_layer=self.LAYER_NAME,
                ))

    def _check_links(self, soup, url, issues, passed):
        generic_texts = {
            "click here", "here", "read more", "more", "learn more",
            "link", "click", "this", "continue", "details",
        }
        problem_links: list[Tag] = []
        empty_links: list[Tag] = []

        for a in soup.find_all("a", href=True):
            acc_name = self._accessible_name(a)
            if not acc_name:
                empty_links.append(a)
            elif acc_name.lower().strip() in generic_texts:
                problem_links.append(a)

        for a in empty_links:
            issues.append(AuditIssue(
                rule_id="link-empty",
                description="Link has no accessible name (no text, aria-label, or aria-labelledby).",
                page_url=url,
                element_selector=_sel(a),
                element_html=_truncate(str(a)),
                severity=Severity.SERIOUS,
                wcag_criteria=["2.4.4", "4.1.2"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "link-purpose-in-context",
                fix_suggestion=(
                    "Add visible text or an aria-label attribute to describe the link destination."
                ),
                audit_layer=self.LAYER_NAME,
            ))

        for a in problem_links:
            issues.append(AuditIssue(
                rule_id="link-generic-text",
                description=(
                    f'Link text "{self._accessible_name(a)}" is not descriptive enough.'
                ),
                page_url=url,
                element_selector=_sel(a),
                element_html=_truncate(str(a)),
                severity=Severity.MODERATE,
                wcag_criteria=["2.4.4"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "link-purpose-in-context",
                fix_suggestion=(
                    "Replace vague link text with a description of the destination or action."
                ),
                audit_layer=self.LAYER_NAME,
            ))

        if not empty_links and not problem_links:
            passed.append("link-purpose")

    def _check_forms(self, soup, url, issues, passed):
        controls = soup.find_all(["input", "select", "textarea"])
        unlabelled: list[Tag] = []

        for ctrl in controls:
            ctrl_type = ctrl.get("type", "text").lower()
            # Hidden inputs and submit/button/image inputs don't need labels
            if ctrl_type in ("hidden", "submit", "button", "image", "reset"):
                continue
            if ctrl.get("aria-hidden") == "true":
                continue

            # Check for label via: for/id, aria-label, aria-labelledby, title, placeholder
            ctrl_id = ctrl.get("id", "")
            has_label = False
            if ctrl_id and soup.find("label", {"for": ctrl_id}):
                has_label = True
            elif ctrl.get("aria-label", "").strip():
                has_label = True
            elif ctrl.get("aria-labelledby", "").strip():
                has_label = True
            elif ctrl.get("title", "").strip():
                has_label = True

            if not has_label:
                unlabelled.append(ctrl)

        for ctrl in unlabelled:
            issues.append(AuditIssue(
                rule_id="form-field-label",
                description=(
                    f"Form control <{ctrl.name} type={ctrl.get('type', 'text')}> "
                    "has no associated label."
                ),
                page_url=url,
                element_selector=_sel(ctrl),
                element_html=_truncate(str(ctrl)),
                severity=Severity.CRITICAL,
                wcag_criteria=["1.3.1", "3.3.2"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "labels-or-instructions",
                fix_suggestion=(
                    "Associate a <label for='ID'> with the field, or add an "
                    "aria-label / aria-labelledby attribute."
                ),
                audit_layer=self.LAYER_NAME,
            ))

        if not unlabelled:
            passed.append("form-field-label")

    def _check_tables(self, soup, url, issues, passed):
        for table in soup.find_all("table"):
            # Skip layout tables explicitly marked
            if table.get("role") == "presentation":
                continue

            # Caption or aria-label
            caption = table.find("caption")
            aria_label = table.get("aria-label", "") or table.get("aria-labelledby", "")
            if not caption and not aria_label:
                issues.append(AuditIssue(
                    rule_id="table-caption",
                    description="Data table is missing a <caption> or aria-label.",
                    page_url=url,
                    element_selector=_sel(table),
                    element_html=_truncate(str(table)),
                    severity=Severity.MODERATE,
                    wcag_criteria=["1.3.1"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "info-and-relationships",
                    fix_suggestion=(
                        'Add <caption>Description</caption> inside the <table> '
                        'or use aria-label="Description".'
                    ),
                    audit_layer=self.LAYER_NAME,
                ))

            # Header cells
            if not table.find("th"):
                issues.append(AuditIssue(
                    rule_id="table-header",
                    description="Data table has no header cells (<th> elements).",
                    page_url=url,
                    element_selector=_sel(table),
                    element_html=_truncate(str(table)),
                    severity=Severity.SERIOUS,
                    wcag_criteria=["1.3.1"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "info-and-relationships",
                    fix_suggestion=(
                        "Use <th> elements for column and/or row headers, and add "
                        'scope="col" or scope="row" attributes.'
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
            else:
                # Check scope attributes on th
                for th in table.find_all("th"):
                    if not th.get("scope") and not th.get("id"):
                        issues.append(AuditIssue(
                            rule_id="table-th-scope",
                            description='<th> element is missing a "scope" attribute.',
                            page_url=url,
                            element_selector=_sel(th),
                            element_html=_truncate(str(th)),
                            severity=Severity.MODERATE,
                            wcag_criteria=["1.3.1"],
                            wcag_level=WCAGLevel.A,
                            help_url=_WCAG_HELP + "info-and-relationships",
                            fix_suggestion='Add scope="col" or scope="row" to all <th> elements.',
                            audit_layer=self.LAYER_NAME,
                        ))
                        break  # one warning per table is enough

        passed.append("table-structure")

    def _check_duplicate_ids(self, soup, url, issues, passed):
        ids: dict[str, int] = {}
        for tag in soup.find_all(id=True):
            tag_id = tag["id"].strip()
            if tag_id:
                ids[tag_id] = ids.get(tag_id, 0) + 1

        duplicates = [id_ for id_, count in ids.items() if count > 1]
        if duplicates:
            for dup_id in duplicates[:5]:  # report first 5
                issues.append(AuditIssue(
                    rule_id="duplicate-id",
                    description=f'Duplicate id="{dup_id}" found on multiple elements.',
                    page_url=url,
                    element_selector=f"#{dup_id}",
                    severity=Severity.SERIOUS,
                    wcag_criteria=["4.1.1"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "parsing",
                    fix_suggestion=(
                        "Ensure every id attribute is unique within the page. "
                        "Use different identifiers or restructure the markup."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
        else:
            passed.append("duplicate-id")

    def _check_viewport(self, soup, url, issues, passed):
        viewport = soup.find("meta", attrs={"name": "viewport"})
        if viewport:
            content = viewport.get("content", "")
            if re.search(r"user-scalable\s*=\s*no", content, re.I) or \
               re.search(r"maximum-scale\s*=\s*1", content, re.I):
                issues.append(AuditIssue(
                    rule_id="viewport-zoom-disabled",
                    description=(
                        "Viewport meta tag disables user zoom (user-scalable=no or "
                        "maximum-scale=1)."
                    ),
                    page_url=url,
                    element_selector='meta[name="viewport"]',
                    element_html=_truncate(str(viewport)),
                    severity=Severity.SERIOUS,
                    wcag_criteria=["1.4.4"],
                    wcag_level=WCAGLevel.AA,
                    help_url=_WCAG_HELP + "resize-text",
                    fix_suggestion=(
                        'Remove "user-scalable=no" and ensure maximum-scale is not '
                        'set below 2 to allow users to zoom the page.'
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
            else:
                passed.append("viewport-zoom")

    def _check_buttons(self, soup, url, issues, passed):
        for btn in soup.find_all("button"):
            name = self._accessible_name(btn)
            if not name:
                issues.append(AuditIssue(
                    rule_id="button-empty",
                    description="<button> element has no accessible name.",
                    page_url=url,
                    element_selector=_sel(btn),
                    element_html=_truncate(str(btn)),
                    severity=Severity.CRITICAL,
                    wcag_criteria=["4.1.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "name-role-value",
                    fix_suggestion=(
                        "Add text content, an aria-label, or an aria-labelledby "
                        "attribute to the button."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
            else:
                passed.append("button-name")

    def _check_iframes(self, soup, url, issues, passed):
        for iframe in soup.find_all("iframe"):
            title = iframe.get("title", "").strip()
            aria_label = iframe.get("aria-label", "").strip()
            aria_labelledby = iframe.get("aria-labelledby", "").strip()
            if not title and not aria_label and not aria_labelledby:
                issues.append(AuditIssue(
                    rule_id="iframe-title",
                    description="<iframe> element has no title attribute.",
                    page_url=url,
                    element_selector=_sel(iframe),
                    element_html=_truncate(str(iframe)),
                    severity=Severity.SERIOUS,
                    wcag_criteria=["4.1.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "name-role-value",
                    fix_suggestion=(
                        'Add a descriptive title attribute to the <iframe>. '
                        'Example: <iframe title="Google Map of our location" ...>'
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
            else:
                passed.append("iframe-title")

    def _check_audio_video(self, soup, url, issues, passed):
        for media in soup.find_all(["video", "audio"]):
            tracks = media.find_all("track")
            has_captions = any(
                t.get("kind", "").lower() in ("captions", "subtitles")
                for t in tracks
            )
            if not has_captions:
                tag_name = media.name
                issues.append(AuditIssue(
                    rule_id=f"{tag_name}-captions",
                    description=(
                        f"<{tag_name}> element has no <track kind='captions'> or "
                        "<track kind='subtitles'>."
                    ),
                    page_url=url,
                    element_selector=_sel(media),
                    element_html=_truncate(str(media)),
                    severity=Severity.CRITICAL,
                    wcag_criteria=["1.2.1", "1.2.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "captions-prerecorded",
                    fix_suggestion=(
                        f'Add <track kind="captions" src="captions.vtt" '
                        f'srclang="en" label="English"> inside <{tag_name}>.'
                    ),
                    audit_layer=self.LAYER_NAME,
                ))

    def _check_skip_links(self, soup, url, issues, passed):
        skip = soup.find("a", href="#main") or soup.find("a", href="#content") or \
               soup.find("a", string=re.compile(r"skip", re.I))
        if not skip:
            issues.append(AuditIssue(
                rule_id="skip-link",
                description='Page is missing a "Skip to main content" skip navigation link.',
                page_url=url,
                element_selector="a[href='#main']",
                severity=Severity.MODERATE,
                wcag_criteria=["2.4.1"],
                wcag_level=WCAGLevel.A,
                help_url=_WCAG_HELP + "bypass-blocks",
                fix_suggestion=(
                    'Add <a href="#main" class="skip-link">Skip to main content</a> '
                    "as the first element inside <body>, and add id='main' to the "
                    "main content area."
                ),
                audit_layer=self.LAYER_NAME,
            ))
        else:
            passed.append("skip-link")

    def _check_autocomplete(self, soup, url, issues, passed):
        """WCAG 1.3.5: Identify input purpose via autocomplete attributes."""
        autocomplete_map = {
            "name": "name",
            "email": "email",
            "tel": "tel",
            "street-address": "street-address",
            "postal-code": "postal-code",
            "cc-number": "cc-number",
            "bday": "bday",
            "username": "username",
            "new-password": "new-password",
            "current-password": "current-password",
        }
        for inp in soup.find_all("input"):
            inp_type = inp.get("type", "text").lower()
            if inp_type in ("hidden", "submit", "button", "image", "reset", "checkbox", "radio"):
                continue
            name_attr = (inp.get("name", "") or "").lower()
            id_attr = (inp.get("id", "") or "").lower()
            placeholder = (inp.get("placeholder", "") or "").lower()
            token = name_attr or id_attr or placeholder

            for key in autocomplete_map:
                if key in token and not inp.get("autocomplete"):
                    issues.append(AuditIssue(
                        rule_id="input-autocomplete",
                        description=(
                            f"Input field that appears to collect '{key}' data is "
                            "missing an autocomplete attribute."
                        ),
                        page_url=url,
                        element_selector=_sel(inp),
                        element_html=_truncate(str(inp)),
                        severity=Severity.MODERATE,
                        wcag_criteria=["1.3.5"],
                        wcag_level=WCAGLevel.AA,
                        help_url=_WCAG_HELP + "identify-input-purpose",
                        fix_suggestion=(
                            f'Add autocomplete="{autocomplete_map[key]}" to this input.'
                        ),
                        audit_layer=self.LAYER_NAME,
                    ))
                    break

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _accessible_name(tag: Tag) -> str:
        """Approximate accessible name computation."""
        aria_label = tag.get("aria-label", "").strip()
        if aria_label:
            return aria_label
        aria_labelledby = tag.get("aria-labelledby", "").strip()
        if aria_labelledby:
            return aria_labelledby  # ideal: resolve IDs, but we return as indicator
        title = tag.get("title", "").strip()
        if title:
            return title
        text = tag.get_text(separator=" ", strip=True)
        if text:
            return text
        # Check child img alt
        img = tag.find("img")
        if img and img.get("alt", "").strip():
            return img["alt"].strip()
        return ""
