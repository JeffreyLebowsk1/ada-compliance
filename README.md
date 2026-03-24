# ada-compliance

> **A thorough, multi-pass ADA/WCAG 2.2 compliance auditing bot for websites.**

Automatically crawls an entire website and audits every page across 6 progressive
layers, building from static analysis through live browser evaluation and finally
AI-powered visual inspection.  Results are compiled into a scored HTML + JSON report
with specific remediation guidance for every issue found.

---

## Features

| Audit Layer | Tool | What it checks |
|---|---|---|
| **1 — axe-core** | Playwright + axe-core | 100+ automated WCAG rules in a real browser |
| **2 — HTML Structure** | BeautifulSoup | Headings, images, links, forms, tables, skip links, iframes, video/audio, viewport, autocomplete |
| **3 — Color Contrast** | Custom WCAG math | WCAG 1.4.3 (AA) and 1.4.6 (AAA) contrast ratios from inline styles |
| **4 — Keyboard Navigation** | BeautifulSoup | tabindex ordering, outline removal, click-only divs, accesskey conflicts |
| **5 — ARIA & Landmarks** | BeautifulSoup | Valid roles, required attributes, landmark regions, aria-hidden on focusable, aria-labelledby resolution |
| **6 — AI Vision** | GPT-4o (optional) | Visual contrast, images of text, missing focus indicators, color-only information |
| **7 — Confirmation Pass** | Layers 2 + 5 | Re-audits all pages with critical issues to confirm findings |

**Produces:**
- HTML report with compliance score, charts, expandable per-page findings, remediation guide
- JSON report for CI integration and programmatic processing
- Exit code `1` if critical issues are found (ideal for CI gates)

---

## Requirements

- Python 3.10+
- For axe-core/vision audits: Chromium (installed via Playwright)
- For AI vision: OpenAI API key with GPT-4o access

---

## Installation

```bash
# Clone the repository
git clone https://github.com/JeffreyLebowsk1/ada-compliance.git
cd ada-compliance

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install the package and all dependencies
pip install -e .

# Install Playwright's Chromium browser (required for axe + vision layers)
playwright install chromium
```

---

## Quick Start

```bash
# Basic audit — crawls up to 100 pages, runs all static layers + axe-core
ada-bot audit https://example.com

# With AI vision (requires OPENAI_API_KEY)
OPENAI_API_KEY=sk-... ada-bot audit https://example.com --vision

# Fast static-only audit (no browser needed)
ada-bot audit https://example.com --no-axe

# Limit scope
ada-bot audit https://example.com --max-pages 20 --max-depth 2

# Custom output directory
ada-bot audit https://example.com --output ./my-reports

# Only audit pages matching a pattern
ada-bot audit https://example.com --include "/products/.*"

# Exclude certain paths
ada-bot audit https://example.com --exclude "/admin/.*" --exclude "/api/.*"
```

Reports are saved to `./ada_reports/report.html` and `./ada_reports/report.json` by default.

---

## CLI Reference

```
Usage: ada-bot audit [OPTIONS] URL

Options:
  --max-pages INTEGER     Maximum pages to crawl (default: 100)
  --max-depth INTEGER     Maximum crawl depth (default: 8)
  --timeout INTEGER       HTTP request timeout in seconds (default: 30)
  --output TEXT           Output directory for reports (default: ada_reports)
  --no-html               Skip HTML structure audit (Layer 2)
  --no-color              Skip color contrast audit (Layer 3)
  --no-keyboard           Skip keyboard navigation audit (Layer 4)
  --no-aria               Skip ARIA/landmark audit (Layer 5)
  --no-axe                Skip axe-core browser audit (Layer 1)
  --vision                Enable AI vision audit — Layer 6 (requires OPENAI_API_KEY)
  --no-robots             Ignore robots.txt
  --no-headless           Run browser visibly (for debugging)
  --axe-script PATH       Path to local axe.min.js (uses CDN otherwise)
  --openai-key TEXT       OpenAI API key (can also be set via OPENAI_API_KEY env var)
  --include TEXT          URL regex to include (repeatable)
  --exclude TEXT          URL regex to exclude (repeatable)
  --screenshot-dir PATH   Directory for vision screenshots
  --version               Show version
  --help                  Show this message and exit
```

---

## Multi-Pass Audit Pipeline

```
Pass 1  Crawl        Discover all pages via breadth-first crawl
Pass 2  HTML         Static HTML structure checks (BeautifulSoup)
Pass 3  Contrast     WCAG color contrast calculation
Pass 4  Keyboard     Keyboard reachability and focus checks
Pass 5  ARIA         ARIA roles, landmarks, attributes
Pass 6  axe-core     100+ automated rules in Chromium via Playwright
Pass 7  AI Vision    GPT-4o screenshot analysis (optional)
Pass 8  Confirm      Re-audit pages with critical issues to confirm
```

Each layer builds on the previous ones.  The final confirmation pass (Pass 8)
re-runs the two most comprehensive static auditors against every page that had
at least one critical issue, ensuring no false positives make it into the report.

---

## WCAG Coverage

The bot checks all four WCAG 2.2 principles across levels A, AA, and AAA:

- **Perceivable**: 1.1.1, 1.2.1–1.2.5, 1.3.1–1.3.6, 1.4.1–1.4.6, 1.4.10–1.4.13
- **Operable**: 2.1.1–2.1.4, 2.4.1–2.4.11
- **Understandable**: 3.1.1–3.1.2, 3.2.1–3.2.4, 3.3.1–3.3.4
- **Robust**: 4.1.1–4.1.3

---

## CI Integration

```yaml
# .github/workflows/accessibility.yml
- name: ADA Compliance Audit
  run: |
    pip install -e .
    playwright install chromium
    ada-bot audit ${{ secrets.SITE_URL }} --max-pages 50
  # Exit code 1 = critical issues found → fails the workflow
```

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_html_auditor.py -v
```

---

## Report Example

The HTML report includes:
- **Compliance score** (0–100) based on issue severity
- **Charts** showing issues by severity and audit layer
- **WCAG violation breakdown** with counts per criterion
- **Per-page findings** with expandable details
- **Element snippets** showing the exact HTML causing each issue
- **Fix suggestions** for every single issue
- **Remediation priority table** sorted by issue frequency

---

## License

MIT
