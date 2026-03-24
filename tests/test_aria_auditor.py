"""Tests for the ARIA and landmark auditor (Layer 5)."""
import pytest
from ada_bot.auditors.aria_auditor import AriaAuditor
from ada_bot.auditors.base import Severity


@pytest.fixture
def auditor():
    return AriaAuditor()


# ---------------------------------------------------------------------------
# Landmark checks
# ---------------------------------------------------------------------------

def test_missing_main_landmark(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><p>Content</p></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "main-landmark" in rule_ids


def test_main_element_satisfies_landmark(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><main><p>Content</p></main></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "main-landmark" not in rule_ids


def test_role_main_satisfies_landmark(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div role="main"><p>Content</p></div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "main-landmark" not in rule_ids


def test_missing_nav_landmark(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><main><p>Content</p></main></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "nav-landmark" in rule_ids


def test_nav_element_satisfies(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <nav><a href="/">Home</a></nav>
                <main><p>Content</p></main>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "nav-landmark" not in rule_ids


# ---------------------------------------------------------------------------
# ARIA roles
# ---------------------------------------------------------------------------

def test_invalid_aria_role(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div role="totally-fake-role">Content</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-invalid-role" in rule_ids


def test_valid_aria_role(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div role="button" tabindex="0">Click</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-invalid-role" not in rule_ids


# ---------------------------------------------------------------------------
# Required ARIA attributes
# ---------------------------------------------------------------------------

def test_checkbox_missing_aria_checked(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div role="checkbox" tabindex="0">Option</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-required-attr" in rule_ids


def test_checkbox_with_aria_checked(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <div role="checkbox" aria-checked="false" tabindex="0">Option</div>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-required-attr" not in rule_ids


def test_slider_missing_required_attrs(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div role="slider" tabindex="0">Slider</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-required-attr" in rule_ids


# ---------------------------------------------------------------------------
# aria-hidden on focusable
# ---------------------------------------------------------------------------

def test_aria_hidden_on_button(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button aria-hidden="true">Hidden</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-hidden-focusable" in rule_ids


def test_aria_hidden_on_div_ok(auditor):
    """aria-hidden on a non-focusable div is fine."""
    html = """<html lang="en"><head><title>T</title></head>
              <body><div aria-hidden="true">Decorative</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-hidden-focusable" not in rule_ids


# ---------------------------------------------------------------------------
# Empty aria-label
# ---------------------------------------------------------------------------

def test_empty_aria_label(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button aria-label="">Click</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-label-empty" in rule_ids


# ---------------------------------------------------------------------------
# aria-labelledby pointing to non-existent id
# ---------------------------------------------------------------------------

def test_aria_labelledby_missing_id(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <input type="text" aria-labelledby="nonexistent-id">
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-labelledby-exists" in rule_ids


def test_aria_labelledby_valid_id(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <label id="name-label">Full name</label>
                <input type="text" aria-labelledby="name-label">
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-labelledby-exists" not in rule_ids


# ---------------------------------------------------------------------------
# Required parent
# ---------------------------------------------------------------------------

def test_option_missing_listbox_parent(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div role="option" aria-selected="false">Item</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-required-parent" in rule_ids


def test_option_with_listbox_parent(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <ul role="listbox">
                  <li role="option" aria-selected="false">Item</li>
                </ul>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "aria-required-parent" not in rule_ids


# ---------------------------------------------------------------------------
# Empty HTML
# ---------------------------------------------------------------------------

def test_empty_html(auditor):
    result = auditor.audit_page("https://example.com", "")
    assert result.error is not None
