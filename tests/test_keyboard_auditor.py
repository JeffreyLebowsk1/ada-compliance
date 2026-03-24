"""Tests for the keyboard navigation auditor (Layer 4)."""
import pytest
from ada_bot.auditors.keyboard_auditor import KeyboardAuditor
from ada_bot.auditors.base import Severity


@pytest.fixture
def auditor():
    return KeyboardAuditor()


# ---------------------------------------------------------------------------
# tabindex positive
# ---------------------------------------------------------------------------

def test_positive_tabindex_flagged(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button tabindex="3">Click me</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "tabindex-positive" in rule_ids


def test_tabindex_zero_ok(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div tabindex="0" role="button">Click me</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "tabindex-positive" not in rule_ids


# ---------------------------------------------------------------------------
# tabindex negative on focusable
# ---------------------------------------------------------------------------

def test_negative_tabindex_on_button(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button tabindex="-1">Hidden button</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "tabindex-negative-focusable" in rule_ids


def test_negative_tabindex_aria_hidden_ok(auditor):
    """A button that is aria-hidden should not be flagged for negative tabindex."""
    html = """<html lang="en"><head><title>T</title></head>
              <body><button tabindex="-1" aria-hidden="true">Hidden</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "tabindex-negative-focusable" not in rule_ids


# ---------------------------------------------------------------------------
# Focus outline removed
# ---------------------------------------------------------------------------

def test_outline_none_on_button(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button style="outline:none">Submit</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "focus-visible" in rule_ids


def test_outline_zero_on_input(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><input type="text" style="outline: 0" aria-label="Name"></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "focus-visible" in rule_ids


def test_no_outline_issue(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button style="background:blue; color:white">Submit</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "focus-visible" not in rule_ids


# ---------------------------------------------------------------------------
# onclick on non-interactive elements
# ---------------------------------------------------------------------------

def test_div_onclick_flagged(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div onclick="doSomething()">Click me</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "non-interactive-click-handler" in rule_ids


def test_div_onclick_with_role_button_ok(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div onclick="go()" role="button" tabindex="0">Click</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "non-interactive-click-handler" not in rule_ids


def test_button_onclick_ok(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button onclick="submit()">Submit</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "non-interactive-click-handler" not in rule_ids


# ---------------------------------------------------------------------------
# accesskey conflicts
# ---------------------------------------------------------------------------

def test_duplicate_accesskey(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <a href="/a" accesskey="s">Search</a>
                <a href="/b" accesskey="s">Submit</a>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "accesskey-conflict" in rule_ids


def test_unique_accesskeys(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <a href="/a" accesskey="s">Search</a>
                <a href="/b" accesskey="h">Home</a>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "accesskey-conflict" not in rule_ids


# ---------------------------------------------------------------------------
# Empty HTML
# ---------------------------------------------------------------------------

def test_empty_html(auditor):
    result = auditor.audit_page("https://example.com", "")
    assert result.error is not None
