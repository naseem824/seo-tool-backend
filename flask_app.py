# file: /home/seoblogy/mysite/flask_app.py

import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from flask_cors import CORS
from flask import Flask, request, jsonify, Response
from collections import OrderedDict, Counter

# --- Basic Setup ---
app = Flask(__name__)

# Allow your WP domain(s) + localhost for testing
CORS(app, origins=[
    "https://seoblogy.com",
    "https://www.seoblogy.com",
    "http://localhost:5500",     # optional for local HTML testing
])

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 20  # seconds


# --- Utility Functions ---
def clean_text(text: str) -> str:
    """Clean text for keyword extraction."""
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text or "")
    return text.lower()


def extract_keywords(text: str, top_n: int = 20) -> dict:
    """Extract most frequent keywords excluding stopwords."""
    stopwords = {
        "the","and","to","of","a","in","for","is","on","with","that","as","by",
        "this","an","be","or","it","are","at","from","was","but","not","have","has",
        "you","your","our","their","they","we","he","she","them","his","her","its"
    }
    words = clean_text(text).split()
    words = [w for w in words if w not in stopwords and len(w) > 2]
    freq = Counter(words)
    return dict(freq.most_common(top_n))


def get_redirected_domain(url: str) -> str:
    """Follow redirects (HEAD then GET fallback) and return final domain."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        final_url = r.url
        if not final_url or r.status_code >= 400:
            # some servers block HEAD; try GET (stream to avoid download)
            g = requests.get(url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS, stream=True)
            final_url = g.url
        return urlparse(final_url).netloc
    except Exception:
        return urlparse(url).netloc


def heading_structure_score(soup: BeautifulSoup) -> int:
    """Check if headings follow proper hierarchy (H1->H2->H3, etc.)."""
    headings = [tag.name for tag in soup.find_all(re.compile(r"h[1-6]"))]
    if not headings:
        return 0
    score = 100
    last_level = None
    for h in headings:
        level = int(h[1])
        if last_level is not None and level - last_level > 1:
            score -= 20
        last_level = level
    return max(score, 0)


def build_report(url: str, soup: BeautifulSoup, response_status: int) -> OrderedDict:
    parsed_url = urlparse(url)
    domain = parsed_url.netloc

    report = OrderedDict()
    report["URL"] = url
    report["Status"] = response_status

    # Title
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else "Not Found"
    report["Title"] = title
    report["Title Length"] = len(title) if title != "Not Found" else 0

    # Meta description
    desc = soup.find("meta", attrs={"name": "description"})
    meta_desc = desc.get("content", "").strip() if desc and desc.has_attr("content") else "Not Found"
    report["Meta Description"] = meta_desc
    report["Meta Description Length"] = len(meta_desc) if meta_desc != "Not Found" else 0

    # Headings (H1–H3 per your requirement)
    for i in range(1, 4):
        hs = soup.find_all(f"h{i}")
        report[f"H{i}"] = " | ".join([h.get_text(strip=True) for h in hs]) or "Not Found"

    # Body content (full + paragraphs)
    full_text = soup.get_text(" ", strip=True)
    report["Body Content (Preview)"] = full_text[:5000]  # limit preview
    para_words = " ".join([p.get_text(strip=True) for p in soup.find_all("p")]).split()
    report["Paragraphs"] = " ".join(para_words[:2000])

    # Canonical + Robots
    canonical = soup.find("link", rel="canonical")
    canonical_href = canonical.get("href") if canonical and canonical.has_attr("href") else "Not Found"
    report["Canonical"] = canonical_href
    robots = soup.find("meta", attrs={"name": "robots"})
    report["Robots"] = robots.get("content") if robots and robots.has_attr("content") else "Not Found"

    # HTTPS + Mixed Content
    report["HTTPS"] = "Yes" if url.startswith("https") else "No"
    is_mixed = False
    if report["HTTPS"] == "Yes":
        for tag in soup.find_all(['img', 'script', 'link']):
            src = tag.get('src') or tag.get('href')
            if src and isinstance(src, str) and src.startswith("http://"):
                is_mixed = True
                break
    report["Mixed Content"] = "Yes" if is_mixed else "No"

    # Word Count
    total_words = len(full_text.split())
    report["Word Count"] = total_words

    # Links (resolve redirects to avoid miscount)
    internal_links, external_links = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        anchor_text = a.get_text(strip=True)
        abs_url = urljoin(url, href)
        link_domain = get_redirected_domain(abs_url)
        entry = {"url": abs_url, "anchor": anchor_text}
        if link_domain == domain:
            internal_links.append(entry)
        else:
            external_links.append(entry)
    report["Internal Links Count"] = len(internal_links)
    report["External Links Count"] = len(external_links)
    report["Internal Links"] = internal_links[:20]
    report["External Links"] = external_links[:20]

    # Images
    images = soup.find_all("img")
    report["Total Images"] = len(images)
    report["Images Missing ALT"] = sum(1 for img in images if not (img.get("alt") or "").strip())

    # Schema Markup (JSON-LD)
    schema_scripts = soup.find_all("script", type="application/ld+json")
    schemas = []
    for s in schema_scripts:
        try:
            # handle whitespace / comments or multiple JSON blocks
            raw = s.string or s.get_text() or ""
            raw = raw.strip()
            if not raw:
                continue
            # Some sites embed arrays or multiple JSON objects separated; try loads
            parsed = json.loads(raw)
            schemas.append(parsed)
        except Exception:
            # try to recover common issues: remove HTML comments
            try:
                cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
                schemas.append(json.loads(cleaned))
            except Exception:
                continue
    report["Schema Markup"] = schemas if schemas else "Not Found"

    # Favicon + Hreflang
    favicon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    report["Favicon"] = favicon.get("href") if favicon and favicon.has_attr("href") else "Not Found"
    hreflangs = [link.get("href") for link in soup.find_all("link", rel="alternate") if link.has_attr("hreflang")]
    report["Hreflang Tags"] = " | ".join(hreflangs) if hreflangs else "Not Found"

    # Keywords + Density
    top_keywords = extract_keywords(full_text)
    density = {k: f"{(v / total_words * 100):.2f}%" for k, v in top_keywords.items()} if total_words else {}
    report["Top Keywords"] = top_keywords
    report["Keyword Density"] = density

    # Heading Structure Score
    report["Heading Structure Score"] = heading_structure_score(soup)

    return report


def format_text_report(report: OrderedDict) -> str:
    """Make a human-readable plain-text report."""
    lines = ["SEO Audit Report", "=================="]
    for key, value in report.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            if not value:
                lines.append("  - None")
            else:
                for item in value:
                    if isinstance(item, dict):
                        anchor = item.get("anchor") or item.get("url")
                        url = item.get("url")
                        lines.append(f"  - {anchor}: {url}")
                    else:
                        lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            if not value:
                lines.append("  - Not Found")
            else:
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


# --- API Routes ---
@app.route("/")
def home():
    return "✅ SEO Audit API is running! Use the /audit or /audit-report endpoints."


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/audit")
def audit():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "URL parameter is missing."}), 400

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Failed to fetch the URL: {str(e)}"}), 400

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        report = build_report(url, soup, resp.status_code)
        return jsonify({"success": True, "data": report})
    except Exception as e:
        return jsonify({"success": False, "error": f"An error occurred during analysis: {str(e)}"}), 500


@app.route("/audit-report")
def audit_report():
    """Plain-text version of the audit (good for copy/paste)."""
    url = request.args.get("url", "").strip()
    if not url:
        return Response("URL parameter is missing.", status=400, mimetype="text/plain")

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return Response(f"Failed to fetch the URL: {str(e)}", status=400, mimetype="text/plain")

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        report = build_report(url, soup, resp.status_code)
        text = format_text_report(report)
        return Response(text, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        return Response(f"An error occurred during analysis: {str(e)}", status=500, mimetype="text/plain")
