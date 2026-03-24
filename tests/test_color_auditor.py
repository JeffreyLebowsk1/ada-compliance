"""Tests for the color contrast auditor (Layer 3)."""
import pytest
from ada_bot.auditors.color_auditor import (
    ColorContrastAuditor,
    contrast_ratio,
    _parse_color,
    _hex_to_rgb,
    _rgb_str_to_tuple,
)
from ada_bot.auditors.base import Severity


# ---------------------------------------------------------------------------
# Unit tests: colour parsing helpers
# ---------------------------------------------------------------------------

def test_hex_to_rgb_6_digits():
    assert _hex_to_rgb("ff0000") == (255, 0, 0)
    assert _hex_to_rgb("000000") == (0, 0, 0)
    assert _hex_to_rgb("ffffff") == (255, 255, 255)


def test_hex_to_rgb_3_digits():
    assert _hex_to_rgb("f00") == (255, 0, 0)
    assert _hex_to_rgb("fff") == (255, 255, 255)


def test_rgb_str_to_tuple():
    assert _rgb_str_to_tuple("rgb(255, 0, 0)") == (255, 0, 0)
    assert _rgb_str_to_tuple("rgba(0, 128, 0, 0.5)") == (0, 128, 0)


def test_parse_color_hex():
    assert _parse_color("#ff0000") == (255, 0, 0)


def test_parse_color_named():
    assert _parse_color("white") == (255, 255, 255)
    assert _parse_color("black") == (0, 0, 0)


def test_parse_color_unknown():
    assert _parse_color("notacolor") is None


# ---------------------------------------------------------------------------
# Unit tests: contrast ratio calculation
# ---------------------------------------------------------------------------

def test_contrast_ratio_black_white():
    ratio = contrast_ratio((0, 0, 0), (255, 255, 255))
    assert abs(ratio - 21.0) < 0.1


def test_contrast_ratio_equal():
    ratio = contrast_ratio((128, 128, 128), (128, 128, 128))
    assert abs(ratio - 1.0) < 0.01


def test_contrast_ratio_symmetrical():
    r1 = contrast_ratio((0, 0, 0), (255, 255, 255))
    r2 = contrast_ratio((255, 255, 255), (0, 0, 0))
    assert abs(r1 - r2) < 0.001


# ---------------------------------------------------------------------------
# Integration: ColorContrastAuditor
# ---------------------------------------------------------------------------

@pytest.fixture
def auditor():
    return ColorContrastAuditor()


def test_insufficient_contrast_detected(auditor):
    # Light gray text on white background — very low contrast
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <p style="color:#aaaaaa; background-color:#ffffff;">Low contrast text</p>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "color-contrast" in rule_ids


def test_sufficient_contrast_passes(auditor):
    # Black text on white — 21:1 ratio
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <p style="color:#000000; background-color:#ffffff;">High contrast text</p>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "color-contrast" not in rule_ids


def test_aaa_only_flagged_as_minor(auditor):
    # Contrast between 4.5 and 7 — passes AA, fails AAA
    # Dark blue #1f4e79 on white: let's compute approx
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <p style="color:#444444; background-color:#ffffff;">Medium contrast</p>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    # #444444 on white ≈ 9.73:1, passes both AA and AAA, so no issue
    assert "color-contrast" not in [i.rule_id for i in result.issues]


def test_no_inline_color_no_issue(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body><p>Normal text</p></body></html>"""
    result = auditor.audit_page("https://example.com", html)
    assert len(result.issues) == 0


def test_missing_background_no_issue(auditor):
    """Only foreground color — cannot compute contrast, should not flag."""
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <p style="color:red;">Red text, no background</p>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "color-contrast" not in rule_ids


def test_empty_html(auditor):
    result = auditor.audit_page("https://example.com", "")
    assert result.error is not None


def test_rgb_colors(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <p style="color:rgb(170,170,170); background-color:rgb(255,255,255);">
                  Low contrast
                </p>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    rule_ids = [i.rule_id for i in result.issues]
    assert "color-contrast" in rule_ids


def test_severity_is_serious_for_aa_failure(auditor):
    html = """<html lang="en"><head><title>T</title></head>
              <body>
                <p style="color:#aaaaaa; background-color:#ffffff;">Low contrast</p>
              </body></html>"""
    result = auditor.audit_page("https://example.com", html)
    aa_issues = [i for i in result.issues if i.rule_id == "color-contrast"]
    assert aa_issues
    assert aa_issues[0].severity == Severity.SERIOUS
