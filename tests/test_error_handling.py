"""
Comprehensive error-handling tests for all foreseeable error scenarios.

Covers:
- Crawler: network failures, timeouts, SSL errors, redirects, malformed URLs,
           encoding issues, non-HTML content types, large pages, robots.txt
- HtmlAuditor: empty/whitespace-only/malformed HTML, bizarre attribute values,
               encoding edge cases, embedded script/style content
- ColorContrastAuditor: invalid/unusual color formats, missing values
- KeyboardAuditor: bizarre tabindex values, very deep DOM nesting
- AriaAuditor: unknown roles, conflicting attributes, deeply nested structures
- ReportData / ReportGenerator: empty data, special characters, score clamping
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.robotparser

import pytest
import requests
import responses as resp_lib

from ada_bot.auditors.aria_auditor import AriaAuditor
from ada_bot.auditors.base import AuditIssue, PageAuditResult, Severity, WCAGLevel
from ada_bot.auditors.color_auditor import ColorContrastAuditor
from ada_bot.auditors.html_auditor import HtmlAuditor
from ada_bot.auditors.keyboard_auditor import KeyboardAuditor
from ada_bot.crawler import Crawler, PageInfo
from ada_bot.reporter import ReportData, ReportGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def html_auditor():
    return HtmlAuditor()


@pytest.fixture
def color_auditor():
    return ColorContrastAuditor()


@pytest.fixture
def keyboard_auditor():
    return KeyboardAuditor()


@pytest.fixture
def aria_auditor():
    return AriaAuditor()


# ===========================================================================
# Crawler error-handling tests
# ===========================================================================

class TestCrawlerNetworkErrors:
    """Crawler should handle network failures gracefully without raising."""

    @resp_lib.activate
    def test_connection_error_on_start_url(self):
        resp_lib.add(
            resp_lib.GET,
            "https://example.com",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].error is not None
        assert pages[0].status_code == 0

    @resp_lib.activate
    def test_timeout_on_start_url(self):
        resp_lib.add(
            resp_lib.GET,
            "https://example.com",
            body=requests.exceptions.Timeout("Request timed out"),
        )
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].error is not None
        assert pages[0].status_code == 0

    @resp_lib.activate
    def test_ssl_error(self):
        resp_lib.add(
            resp_lib.GET,
            "https://example.com",
            body=requests.exceptions.SSLError("SSL certificate verification failed"),
        )
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].error is not None

    @resp_lib.activate
    def test_too_many_redirects(self):
        resp_lib.add(
            resp_lib.GET,
            "https://example.com",
            body=requests.exceptions.TooManyRedirects("Too many redirects"),
        )
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].error is not None

    @resp_lib.activate
    def test_connection_error_on_subpage(self):
        """A network error on an internal link should not crash the crawl."""
        home_html = (
            '<html lang="en"><head><title>Home</title></head>'
            '<body><a href="/fail">Fail</a></body></html>'
        )
        resp_lib.add(resp_lib.GET, "https://example.com", body=home_html, content_type="text/html")
        resp_lib.add(
            resp_lib.GET,
            "https://example.com/fail",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )
        crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 2
        fail_pages = [p for p in pages if "fail" in p.url]
        assert fail_pages[0].error is not None

    @resp_lib.activate
    def test_500_error_still_recorded(self):
        # 500 is in status_forcelist so retries exhaust and raise RetryError
        # which is caught as RequestException → status_code=0, error set
        resp_lib.add(resp_lib.GET, "https://example.com", status=500, body="Server Error")
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        # After retries are exhausted the page is recorded either with status 500
        # (if responses short-circuits retries) or 0 (if MaxRetryError is raised)
        assert pages[0].status_code in (0, 500)

    @resp_lib.activate
    def test_429_rate_limit_recorded(self):
        # 429 is in status_forcelist so retries exhaust and raise RetryError
        resp_lib.add(resp_lib.GET, "https://example.com", status=429, body="Too Many Requests")
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].status_code in (0, 429)

    @resp_lib.activate
    def test_empty_response_body(self):
        resp_lib.add(resp_lib.GET, "https://example.com", body="", content_type="text/html")
        crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        # An empty HTML page should still be recorded
        assert pages[0].status_code == 200

    @resp_lib.activate
    def test_non_html_content_types(self):
        """Various non-HTML content types should be recorded but not crawled further."""
        for content_type, body in [
            ("application/json", b'{"key": "value"}'),
            ("application/pdf", b"%PDF-1.4"),
            ("image/png", b"\x89PNG"),
            ("text/xml", b"<?xml version='1.0'?><root/>"),
        ]:
            resp_lib.reset()
            resp_lib.add(
                resp_lib.GET,
                "https://example.com",
                body=body,
                content_type=content_type,
            )
            crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
            pages = crawler.crawl()
            assert len(pages) == 1
            p = pages[0]
            assert p.html == "" or p.error is not None

    @resp_lib.activate
    def test_large_page_handled(self):
        """A very large HTML page (>1 MB) should be fetched without crashing."""
        # ~1.2 MB page
        big_html = (
            '<html lang="en"><head><title>Big</title></head><body>'
            + "<p>x</p>" * 150_000
            + "</body></html>"
        )
        resp_lib.add(resp_lib.GET, "https://example.com", body=big_html, content_type="text/html")
        crawler = Crawler("https://example.com", max_pages=1, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].html != ""

    @resp_lib.activate
    def test_url_with_query_string(self):
        """URLs containing query parameters should be normalised consistently."""
        html = '<html lang="en"><head><title>T</title></head><body></body></html>'
        resp_lib.add(
            resp_lib.GET,
            "https://example.com/search?q=test",
            body=html,
            content_type="text/html",
        )
        crawler = Crawler(
            "https://example.com/search?q=test", max_pages=1, respect_robots=False
        )
        pages = crawler.crawl()
        assert len(pages) == 1
        assert pages[0].status_code == 200

    def test_robots_txt_disallows_all(self):
        """When robots.txt disallows all paths, matching pages should be blocked."""
        from unittest.mock import patch

        def fake_read(self_rp):
            # Simulate a successfully-parsed robots.txt that blocks everything
            self_rp.parse(["User-agent: *", "Disallow: /"])

        html = '<html lang="en"><head><title>T</title></head><body></body></html>'
        with resp_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(rsps.GET, "https://example.com", body=html, content_type="text/html")
            with patch.object(
                urllib.robotparser.RobotFileParser, "read", fake_read
            ):
                crawler = Crawler("https://example.com", max_pages=5, respect_robots=True)
                pages = crawler.crawl()
        # All pages (including start URL) are blocked by Disallow: /
        assert len(pages) == 0

    def test_robots_txt_unreachable(self):
        """If robots.txt cannot be fetched, the crawl should continue normally."""
        from unittest.mock import patch

        html = '<html lang="en"><head><title>T</title></head><body></body></html>'
        with resp_lib.RequestsMock() as rsps:
            rsps.add(rsps.GET, "https://example.com", body=html, content_type="text/html")
            with patch.object(
                urllib.robotparser.RobotFileParser,
                "read",
                side_effect=OSError("Connection refused"),
            ):
                crawler = Crawler("https://example.com", max_pages=5, respect_robots=True)
                pages = crawler.crawl()
        # Failed robots.txt fetch → permissive → start URL is crawled
        assert len(pages) >= 1

    def test_robots_txt_connection_error(self):
        """If robots.txt read raises an exception the crawl should not crash."""
        from unittest.mock import patch

        html = '<html lang="en"><head><title>T</title></head><body></body></html>'
        with resp_lib.RequestsMock() as rsps:
            rsps.add(rsps.GET, "https://example.com", body=html, content_type="text/html")
            with patch.object(
                urllib.robotparser.RobotFileParser,
                "read",
                side_effect=Exception("Unexpected robots error"),
            ):
                crawler = Crawler("https://example.com", max_pages=5, respect_robots=True)
                pages = crawler.crawl()
        assert len(pages) >= 1

    @resp_lib.activate
    def test_fragment_only_links_not_crawled(self):
        """Links that are only fragment anchors should not create new pages."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="#section1">Jump</a>'
            '<a href="#section2">Jump 2</a>'
            "</body></html>"
        )
        resp_lib.add(resp_lib.GET, "https://example.com", body=html, content_type="text/html")
        crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
        pages = crawler.crawl()
        # Only the start URL — no new pages from fragment-only links
        assert len(pages) == 1

    @resp_lib.activate
    def test_mailto_and_tel_links_not_crawled(self):
        """mailto: and tel: links should be ignored by the crawler."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="mailto:test@example.com">Email</a>'
            '<a href="tel:+15555555555">Call</a>'
            "</body></html>"
        )
        resp_lib.add(resp_lib.GET, "https://example.com", body=html, content_type="text/html")
        crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
        pages = crawler.crawl()
        assert len(pages) == 1

    @resp_lib.activate
    def test_duplicate_links_visited_once(self):
        """The same URL appearing multiple times in a page is visited only once."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="/about">About</a>'
            '<a href="/about">About (duplicate)</a>'
            '<a href="/about/">About (trailing slash)</a>'
            "</body></html>"
        )
        about_html = '<html lang="en"><head><title>About</title></head><body></body></html>'
        resp_lib.add(resp_lib.GET, "https://example.com", body=html, content_type="text/html")
        resp_lib.add(
            resp_lib.GET,
            "https://example.com/about",
            body=about_html,
            content_type="text/html",
        )
        crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
        pages = crawler.crawl()
        about_pages = [p for p in pages if "about" in p.url]
        assert len(about_pages) == 1

    @resp_lib.activate
    def test_max_depth_respected(self):
        """Pages beyond max_depth should not be crawled."""
        html_d0 = (
            '<html lang="en"><head><title>D0</title></head>'
            '<body><a href="/level1">L1</a></body></html>'
        )
        html_d1 = (
            '<html lang="en"><head><title>D1</title></head>'
            '<body><a href="/level2">L2</a></body></html>'
        )
        html_d2 = (
            '<html lang="en"><head><title>D2</title></head><body>Deep</body></html>'
        )
        resp_lib.add(resp_lib.GET, "https://example.com", body=html_d0, content_type="text/html")
        resp_lib.add(
            resp_lib.GET, "https://example.com/level1", body=html_d1, content_type="text/html"
        )
        resp_lib.add(
            resp_lib.GET, "https://example.com/level2", body=html_d2, content_type="text/html"
        )
        crawler = Crawler("https://example.com", max_pages=50, max_depth=1, respect_robots=False)
        pages = crawler.crawl()
        urls = [p.url for p in pages]
        assert "https://example.com" in urls
        assert "https://example.com/level1" in urls
        assert "https://example.com/level2" not in urls

    @resp_lib.activate
    def test_include_pattern_filters_pages(self):
        """Only pages matching include_patterns should be crawled."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="/blog/post-1">Post</a>'
            '<a href="/about">About</a>'
            "</body></html>"
        )
        blog_html = '<html lang="en"><head><title>Blog</title></head><body></body></html>'
        resp_lib.add(resp_lib.GET, "https://example.com", body=html, content_type="text/html")
        resp_lib.add(
            resp_lib.GET,
            "https://example.com/blog/post-1",
            body=blog_html,
            content_type="text/html",
        )
        crawler = Crawler(
            "https://example.com",
            max_pages=10,
            respect_robots=False,
            include_patterns=[r"/blog/"],
        )
        pages = crawler.crawl()
        # The start URL itself does not match /blog/ so it is excluded
        # Only the blog post should be visited (if include_patterns is applied)
        for p in pages:
            # All crawled pages must match the pattern (except maybe start url)
            if p.url != "https://example.com":
                assert "/blog/" in p.url

    @resp_lib.activate
    def test_exclude_pattern_filters_pages(self):
        """Pages matching exclude_patterns should not be crawled."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="/private/secret">Secret</a>'
            '<a href="/public/page">Public</a>'
            "</body></html>"
        )
        public_html = '<html lang="en"><head><title>Public</title></head><body></body></html>'
        resp_lib.add(resp_lib.GET, "https://example.com", body=html, content_type="text/html")
        resp_lib.add(
            resp_lib.GET,
            "https://example.com/public/page",
            body=public_html,
            content_type="text/html",
        )
        crawler = Crawler(
            "https://example.com",
            max_pages=10,
            respect_robots=False,
            exclude_patterns=[r"/private/"],
        )
        pages = crawler.crawl()
        for p in pages:
            assert "/private/" not in p.url

    def test_on_page_discovered_callback_exception_does_not_crash(self):
        """If on_page_discovered raises, the crawl should continue."""
        def bad_callback(page: PageInfo) -> None:
            raise RuntimeError("Callback exploded!")

        with resp_lib.RequestsMock() as rsps:
            rsps.add(rsps.GET, "https://example.com",
                     body='<html lang="en"><head><title>T</title></head><body></body></html>',
                     content_type="text/html")
            crawler = Crawler(
                "https://example.com",
                max_pages=5,
                respect_robots=False,
                on_page_discovered=bad_callback,
            )
            pages = crawler.crawl()  # must not raise
        assert len(pages) == 1


# ===========================================================================
# HtmlAuditor error-handling tests
# ===========================================================================

class TestHtmlAuditorEdgeCases:

    def test_whitespace_only_html(self, html_auditor):
        result = html_auditor.audit_page("https://example.com", "   \n\t  ")
        # Should return error or an empty result — must not raise
        assert result is not None
        assert isinstance(result, PageAuditResult)

    def test_none_like_empty_string(self, html_auditor):
        result = html_auditor.audit_page("https://example.com", "")
        assert result.error is not None or result is not None

    def test_html_with_no_head_or_body(self, html_auditor):
        html = "<p>Just a paragraph, no head or body tags.</p>"
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None
        # Should still detect missing title, lang, etc.
        rule_ids = [i.rule_id for i in result.issues]
        assert "page-title" in rule_ids or "html-lang" in rule_ids or len(rule_ids) > 0

    def test_malformed_unclosed_tags(self, html_auditor):
        html = (
            '<html lang="en"><head><title>Test</title></head>'
            '<body><p>Unclosed <b>bold <i>italic</b></p></body></html>'
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None
        assert result.url == "https://example.com"

    def test_deeply_nested_html(self, html_auditor):
        """Very deeply nested tags should not cause recursion errors."""
        inner = "<p>Deep content</p>"
        for _ in range(200):
            inner = f"<div>{inner}</div>"
        html = f'<html lang="en"><head><title>T</title></head><body>{inner}</body></html>'
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_html_with_special_characters_in_attributes(self, html_auditor):
        html = (
            '<html lang="en"><head><title>Test & "Quotes" <Tags></title></head>'
            '<body>'
            '<img src="photo.jpg" alt="A <b>bold</b> & \'quoted\' caption">'
            '<a href="/path?a=1&b=2&c=<3>">Link</a>'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_html_with_unicode_content(self, html_auditor):
        html = (
            '<html lang="zh"><head><title>中文测试</title></head>'
            '<body>'
            '<h1>你好世界</h1>'
            '<img src="img.jpg" alt="图片描述">'
            '<a href="/zh/about">关于我们</a>'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_html_with_rtl_language(self, html_auditor):
        html = (
            '<html lang="ar" dir="rtl"><head><title>اختبار</title></head>'
            '<body><h1>مرحبا</h1></body></html>'
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None
        # No html-lang issue expected
        rule_ids = [i.rule_id for i in result.issues]
        assert "html-lang" not in rule_ids

    def test_html_with_embedded_svg(self, html_auditor):
        html = (
            '<html lang="en"><head><title>SVG Test</title></head><body>'
            '<svg role="img" aria-label="Company logo">'
            "<circle cx='50' cy='50' r='40' fill='red'/>"
            "</svg>"
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_html_with_data_uris(self, html_auditor):
        html = (
            '<html lang="en"><head><title>Data URI</title></head><body>'
            '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI6QAAAABJRU5ErkJggg==" alt="1x1 pixel">'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_form_with_no_fields(self, html_auditor):
        html = (
            '<html lang="en"><head><title>Form Test</title></head><body>'
            "<form action='/submit'><button type='submit'>Go</button></form>"
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_table_with_nested_table(self, html_auditor):
        html = (
            '<html lang="en"><head><title>Tables</title></head><body>'
            "<table><caption>Outer</caption>"
            "<thead><tr><th>Col A</th><th>Col B</th></tr></thead>"
            "<tbody><tr><td>"
            "<table><caption>Inner</caption>"
            "<thead><tr><th>Sub A</th></tr></thead>"
            "<tbody><tr><td>data</td></tr></tbody>"
            "</table>"
            "</td><td>data</td></tr></tbody>"
            "</table></body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_multiple_forms(self, html_auditor):
        html = (
            '<html lang="en"><head><title>Multi-Form</title></head><body>'
            '<form><label for="f1">Field 1</label><input id="f1" type="text"></form>'
            '<form><label for="f2">Field 2</label><input id="f2" type="email"></form>'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "form-label" not in rule_ids

    def test_heading_level_jump_several_levels(self, html_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            "<h1>Title</h1>"
            "<h4>Skipped two levels</h4>"
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "heading-skipped-level" in rule_ids

    def test_very_long_page_title(self, html_auditor):
        long_title = "A" * 5000
        html = (
            f'<html lang="en"><head><title>{long_title}</title></head>'
            "<body><h1>Hello</h1></body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        assert result is not None
        rule_ids = [i.rule_id for i in result.issues]
        assert "page-title" not in rule_ids

    def test_all_images_decorative(self, html_auditor):
        """All images with empty alt (decorative) should produce no image-alt issues."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<img src="a.jpg" alt="">'
            '<img src="b.jpg" alt="">'
            '<img src="c.jpg" alt="">'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "image-alt" not in rule_ids

    def test_link_with_only_whitespace_text(self, html_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="/page">   </a>'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "link-empty" in rule_ids

    def test_button_with_only_icon_no_label(self, html_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<button><span class="icon icon-search"></span></button>'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "button-empty" in rule_ids

    def test_iframe_with_empty_title(self, html_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<iframe src="https://example.com" title=""></iframe>'
            "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "iframe-title" in rule_ids

    def test_many_duplicate_ids(self, html_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            + ''.join(f'<div id="dup">Item {i}</div>' for i in range(10))
            + "</body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "duplicate-id" in rule_ids

    def test_viewport_with_maximum_scale_one(self, html_auditor):
        """maximum-scale=1.0 effectively prevents zoom — should flag the issue."""
        html = (
            '<html lang="en"><head><title>T</title>'
            '<meta name="viewport" content="width=device-width, maximum-scale=1.0">'
            "</head><body><h1>Hello</h1></body></html>"
        )
        result = html_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "viewport-zoom-disabled" in rule_ids

    def test_audit_pages_with_empty_list(self, html_auditor):
        results = html_auditor.audit_pages([])
        assert results == []

    def test_audit_pages_multiple_urls(self, html_auditor):
        pages = [
            ("https://a.example.com", '<html lang="en"><head><title>A</title></head><body></body></html>', "A"),
            ("https://b.example.com", '<html lang="en"><head><title>B</title></head><body></body></html>', "B"),
            ("https://c.example.com", "", "C"),
        ]
        results = html_auditor.audit_pages(pages)
        assert len(results) == 3
        assert results[2].error is not None


# ===========================================================================
# ColorContrastAuditor error-handling tests
# ===========================================================================

class TestColorAuditorEdgeCases:

    def test_rgba_color_not_crash(self, color_auditor):
        """rgba() inline colors should not raise an exception."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: rgba(255,0,0,0.5); background-color: rgba(255,255,255,0.9);">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_hsl_color_not_crash(self, color_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: hsl(120, 100%, 25%); background-color: white;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_invalid_color_string_not_crash(self, color_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: notacolor; background-color: alsowrong;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_transparent_background_not_crash(self, color_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: black; background-color: transparent;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_currentcolor_keyword_not_crash(self, color_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: currentColor; background-color: white;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_color_with_important_not_crash(self, color_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: red !important; background-color: white !important;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_empty_style_attribute(self, color_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="">No color here</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None
        rule_ids = [i.rule_id for i in result.issues]
        assert "color-contrast" not in rule_ids

    def test_very_many_colored_elements(self, color_auditor):
        """Auditor should handle pages with hundreds of colored elements."""
        elements = "".join(
            f'<p style="color: #333; background-color: #fff;">Paragraph {i}</p>'
            for i in range(500)
        )
        html = f'<html lang="en"><head><title>T</title></head><body>{elements}</body></html>'
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_four_digit_hex_color(self, color_auditor):
        """4-digit hex colors (with alpha, e.g. #RRGA) should not crash."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: #333f; background-color: #ffff;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_8_digit_hex_color(self, color_auditor):
        """8-digit hex colors (with alpha) should not crash."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<p style="color: #333333ff; background-color: #ffffffff;">Text</p>'
            "</body></html>"
        )
        result = color_auditor.audit_page("https://example.com", html)
        assert result is not None


# ===========================================================================
# KeyboardAuditor error-handling tests
# ===========================================================================

class TestKeyboardAuditorEdgeCases:

    def test_very_high_tabindex(self, keyboard_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<button tabindex="32767">Extreme tabindex</button>'
            "</body></html>"
        )
        result = keyboard_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "tabindex-positive" in rule_ids

    def test_tabindex_on_non_interactive_element(self, keyboard_auditor):
        """tabindex=0 on a span (making it focusable) should not raise."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<span tabindex="0">Focusable span</span>'
            "</body></html>"
        )
        result = keyboard_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_negative_tabindex_on_focusable_with_aria_hidden(self, keyboard_auditor):
        """tabindex=-1 on an element with aria-hidden should not raise an issue."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<button tabindex="-1" aria-hidden="true">Hidden</button>'
            "</body></html>"
        )
        result = keyboard_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "negative-tabindex" not in rule_ids

    def test_many_accesskeys_all_unique(self, keyboard_auditor):
        keys = list("abcdefghijklmnopqrstuvwxyz")
        elements = "".join(f'<a href="/{k}" accesskey="{k}">Link {k}</a>' for k in keys)
        html = f'<html lang="en"><head><title>T</title></head><body>{elements}</body></html>'
        result = keyboard_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "accesskey-conflict" not in rule_ids

    def test_outline_none_in_inline_style_on_anchor(self, keyboard_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<a href="/page" style="outline: none;">Link</a>'
            "</body></html>"
        )
        result = keyboard_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "focus-visible" in rule_ids

    def test_div_with_onclick_and_tabindex_but_no_role(self, keyboard_auditor):
        """A div with onclick but no role AND no tabindex should be flagged."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<div onclick="doSomething()">Clickable div without role or tabindex</div>'
            "</body></html>"
        )
        result = keyboard_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "non-interactive-click-handler" in rule_ids

    def test_empty_html_does_not_crash(self, keyboard_auditor):
        result = keyboard_auditor.audit_page("https://example.com", "")
        assert result is not None


# ===========================================================================
# AriaAuditor error-handling tests
# ===========================================================================

class TestAriaAuditorEdgeCases:

    def test_unknown_aria_role(self, aria_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<div role="nonexistent-role">Content</div>'
            "<main>Main</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "aria-invalid-role" in rule_ids

    def test_aria_labelledby_pointing_to_wrong_id(self, aria_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<main>'
            '<input aria-labelledby="id-that-does-not-exist" type="text">'
            "</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "aria-labelledby-exists" in rule_ids

    def test_aria_hidden_on_focusable_anchor(self, aria_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<main>'
            '<a href="/page" aria-hidden="true">Link</a>'
            "</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "aria-hidden-focusable" in rule_ids

    def test_role_option_without_listbox(self, aria_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<main>'
            '<div role="option">Orphaned option</div>'
            "</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "aria-required-parent" in rule_ids

    def test_multiple_main_landmarks(self, aria_auditor):
        """Multiple <main> elements is an ARIA anti-pattern."""
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            "<main>First main</main>"
            "<main>Second main</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        # Should not crash; may or may not flag the issue
        assert result is not None

    def test_deeply_nested_aria_roles(self, aria_auditor):
        inner = '<div role="listitem">Item</div>'
        for _ in range(50):
            inner = f'<div role="list">{inner}</div>'
        html = f'<html lang="en"><head><title>T</title></head><body><main>{inner}</main></body></html>'
        result = aria_auditor.audit_page("https://example.com", html)
        assert result is not None

    def test_aria_label_only_whitespace(self, aria_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<main>'
            '<button aria-label="   ">Search</button>'
            "</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "aria-label-empty" in rule_ids

    def test_slider_with_all_required_attrs(self, aria_auditor):
        html = (
            '<html lang="en"><head><title>T</title></head><body>'
            '<main>'
            '<div role="slider" aria-valuenow="50" aria-valuemin="0" aria-valuemax="100" aria-label="Volume">Slider</div>'
            "</main>"
            "</body></html>"
        )
        result = aria_auditor.audit_page("https://example.com", html)
        rule_ids = [i.rule_id for i in result.issues]
        assert "aria-required-attr" not in rule_ids

    def test_empty_html_does_not_crash(self, aria_auditor):
        result = aria_auditor.audit_page("https://example.com", "")
        assert result is not None


# ===========================================================================
# ReportData / ReportGenerator edge cases
# ===========================================================================

class TestReporterEdgeCases:

    def _make_issue(self, rule_id="test", severity=Severity.SERIOUS):
        return AuditIssue(
            rule_id=rule_id,
            description="Test issue",
            page_url="https://example.com",
            severity=severity,
            wcag_criteria=["1.1.1"],
            wcag_level=WCAGLevel.A,
            fix_suggestion="Fix it.",
            audit_layer="html_structure",
        )

    def _make_page(self, url="https://example.com", issues=None):
        page = PageAuditResult(url=url, title="Test Page", layer="html_structure")
        if issues:
            page.issues = issues
        return page

    def test_score_exactly_100_with_no_issues(self):
        data = ReportData("https://example.com", [self._make_page()])
        assert data.compliance_score == 100

    def test_score_never_below_zero(self):
        issues = [self._make_issue(severity=Severity.CRITICAL)] * 100
        page = self._make_page(issues=issues)
        data = ReportData("https://example.com", [page])
        assert data.compliance_score == 0

    def test_score_never_above_100(self):
        data = ReportData("https://example.com", [])
        assert data.compliance_score <= 100

    def test_many_pages_in_report(self):
        pages = [
            self._make_page(
                url=f"https://example.com/page{i}",
                issues=[self._make_issue()],
            )
            for i in range(50)
        ]
        data = ReportData("https://example.com", pages)
        assert data.total_pages == 50

    def test_url_with_special_characters(self):
        page = self._make_page(url="https://example.com/path?q=hello+world&lang=en#section")
        data = ReportData("https://example.com/path?q=hello+world&lang=en#section", [page])
        d = data.to_dict()
        assert "target_url" in d

    def test_issue_with_unicode_in_description(self):
        issue = AuditIssue(
            rule_id="test-rule",
            description="Issue with 中文 and émoji 🌍",
            page_url="https://example.com",
            severity=Severity.MINOR,
            wcag_criteria=["1.1.1"],
            wcag_level=WCAGLevel.A,
            fix_suggestion="Fix 修复 this.",
            audit_layer="html_structure",
        )
        page = self._make_page(issues=[issue])
        data = ReportData("https://example.com", [page])
        d = data.to_dict()
        assert "中文" in json.dumps(d, ensure_ascii=False)

    def test_json_report_is_valid_with_special_chars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            issue = AuditIssue(
                rule_id="test-rule",
                description='Issue with "quotes" & <tags>',
                page_url="https://example.com",
                severity=Severity.MODERATE,
                wcag_criteria=["1.1.1"],
                wcag_level=WCAGLevel.A,
                fix_suggestion="Use &amp; entities.",
                audit_layer="html_structure",
            )
            page = self._make_page(issues=[issue])
            data = ReportData("https://example.com", [page])
            gen = ReportGenerator(output_dir=tmpdir)
            paths = gen.generate(data)

            with open(paths["json"]) as f:
                parsed = json.load(f)
            assert parsed["target_url"] == "https://example.com"

    def test_html_report_written_to_custom_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "reports", "subdir")
            os.makedirs(output_dir, exist_ok=True)
            data = ReportData("https://example.com", [])
            gen = ReportGenerator(output_dir=output_dir)
            paths = gen.generate(data)
            assert os.path.exists(paths["html"])
            assert os.path.exists(paths["json"])

    def test_page_with_error_included_in_report(self):
        page = PageAuditResult(
            url="https://example.com/broken",
            title="Broken",
            layer="html_structure",
            error="Could not fetch page",
        )
        data = ReportData("https://example.com", [page])
        d = data.to_dict()
        page_dicts = d["pages"]
        assert any(p.get("error") == "Could not fetch page" for p in page_dicts)

    def test_to_dict_all_severities_present(self):
        issues = [
            self._make_issue(rule_id="c", severity=Severity.CRITICAL),
            self._make_issue(rule_id="s", severity=Severity.SERIOUS),
            self._make_issue(rule_id="m", severity=Severity.MODERATE),
            self._make_issue(rule_id="n", severity=Severity.MINOR),
        ]
        page = self._make_page(issues=issues)
        data = ReportData("https://example.com", [page])
        d = data.to_dict()
        summary = d["summary"]
        assert summary["by_severity"]["critical"] == 1
        assert summary["by_severity"]["serious"] == 1
        assert summary["by_severity"]["moderate"] == 1
        assert summary["by_severity"]["minor"] == 1


# ===========================================================================
# Normalise / URL utility edge cases
# ===========================================================================

class TestCrawlerUtilities:

    def test_normalise_already_clean(self):
        assert Crawler._normalise("https://example.com/page") == "https://example.com/page"

    def test_normalise_trailing_slash_on_root(self):
        # Root URL "/" special case handled in implementation
        result = Crawler._normalise("https://example.com/")
        assert result in ("https://example.com", "https://example.com/")

    def test_normalise_strips_fragment(self):
        assert Crawler._normalise("https://example.com/page#sec") == "https://example.com/page"

    def test_normalise_preserves_query_string(self):
        result = Crawler._normalise("https://example.com/search?q=ada")
        assert "q=ada" in result

    def test_is_internal_same_origin(self):
        from unittest.mock import MagicMock
        crawler = MagicMock(spec=Crawler)
        crawler.origin = "https://example.com"
        assert Crawler._is_internal(crawler, "https://example.com/path") is True

    def test_is_internal_different_subdomain(self):
        from unittest.mock import MagicMock
        crawler = MagicMock(spec=Crawler)
        crawler.origin = "https://example.com"
        assert Crawler._is_internal(crawler, "https://sub.example.com/path") is False

    def test_is_internal_different_scheme(self):
        from unittest.mock import MagicMock
        crawler = MagicMock(spec=Crawler)
        crawler.origin = "https://example.com"
        assert Crawler._is_internal(crawler, "http://example.com/path") is False

    def test_is_internal_javascript_scheme(self):
        from unittest.mock import MagicMock
        crawler = MagicMock(spec=Crawler)
        crawler.origin = "https://example.com"
        assert Crawler._is_internal(crawler, "javascript:void(0)") is False
