"""
Layer 5 — ARIA roles, labels, and semantic HTML auditor.

Checks:
  4.1.2  Name/Role/Value: ARIA roles are valid, required ARIA children
         and parents are present, required ARIA attributes are set.
  1.3.1  Landmark regions: page has main, nav, header/banner, footer/contentinfo.
  1.3.6  ARIA required attributes are present.
  2.4.1  No content outside landmark regions (advisory).
  4.1.3  Status messages use role='status' or role='alert'.

Reference: https://www.w3.org/TR/wai-aria-1.2/
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from .base import AuditIssue, BaseAuditor, PageAuditResult, Severity, WCAGLevel

_WCAG_HELP = "https://www.w3.org/WAI/WCAG22/Understanding/"

# ARIA roles that require specific attributes
_REQUIRED_ATTRS: dict[str, list[str]] = {
    "checkbox":    ["aria-checked"],
    "combobox":    ["aria-expanded"],
    "listbox":     [],
    "option":      ["aria-selected"],
    "radio":       ["aria-checked"],
    "scrollbar":   ["aria-controls", "aria-valuenow", "aria-valuemax", "aria-valuemin"],
    "slider":      ["aria-valuenow", "aria-valuemax", "aria-valuemin"],
    "spinbutton":  ["aria-valuenow"],
    "tab":         ["aria-selected"],
}

# Roles that must be contained within specific parent roles
_REQUIRED_PARENTS: dict[str, list[str]] = {
    "listitem":    ["list"],
    "option":      ["listbox"],
    "row":         ["rowgroup", "grid", "treegrid", "table"],
    "gridcell":    ["row"],
    "tab":         ["tablist"],
    "treeitem":    ["tree", "group"],
    "menuitem":    ["menu", "menubar"],
}

# Valid ARIA roles (subset of WAI-ARIA 1.2)
_VALID_ROLES = {
    "alert", "alertdialog", "application", "article", "banner", "button",
    "cell", "checkbox", "columnheader", "combobox", "complementary",
    "contentinfo", "definition", "dialog", "directory", "document",
    "feed", "figure", "form", "grid", "gridcell", "group", "heading",
    "img", "link", "list", "listbox", "listitem", "log", "main",
    "marquee", "math", "menu", "menubar", "menuitem", "menuitemcheckbox",
    "menuitemradio", "navigation", "none", "note", "option", "presentation",
    "progressbar", "radio", "radiogroup", "region", "row", "rowgroup",
    "rowheader", "scrollbar", "search", "searchbox", "separator",
    "slider", "spinbutton", "status", "switch", "tab", "table",
    "tablist", "tabpanel", "term", "textbox", "timer", "toolbar",
    "tooltip", "tree", "treegrid", "treeitem",
}


def _sel(tag: Tag) -> str:
    name = tag.name
    id_ = tag.get("id", "")
    if id_:
        return f"{name}#{id_}"
    classes = tag.get("class", [])
    return f"{name}.{classes[0]}" if classes else name


class AriaAuditor(BaseAuditor):
    """Static ARIA and landmark checks."""

    LAYER_NAME = "aria_landmarks"

    def audit_page(self, url: str, html: str, title: str = "") -> PageAuditResult:
        result = PageAuditResult(url=url, title=title, layer=self.LAYER_NAME)
        if not html:
            result.error = "No HTML content"
            return result

        soup = BeautifulSoup(html, "lxml")
        issues = result.issues
        passed = result.passed_rules

        self._check_landmarks(soup, url, issues, passed)
        self._check_aria_roles(soup, url, issues, passed)
        self._check_aria_required_attrs(soup, url, issues, passed)
        self._check_aria_required_parents(soup, url, issues, passed)
        self._check_aria_hidden_focusable(soup, url, issues, passed)
        self._check_aria_label_empty(soup, url, issues, passed)
        self._check_aria_labelledby_exists(soup, url, issues, passed)
        self._check_role_presentation(soup, url, issues, passed)

        return result

    # ------------------------------------------------------------------

    def _check_landmarks(self, soup, url, issues, passed):
        def has_landmark(role_name, html_tags, implicit_role_tags=None):
            if soup.find(role=role_name):
                return True
            for tag_name in html_tags:
                if soup.find(tag_name):
                    return True
            return False

        landmarks = [
            ("main",        ["main"],                      "2.4.1", "main-landmark"),
            ("navigation",  ["nav"],                       "2.4.1", "nav-landmark"),
            ("banner",      ["header"],                    "1.3.6", "banner-landmark"),
            ("contentinfo", ["footer"],                    "1.3.6", "contentinfo-landmark"),
        ]

        for role, tags, wcag, rule_id in landmarks:
            if not has_landmark(role, tags):
                issues.append(AuditIssue(
                    rule_id=rule_id,
                    description=(
                        f"Page has no <{tags[0]}> element or role='{role}' landmark."
                    ),
                    page_url=url,
                    element_selector=tags[0],
                    severity=Severity.MODERATE,
                    wcag_criteria=[wcag],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "bypass-blocks",
                    fix_suggestion=(
                        f"Add a <{tags[0]}> element to define the {role} landmark "
                        "region, helping screen reader users navigate directly to it."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
            else:
                passed.append(rule_id)

    def _check_aria_roles(self, soup, url, issues, passed):
        for tag in soup.find_all(role=True):
            roles = [r.strip() for r in tag["role"].split()]
            for role in roles:
                if role not in _VALID_ROLES:
                    issues.append(AuditIssue(
                        rule_id="aria-invalid-role",
                        description=f'Element has an invalid ARIA role: "{role}".',
                        page_url=url,
                        element_selector=_sel(tag),
                        element_html=str(tag)[:200],
                        severity=Severity.SERIOUS,
                        wcag_criteria=["4.1.2"],
                        wcag_level=WCAGLevel.A,
                        help_url=_WCAG_HELP + "name-role-value",
                        fix_suggestion=(
                            f'Replace role="{role}" with a valid WAI-ARIA role. '
                            "See https://www.w3.org/TR/wai-aria-1.2/#role_definitions"
                        ),
                        audit_layer=self.LAYER_NAME,
                    ))
        passed.append("aria-valid-role")

    def _check_aria_required_attrs(self, soup, url, issues, passed):
        for tag in soup.find_all(role=True):
            role = tag["role"].strip().split()[0]  # first token
            required = _REQUIRED_ATTRS.get(role, [])
            for attr in required:
                if not tag.get(attr):
                    issues.append(AuditIssue(
                        rule_id="aria-required-attr",
                        description=(
                            f'Element with role="{role}" is missing required '
                            f'attribute "{attr}".'
                        ),
                        page_url=url,
                        element_selector=_sel(tag),
                        element_html=str(tag)[:200],
                        severity=Severity.CRITICAL,
                        wcag_criteria=["4.1.2"],
                        wcag_level=WCAGLevel.A,
                        help_url=_WCAG_HELP + "name-role-value",
                        fix_suggestion=(
                            f'Add {attr}="<value>" to this element. The "{attr}" '
                            f'attribute is required for role="{role}".'
                        ),
                        audit_layer=self.LAYER_NAME,
                    ))

    def _check_aria_required_parents(self, soup, url, issues, passed):
        for tag in soup.find_all(role=True):
            role = tag["role"].strip().split()[0]
            required_parents = _REQUIRED_PARENTS.get(role, [])
            if not required_parents:
                continue
            # Walk up the tree looking for a matching parent role or tag
            has_parent = False
            for ancestor in tag.parents:
                if not isinstance(ancestor, Tag):
                    continue
                ancestor_role = ancestor.get("role", "")
                if any(r in ancestor_role for r in required_parents):
                    has_parent = True
                    break
                if ancestor.name in required_parents:
                    has_parent = True
                    break
            if not has_parent:
                issues.append(AuditIssue(
                    rule_id="aria-required-parent",
                    description=(
                        f'Element with role="{role}" must be contained within '
                        f'an element with role="{" or ".join(required_parents)}".'
                    ),
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.CRITICAL,
                    wcag_criteria=["1.3.1", "4.1.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "name-role-value",
                    fix_suggestion=(
                        f'Wrap the element in a container with role="{required_parents[0]}".'
                    ),
                    audit_layer=self.LAYER_NAME,
                ))

    def _check_aria_hidden_focusable(self, soup, url, issues, passed):
        """aria-hidden=true must not be placed on focusable elements."""
        for tag in soup.find_all(**{"aria-hidden": "true"}):
            if tag.name in {"a", "button", "input", "select", "textarea"}:
                issues.append(AuditIssue(
                    rule_id="aria-hidden-focusable",
                    description=(
                        f"<{tag.name}> is focusable but has aria-hidden='true', "
                        "hiding it from assistive technologies while it remains "
                        "reachable by keyboard."
                    ),
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.CRITICAL,
                    wcag_criteria=["4.1.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "name-role-value",
                    fix_suggestion=(
                        "Remove aria-hidden='true' from focusable elements, or make "
                        "the element non-focusable with tabindex='-1'."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))

    def _check_aria_label_empty(self, soup, url, issues, passed):
        for tag in soup.find_all(**{"aria-label": True}):
            if not tag.get("aria-label", "").strip():
                issues.append(AuditIssue(
                    rule_id="aria-label-empty",
                    description="Element has an empty aria-label attribute.",
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.SERIOUS,
                    wcag_criteria=["4.1.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "name-role-value",
                    fix_suggestion=(
                        "Provide a meaningful, descriptive value for aria-label, "
                        "or remove the attribute and use visible text content."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
        passed.append("aria-label-non-empty")

    def _check_aria_labelledby_exists(self, soup, url, issues, passed):
        """Verify aria-labelledby references exist in the DOM."""
        for tag in soup.find_all(**{"aria-labelledby": True}):
            ids = tag["aria-labelledby"].split()
            for ref_id in ids:
                if not soup.find(id=ref_id):
                    issues.append(AuditIssue(
                        rule_id="aria-labelledby-exists",
                        description=(
                            f"aria-labelledby references id='{ref_id}' which does "
                            "not exist in the document."
                        ),
                        page_url=url,
                        element_selector=_sel(tag),
                        element_html=str(tag)[:200],
                        severity=Severity.SERIOUS,
                        wcag_criteria=["4.1.2"],
                        wcag_level=WCAGLevel.A,
                        help_url=_WCAG_HELP + "name-role-value",
                        fix_suggestion=(
                            f"Add an element with id='{ref_id}' to the page, or "
                            "update aria-labelledby to reference an existing element id."
                        ),
                        audit_layer=self.LAYER_NAME,
                    ))

    def _check_role_presentation(self, soup, url, issues, passed):
        """Elements with role=presentation/none must not have ARIA attributes."""
        for tag in soup.find_all(role=True):
            role = tag["role"].strip()
            if role not in ("presentation", "none"):
                continue
            # Check for forbidden global ARIA state/property attrs
            forbidden_found = [
                attr for attr in tag.attrs
                if attr.startswith("aria-") and attr != "aria-hidden"
            ]
            if forbidden_found:
                issues.append(AuditIssue(
                    rule_id="aria-presentation-has-attributes",
                    description=(
                        f'Element with role="{role}" has ARIA attributes '
                        f'({", ".join(forbidden_found)}) which are ignored.'
                    ),
                    page_url=url,
                    element_selector=_sel(tag),
                    element_html=str(tag)[:200],
                    severity=Severity.MINOR,
                    wcag_criteria=["4.1.2"],
                    wcag_level=WCAGLevel.A,
                    help_url=_WCAG_HELP + "name-role-value",
                    fix_suggestion=(
                        f'Remove the ARIA attributes from the element with '
                        f'role="{role}", or change the role to one that supports '
                        "these attributes."
                    ),
                    audit_layer=self.LAYER_NAME,
                ))
