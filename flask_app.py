# file: /home/seoblogy/mysite/flask_app.py

import sys
import os
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from flask_cors import CORS
from flask import Flask, request, jsonify
from collections import OrderedDict, Counter

# --- Basic Setup ---
app = Flask(__name__)
# IMPORTANT: Replace 'https://www.your-wordpress-domain.com' with your actual WordPress URL.
# This explicitly allows your front-end to connect to this API.
CORS(app, origins="https://your-wordpress-domain.com")

# --- Utility Functions ---
def clean_text(text):
    """Clean text for keyword extraction."""
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    return text.lower()

def extract_keywords(text, top_n=20):
    """Extract most frequent keywords excluding stopwords."""
    stopwords = set([
        "the","and","to","of","a","in","for","is","on","with","that","as","by",
        "this","an","be","or","it","are","at","from","was","but","not","have","has"
    ])
    words = clean_text(text).split()
    words = [w for w in words if w not in stopwords and len(w) > 2]
    freq = Counter(words)
    return dict(freq.most_common(top_n))

def get_redirected_domain(url):
    """Follow redirects and return final domain."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        return urlparse(r.url).netloc
    except:
        return urlparse(url).netloc

def heading_structure_score(soup):
    """Check if headings follow proper hierarchy (H1->H2->H3, etc.)."""
    headings = [tag.name for tag in soup.find_all(re.compile(r"h[1-6]"))]
    if not headings:
        return 0
    score = 100
    last_level = 0
    for h in headings:
        level = int(h[1])
        if last_level and level - last_level > 1:
            score -= 20
        last_level = level
    return max(score, 0)

# --- API Routes ---
@app.route("/")
def home():
    return "✅ SEO Audit API is running! Use the /audit endpoint."

@app.route("/audit")
def audit():
    url = request.args.get("url")
    if not url:
        return jsonify({"success": False, "error": "URL parameter is missing."}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Failed to fetch the URL: {str(e)}"}), 400

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        # --- Build Ordered Report ---
        report = OrderedDict()
        report["URL"] = url
        report["Status"] = response.status_code

        # Title
        title = soup.title.string.strip() if soup.title else "Not Found"
        report["Title"] = title
        report["Title Length"] = len(title) if title != "Not Found" else 0

        # Meta description
        desc = soup.find("meta", attrs={"name": "description"})
        meta_desc = desc["content"].strip() if desc and desc.has_attr("content") else "Not Found"
        report["Meta Description"] = meta_desc
        report["Meta Description Length"] = len(meta_desc) if meta_desc != "Not Found" else 0

        # Headings
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
        report["Canonical"] = canonical["href"] if canonical and canonical.has_attr("href") else "Not Found"
        robots = soup.find("meta", attrs={"name": "robots"})
        report["Robots"] = robots["content"] if robots and robots.has_attr("content") else "Not Found"

        # HTTPS + Mixed Content
        report["HTTPS"] = "Yes" if url.startswith("https") else "No"
        is_mixed = False
        if report["HTTPS"] == "Yes":
            for tag in soup.find_all(['img', 'script', 'link']):
                src = tag.get('src') or tag.get('href')
                if src and src.startswith("http://"):
                    is_mixed = True
                    break
        report["Mixed Content"] = "Yes" if is_mixed else "No"

        # Word Count
        report["Word Count"] = len(full_text.split())

        # Links
        internal_links, external_links = [], []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            anchor_text = a.get_text(strip=True)
            abs_url = urljoin(url, href)
            link_domain = get_redirected_domain(abs_url)
            if link_domain == domain:
                internal_links.append({"url": abs_url, "anchor": anchor_text})
            else:
                external_links.append({"url": abs_url, "anchor": anchor_text})
        report["Internal Links Count"] = len(internal_links)
        report["External Links Count"] = len(external_links)
        report["Internal Links"] = internal_links[:20]
        report["External Links"] = external_links[:20]

        # Images
        images = soup.find_all("img")
        report["Total Images"] = len(images)
        report["Images Missing ALT"] = sum(1 for img in images if not img.get("alt", "").strip())

        # Schema
        schema_scripts = soup.find_all("script", type="application/ld+json")
        schemas = []
        for s in schema_scripts:
            try:
                schemas.append(json.loads(s.string))
            except:
                continue
        report["Schema Markup"] = schemas if schemas else "Not Found"

        # Favicon + Hreflang
        favicon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
        report["Favicon"] = favicon["href"] if favicon and favicon.has_attr("href") else "Not Found"
        hreflangs = [link["href"] for link in soup.find_all("link", rel="alternate") if link.has_attr("hreflang")]
        report["Hreflang Tags"] = " | ".join(hreflangs) if hreflangs else "Not Found"

        # Keywords + Density
        top_keywords = extract_keywords(full_text)
        total_words = len(full_text.split())
        density = {k: f"{(v/total_words*100):.2f}%" for k, v in top_keywords.items()}
        report["Top Keywords"] = top_keywords
        report["Keyword Density"] = density

        # Heading Structure Score
        report["Heading Structure Score"] = heading_structure_score(soup)

        return jsonify({"success": True, "data": report})

    except Exception as e:
        return jsonify({"success": False, "error": f"An error occurred during analysis: {str(e)}"}), 500
