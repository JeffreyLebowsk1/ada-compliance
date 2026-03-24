"""Tests for the web crawler."""
import pytest
import responses as resp_lib
from ada_bot.crawler import Crawler, PageInfo


SIMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Home</title></head>
<body>
  <a href="/about">About</a>
  <a href="/contact">Contact</a>
  <a href="https://external.example.com/page">External</a>
</body>
</html>"""

ABOUT_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>About</title></head>
<body><h1>About us</h1></body>
</html>"""

CONTACT_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Contact</title></head>
<body><h1>Contact us</h1></body>
</html>"""


@resp_lib.activate
def test_crawl_discovers_internal_pages():
    resp_lib.add(resp_lib.GET, "https://example.com",
                 body=SIMPLE_HTML, content_type="text/html")
    resp_lib.add(resp_lib.GET, "https://example.com/about",
                 body=ABOUT_HTML, content_type="text/html")
    resp_lib.add(resp_lib.GET, "https://example.com/contact",
                 body=CONTACT_HTML, content_type="text/html")
    # robots.txt (called automatically)
    resp_lib.add(resp_lib.GET, "https://example.com/robots.txt",
                 body="", status=404)

    crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
    pages = crawler.crawl()

    urls = [p.url for p in pages]
    assert "https://example.com" in urls
    assert "https://example.com/about" in urls
    assert "https://example.com/contact" in urls


@resp_lib.activate
def test_crawl_does_not_follow_external_links():
    resp_lib.add(resp_lib.GET, "https://example.com",
                 body=SIMPLE_HTML, content_type="text/html")
    resp_lib.add(resp_lib.GET, "https://example.com/about",
                 body=ABOUT_HTML, content_type="text/html")
    resp_lib.add(resp_lib.GET, "https://example.com/contact",
                 body=CONTACT_HTML, content_type="text/html")

    crawler = Crawler("https://example.com", max_pages=20, respect_robots=False)
    pages = crawler.crawl()

    urls = [p.url for p in pages]
    assert "https://external.example.com/page" not in urls


@resp_lib.activate
def test_crawl_respects_max_pages():
    # Start page links to many sub-pages
    html = "<html lang='en'><head><title>T</title></head><body>"
    for i in range(20):
        html += f'<a href="/page{i}">Page {i}</a>'
    html += "</body></html>"
    resp_lib.add(resp_lib.GET, "https://example.com", body=html, content_type="text/html")
    for i in range(20):
        resp_lib.add(resp_lib.GET, f"https://example.com/page{i}",
                     body=f"<html><head><title>P{i}</title></head><body></body></html>",
                     content_type="text/html")

    crawler = Crawler("https://example.com", max_pages=5, respect_robots=False)
    pages = crawler.crawl()
    assert len(pages) <= 5


@resp_lib.activate
def test_crawl_handles_http_error():
    resp_lib.add(resp_lib.GET, "https://example.com",
                 body=SIMPLE_HTML, content_type="text/html")
    resp_lib.add(resp_lib.GET, "https://example.com/about", status=404, body="Not found")
    resp_lib.add(resp_lib.GET, "https://example.com/contact",
                 body=CONTACT_HTML, content_type="text/html")

    crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
    pages = crawler.crawl()
    urls = [p.url for p in pages]
    # 404 pages are still recorded
    about_pages = [p for p in pages if p.url == "https://example.com/about"]
    assert about_pages
    assert about_pages[0].status_code == 404


@resp_lib.activate
def test_crawl_skips_non_html():
    html_with_pdf = """<html lang='en'><head><title>T</title></head>
                       <body><a href="/doc.pdf">PDF</a></body></html>"""
    resp_lib.add(resp_lib.GET, "https://example.com",
                 body=html_with_pdf, content_type="text/html")
    resp_lib.add(resp_lib.GET, "https://example.com/doc.pdf",
                 body=b"%PDF-1.4", content_type="application/pdf")

    crawler = Crawler("https://example.com", max_pages=10, respect_robots=False)
    pages = crawler.crawl()

    # PDF page is fetched but its error indicates non-HTML
    pdf_pages = [p for p in pages if "doc.pdf" in p.url]
    if pdf_pages:
        assert pdf_pages[0].error is not None or pdf_pages[0].html == ""


def test_normalise():
    crawler = Crawler.__new__(Crawler)
    from urllib.parse import urlparse
    crawler.origin = "https://example.com"
    # Internal: strips trailing slash
    assert Crawler._normalise("https://example.com/page/") == "https://example.com/page"
    # Strips fragment
    assert Crawler._normalise("https://example.com/page#section") == "https://example.com/page"


def test_is_internal():
    from unittest.mock import MagicMock
    crawler = MagicMock(spec=Crawler)
    crawler.origin = "https://example.com"
    # Use the actual method
    assert Crawler._is_internal(crawler, "https://example.com/page") is True
    assert Crawler._is_internal(crawler, "https://other.com/page") is False
    assert Crawler._is_internal(crawler, "ftp://example.com/file") is False
