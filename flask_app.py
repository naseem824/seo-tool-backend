import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from flask_cors import CORS
from flask import Flask, request, jsonify, Response
from collections import OrderedDict, Counter
import spacy

# --- A++ MODIFICATION: Basic Setup ---
app = Flask(__name__)
# Use a larger, more accurate model for better semantic understanding.
# This will use more memory but provides superior results.
SPACY_MODEL = "en_core_web_lg" 

# --- A++ MODIFICATION: Load the spaCy model intelligently ---
try:
    nlp = spacy.load(SPACY_MODEL)
except OSError:
    print(f"Downloading spaCy model '{SPACY_MODEL}'...")
    from spacy.cli import download
    download(SPACY_MODEL)
    nlp = spacy.load(SPACY_MODEL)

# --- CORS and Constants (unchanged but good) ---
CORS(app, origins=["https://seoblogy.com", "https://www.seoblogy.com", "http://localhost:5500"])
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_TIMEOUT = 20
MAX_CONTENT_SIZE = 500000 # Limit content size to avoid excessive memory usage

# --- A++ MODIFICATION: Advanced Semantic & Content Analysis Engine ---
def analyze_content_semantics(full_text: str, soup: BeautifulSoup) -> dict:
    """
    Performs a deep semantic analysis of the page content, weighting phrases
    by their HTML importance and identifying named entities.
    """
    # A++ FEATURE: Filter out generic, low-value phrases for cleaner results.
    stop_phrases = {
        "many people", "a lot", "some things", "the fact", "the way", "the world",
        "your business", "our team", "our clients", "their website", "a new website",
        "many uae businesses", "a few months", "a long time", "all the things"
    }
    
    # A++ FEATURE: Weight phrases based on the SEO importance of their HTML tag.
    tag_weights = {
        "title": 10,
        "h1": 7,
        "h2": 5,
        "h3": 3,
        "strong": 2,
        "b": 2,
        "p": 1,
        "li": 1
    }

    doc = nlp(full_text[:300000]) # Process a larger but still limited amount of text
    
    # --- 1. Weighted Keyword Phrase Extraction ---
    weighted_phrase_counts = Counter()
    for tag, weight in tag_weights.items():
        elements = soup.find_all(tag)
        for element in elements:
            text = element.get_text(strip=True).lower()
            if not text:
                continue
            
            element_doc = nlp(text)
            for chunk in element_doc.noun_chunks:
                phrase = chunk.text
                if len(phrase.split()) > 1 and len(phrase.split()) < 6 and phrase not in stop_phrases:
                    weighted_phrase_counts[phrase] += weight

    if not weighted_phrase_counts:
        return {"error": "Not enough meaningful content found for semantic analysis."}
        
    main_phrases = [phrase for phrase, count in weighted_phrase_counts.most_common(15)]
    main_phrase_docs = {phrase: nlp(phrase) for phrase in main_phrases}

    # --- 2. Semantic Clustering ---
    semantic_clusters = OrderedDict()
    all_key_phrases = list(weighted_phrase_counts.keys())
    all_phrase_docs = [nlp(phrase) for phrase in all_key_phrases]
    
    for phrase, doc1 in main_phrase_docs.items():
        if not doc1.has_vector or doc1.vector_norm == 0:
            continue
        
        related = []
        # A++ TWEAK: Adjust similarity threshold for better topical relevance.
        for doc2 in all_phrase_docs:
            if doc1.text == doc2.text or not doc2.has_vector or doc2.vector_norm == 0:
                continue
            if doc1.similarity(doc2) > 0.75: # Higher threshold for tighter clusters
                related.append(doc2.text)
        
        if related:
            semantic_clusters[phrase] = list(set(related))

    # --- 3. Named Entity Recognition (NER) ---
    entities = {}
    allowed_labels = ["ORG", "GPE", "PRODUCT", "PERSON", "EVENT"] # Organizations, Places, Products etc.
    for ent in doc.ents:
        if ent.label_ in allowed_labels:
            label = ent.label_
            text = ent.text.strip()
            if label not in entities:
                entities[label] = Counter()
            entities[label][text] += 1
            
    # Format entities for the final report
    final_entities = {label: [item for item, count in data.most_common(5)] for label, data in entities.items()}

    return {
        "Topically Important Phrases": main_phrases,
        "Semantic Keyword Clusters": semantic_clusters if semantic_clusters else "No strong clusters found.",
        "Recognized Named Entities": final_entities if final_entities else "No major entities found."
    }

# --- Utility functions (some are no longer needed or are simplified) ---
def get_redirected_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""

def heading_structure_score(soup: BeautifulSoup) -> int:
    headings = [tag.name for tag in soup.find_all(re.compile(r"h[1-6]"))]
    if not headings or headings[0] != 'h1':
        return 50 # Penalize if no H1
    score = 100
    last_level = 0
    if 'h1' in headings and headings.count('h1') > 1:
        score -= 40 # Heavy penalty for multiple H1s
    
    for h in headings:
        level = int(h[1])
        if last_level != 0 and level - last_level > 1:
            score -= 15 # Penalize for skipping heading levels
        last_level = level
    return max(score, 0)

# --- A++ MODIFICATION: Hierarchical Report Builder ---
def build_report(url: str, soup: BeautifulSoup, response: requests.Response) -> OrderedDict:
    full_text = soup.get_text(" ", strip=True)
    domain = urlparse(url).netloc
    report = OrderedDict()

    # --- Section 1: Core Metrics ---
    title_tag = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta_desc_tag.get("content", "").strip() if meta_desc_tag else ""
    
    report["Core Metrics"] = {
        "URL": url,
        "HTTP Status": response.status_code,
        "Title": title_tag if title_tag else "Not Found",
        "Title Length": len(title_tag),
        "Meta Description": meta_desc if meta_desc else "Not Found",
        "Meta Description Length": len(meta_desc)
    }

    # --- Section 2: Content Analysis ---
    headings = {f"H{i}": [h.get_text(strip=True) for h in soup.find_all(f"h{i}")] for i in range(1, 4)}
    images = soup.find_all("img")

    report["Content Analysis"] = {
        "Word Count": len(full_text.split()),
        "Heading Structure Score (out of 100)": heading_structure_score(soup),
        "Headings": {
            "H1": headings["H1"] if headings["H1"] else "Not Found",
            "H2 Count": len(headings["H2"]),
            "H3 Count": len(headings["H3"]),
        },
        "Image SEO": {
            "Total Images": len(images),
            "Images Missing ALT Text": sum(1 for img in images if not img.get("alt", "").strip())
        }
    }

    # --- Section 3: Semantic Analysis (The A++ Core) ---
    report["Semantic Analysis"] = analyze_content_semantics(full_text, soup)

    # --- Section 4: Technical SEO ---
    canonical_tag = soup.find("link", rel="canonical")
    robots_tag = soup.find("meta", attrs={"name": "robots"})
    
    report["Technical SEO"] = {
        "Canonical URL": canonical_tag.get("href") if canonical_tag else "Not Found",
        "Robots Directive": robots_tag.get("content") if robots_tag else "Not Specified",
        "HTTPS Enabled": "Yes" if url.startswith("https") else "No",
        "Schema Markup Found": "Yes" if soup.find("script", type="application/ld+json") else "No",
    }
    
    # --- Section 5: Link Analysis ---
    internal_links, external_links = [], []
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        link_domain = get_redirected_domain(urljoin(url, href))
        if link_domain == domain:
            internal_links.append(href)
        elif link_domain:
            external_links.append(href)
            
    report["Link Analysis"] = {
        "Internal Links Count": len(internal_links),
        "Unique External Links Count": len(set(external_links)),
    }

    return report


# --- A++ MODIFICATION: Recursive text report formatter for hierarchy ---
def format_text_report_recursive(report_dict, indent=0):
    lines = []
    indent_str = "  " * indent
    for key, value in report_dict.items():
        if isinstance(value, dict):
            lines.append(f"{indent_str}## {key}:")
            lines.extend(format_text_report_recursive(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{indent_str}- {key}:")
            for item in value:
                lines.append(f"{indent_str}  - {item}")
        else:
            lines.append(f"{indent_str}- {key}: {value}")
    return lines

def format_text_report(report: OrderedDict) -> str:
    header = ["SEO Audit Report", "=================="]
    body = format_text_report_recursive(report)
    return "\n".join(header + body)

# --- API Routes (Largely unchanged, but now serve the new report structure) ---
@app.route("/")
def home():
    return "✅ A++ SEO Audit API is running!"

@app.route("/audit")
def audit():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "URL parameter is missing."}), 400

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text[:MAX_CONTENT_SIZE], "html.parser")
        report = build_report(url, soup, resp)
        return jsonify({"success": True, "data": report})
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Target site took too long to respond"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Failed to fetch the URL: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"An error occurred during analysis: {str(e)}"}), 500

@app.route("/audit-report")
def audit_report():
    url = request.args.get("url", "").strip()
    if not url:
        return Response("URL parameter is missing.", status=400, mimetype="text/plain")
        
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text[:MAX_CONTENT_SIZE], "html.parser")
        report = build_report(url, soup, resp)
        text_report = format_text_report(report)
        return Response(text_report, mimetype="text/plain; charset=utf-8")
    except Exception as e: # Catch all exceptions for simplicity in this route
        return Response(f"An error occurred: {str(e)}", status=500, mimetype="text/plain")
