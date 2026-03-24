"""
CLI entry point for the ADA Compliance Bot.

Usage examples
--------------
# Audit a website with default settings (HTML + color + keyboard + ARIA + axe):
  ada-bot audit https://example.com

# Audit with AI vision enabled:
  ada-bot audit https://example.com --vision

# Limit crawl depth and pages:
  ada-bot audit https://example.com --max-pages 50 --max-depth 3

# Save reports to a custom directory:
  ada-bot audit https://example.com --output my-reports

# Run only static HTML checks (no browser needed):
  ada-bot audit https://example.com --no-axe --no-vision

# Show version:
  ada-bot --version
"""

from __future__ import annotations

import os
import sys

import click
from colorama import Fore, Style, init as colorama_init

from . import __version__
from .engine import AuditConfig, AuditEngine

colorama_init(autoreset=True)


def _colour_log(msg: str) -> None:
    """Print a log message with ANSI colour highlighting."""
    if msg.startswith("Pass "):
        click.echo(Fore.CYAN + Style.BRIGHT + msg + Style.RESET_ALL)
    elif msg.startswith("  Found:") or msg.startswith("  "):
        click.echo(Fore.WHITE + msg + Style.RESET_ALL)
    elif msg.startswith("✅"):
        click.echo(Fore.GREEN + Style.BRIGHT + msg + Style.RESET_ALL)
    elif msg.startswith("⚠") or "error" in msg.lower():
        click.echo(Fore.YELLOW + msg + Style.RESET_ALL)
    else:
        click.echo(msg)


@click.group()
@click.version_option(version=__version__, prog_name="ada-bot")
def main():
    """ADA Compliance Bot — multi-pass WCAG 2.2 website auditing tool."""


@main.command("audit")
@click.argument("url")
@click.option("--max-pages",  default=100,  show_default=True, help="Maximum pages to crawl.")
@click.option("--max-depth",  default=8,    show_default=True, help="Maximum crawl depth.")
@click.option("--timeout",    default=30,   show_default=True, help="HTTP request timeout (seconds).")
@click.option("--output",     default="ada_reports", show_default=True, help="Output directory for reports.")
@click.option("--no-html",    is_flag=True, default=False, help="Skip HTML structure audit.")
@click.option("--no-color",   is_flag=True, default=False, help="Skip color contrast audit.")
@click.option("--no-keyboard",is_flag=True, default=False, help="Skip keyboard navigation audit.")
@click.option("--no-aria",    is_flag=True, default=False, help="Skip ARIA/landmark audit.")
@click.option("--no-axe",     is_flag=True, default=False, help="Skip axe-core browser audit.")
@click.option("--vision",     is_flag=True, default=False, help="Enable AI vision audit (requires PERPLEXITY_API_KEY).")
@click.option("--no-robots",  is_flag=True, default=False, help="Ignore robots.txt.")
@click.option("--no-headless",is_flag=True, default=False, help="Run browser in visible mode (for debugging).")
@click.option("--axe-script", default=None, help="Path to local axe.min.js (uses CDN if not provided).")
@click.option("--perplexity-key", default=None, envvar="PERPLEXITY_API_KEY", help="Perplexity API key for vision audit.")
@click.option("--include",    multiple=True, help="URL regex pattern to include (can specify multiple).")
@click.option("--exclude",    multiple=True, help="URL regex pattern to exclude (can specify multiple).")
@click.option("--screenshot-dir", default=None, help="Directory for vision screenshots.")
def audit_cmd(
    url, max_pages, max_depth, timeout, output,
    no_html, no_color, no_keyboard, no_aria, no_axe, vision,
    no_robots, no_headless, axe_script, perplexity_key,
    include, exclude, screenshot_dir,
):
    """Audit URL for ADA/WCAG compliance.

    Runs a thorough multi-pass audit across all discovered pages and
    produces HTML + JSON reports.
    """
    click.echo(
        Fore.CYAN + Style.BRIGHT
        + f"\n{'='*60}\n  ADA Compliance Bot v{__version__}\n{'='*60}\n"
        + Style.RESET_ALL
    )

    cfg = AuditConfig(
        url=url,
        max_pages=max_pages,
        max_depth=max_depth,
        crawl_timeout=timeout,
        respect_robots=not no_robots,
        include_patterns=list(include),
        exclude_patterns=list(exclude),
        run_html_audit=not no_html,
        run_color_audit=not no_color,
        run_keyboard_audit=not no_keyboard,
        run_aria_audit=not no_aria,
        run_axe_audit=not no_axe,
        run_vision_audit=vision,
        headless=not no_headless,
        axe_script_path=axe_script,
        perplexity_api_key=perplexity_key,
        vision_screenshot_dir=screenshot_dir or os.path.join(output, "screenshots"),
        output_dir=output,
        on_progress=_colour_log,
    )

    try:
        report_data, paths = AuditEngine(cfg).run()
    except KeyboardInterrupt:
        click.echo(Fore.RED + "\nAudit interrupted by user." + Style.RESET_ALL)
        sys.exit(1)
    except Exception as exc:
        click.echo(Fore.RED + f"\nFatal error: {exc}" + Style.RESET_ALL)
        sys.exit(2)

    # Print summary table
    click.echo("\n" + Fore.CYAN + Style.BRIGHT + "AUDIT SUMMARY" + Style.RESET_ALL)
    click.echo(f"  Score           : {report_data.compliance_score}/100")
    click.echo(f"  Pages audited   : {report_data.total_pages}")
    click.echo(f"  Total issues    : {report_data.total_issues}")
    click.echo(
        Fore.RED + f"  Critical        : {report_data.by_severity.get('critical', 0)}"
        + Style.RESET_ALL
    )
    click.echo(
        Fore.YELLOW + f"  Serious         : {report_data.by_severity.get('serious', 0)}"
        + Style.RESET_ALL
    )
    click.echo(f"  Moderate        : {report_data.by_severity.get('moderate', 0)}")
    click.echo(f"  Minor           : {report_data.by_severity.get('minor', 0)}")
    click.echo(f"\n  HTML report     : {paths['html']}")
    click.echo(f"  JSON report     : {paths['json']}\n")

    # Exit with error code if critical issues found
    if report_data.by_severity.get("critical", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
