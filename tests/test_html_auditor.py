"""Tests for the HTML structure auditor (Layer 2)."""
import pytest
from ada_bot.auditors.html_auditor import HtmlAuditor
from ada_bot.auditors.base import Severity


@pytest.fixture
def auditor():
    return HtmlAuditor()


# ---------------------------------------------------------------------------
# Page title
# ---------------------------------------------------------------------------

def test_missing_page_title(auditor):
    html = "<html lang='en'><head></head><body><h1>Hello</h1></body></html>"
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "page-title" in rule_ids


def test_present_page_title(auditor):
    html = "<html lang='en'><head><title>Home</title></head><body><h1>Hello</h1></body></html>"
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "page-title" not in rule_ids
    assert "page-title" in result.passed_rules


# ---------------------------------------------------------------------------
# HTML lang
# ---------------------------------------------------------------------------

def test_missing_html_lang(auditor):
    html = "<html><head><title>T</title></head><body><h1>H</h1></body></html>"
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "html-lang" in rule_ids


def test_present_html_lang(auditor):
    html = "<html lang='en'><head><title>T</title></head><body><h1>H</h1></body></html>"
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "html-lang" not in rule_ids


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def test_image_missing_alt(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><img src="photo.jpg"></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "image-alt" in rule_ids


def test_image_with_empty_alt_decorative(auditor):
    """An image with alt='' should NOT trigger image-alt."""
    html = """<html lang="en"><head><title>T</title></head>
              <body><img src="photo.jpg" alt=""></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "image-alt" not in rule_ids


def test_image_with_meaningful_alt(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><img src="photo.jpg" alt="A cat on a mat"></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "image-alt" not in rule_ids


def test_image_aria_hidden_no_alt_required(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><img src="deco.svg" aria-hidden="true"></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "image-alt" not in rule_ids


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------

def test_missing_h1(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><h2>Subtitle</h2></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "heading-h1-missing" in rule_ids


def test_multiple_h1(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><h1>First</h1><h1>Second</h1></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "heading-multiple-h1" in rule_ids


def test_skipped_heading_level(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><h1>Main</h1><h3>Sub</h3></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "heading-skipped-level" in rule_ids


def test_correct_heading_hierarchy(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><h1>Main</h1><h2>Sub</h2><h3>Sub-sub</h3></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "heading-skipped-level" not in rule_ids


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def test_empty_link(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><a href="/page"></a></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "link-empty" in rule_ids


def test_generic_link_text(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><a href="/page">click here</a></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "link-generic-text" in rule_ids


def test_good_link_text(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><a href="/page">Download accessibility report</a></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "link-empty" not in rule_ids
    assert "link-generic-text" not in rule_ids


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

def test_form_field_missing_label(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><form><input type="text" name="email"></form></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "form-field-label" in rule_ids


def test_form_field_with_label(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><form>
                <label for="email">Email</label>
                <input type="email" id="email" name="email">
              </form></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "form-field-label" not in rule_ids


def test_form_field_with_aria_label(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><form>
                <input type="email" aria-label="Your email address">
              </form></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "form-field-label" not in rule_ids


def test_hidden_input_no_label_required(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><form><input type="hidden" name="csrf"></form></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "form-field-label" not in rule_ids


# ---------------------------------------------------------------------------
# Duplicate IDs
# ---------------------------------------------------------------------------

def test_duplicate_id(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div id="nav">Nav</div><div id="nav">Other</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "duplicate-id" in rule_ids


def test_no_duplicate_id(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><div id="nav">Nav</div><div id="main">Main</div></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "duplicate-id" not in rule_ids


# ---------------------------------------------------------------------------
# Viewport
# ---------------------------------------------------------------------------

def test_viewport_user_scalable_no(auditor):
    html = """<html lang="en"><head><title>T</title>
              <meta name="viewport" content="width=device-width, user-scalable=no">
              </head><body><h1>H</h1></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "viewport-zoom-disabled" in rule_ids


def test_viewport_ok(auditor):
    html = """<html lang="en"><head><title>T</title>
              <meta name="viewport" content="width=device-width, initial-scale=1">
              </head><body><h1>H</h1></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "viewport-zoom-disabled" not in rule_ids


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

def test_empty_button(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button></button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "button-empty" in rule_ids


def test_button_with_text(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button>Submit</button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "button-empty" not in rule_ids


def test_button_with_aria_label(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><button aria-label="Close dialog"><span>✕</span></button></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "button-empty" not in rule_ids


# ---------------------------------------------------------------------------
# Iframes
# ---------------------------------------------------------------------------

def test_iframe_missing_title(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><iframe src="https://maps.example.com"></iframe></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "iframe-title" in rule_ids


def test_iframe_with_title(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><iframe src="map.html" title="Location map"></iframe></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "iframe-title" not in rule_ids


# ---------------------------------------------------------------------------
# Skip link
# ---------------------------------------------------------------------------

def test_missing_skip_link(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><nav><a href="/home">Home</a></nav></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "skip-link" in rule_ids


def test_present_skip_link(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <a href="#main">Skip to main content</a>
                <main id="main"><h1>Content</h1></main>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "skip-link" not in rule_ids


# ---------------------------------------------------------------------------
# Video/Audio captions
# ---------------------------------------------------------------------------

def test_video_missing_captions(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><video src="clip.mp4"></video></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "video-captions" in rule_ids


def test_video_with_captions(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <video src="clip.mp4">
                  <track kind="captions" src="caps.vtt" srclang="en" label="English">
                </video>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "video-captions" not in rule_ids


# ---------------------------------------------------------------------------
# Empty HTML
# ---------------------------------------------------------------------------

def test_empty_html(auditor):
    result = auditor.audit_page("https://example.com", "")
    assert result.error is not None


# ---------------------------------------------------------------------------
# Severity checks
# ---------------------------------------------------------------------------

def test_critical_severities(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <img src="cat.jpg">
                <button></button>
                <form><input type="text" name="name"></form>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    critical = [i for i in result.issues if i.severity == Severity.CRITICAL]
    assert len(critical) >= 2


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def test_table_missing_caption_and_headers(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <table>
                  <tr><td>Name</td><td>Age</td></tr>
                  <tr><td>Alice</td><td>30</td></tr>
                </table>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "table-caption" in rule_ids
    assert "table-header" in rule_ids


def test_table_with_caption_and_headers(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <table>
                  <caption>User data</caption>
                  <tr><th scope="col">Name</th><th scope="col">Age</th></tr>
                  <tr><td>Alice</td><td>30</td></tr>
                </table>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "table-caption" not in rule_ids
    assert "table-header" not in rule_ids
