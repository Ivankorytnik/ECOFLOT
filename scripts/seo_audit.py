#!/usr/bin/env python3
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://ecoflot.pro"

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.desc = ""
        self.canonical = ""
        self.h1 = []
        self.links = []
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "meta" and a.get("name","").lower() == "description":
            self.desc = a.get("content","").strip()
        elif tag == "link" and a.get("rel","").lower() == "canonical":
            self.canonical = a.get("href","").strip()
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        if self._in_h1 and data.strip():
            self.h1.append(data.strip())

def url_for(path):
    rel = path.relative_to(ROOT).as_posix()
    if rel == "index.html":
        return BASE + "/"
    if rel.endswith("/index.html"):
        return BASE + "/" + rel[:-10]
    return None

def normalize_internal(href, source_url):
    if not href or href.startswith("#"):
        return None
    if href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
        return None
    if href.startswith("http://") or href.startswith("https://"):
        u = urlparse(href)
        if u.netloc != "ecoflot.pro":
            return None
        path = u.path or "/"
    elif href.startswith("/"):
        path = href.split("#",1)[0].split("?",1)[0]
    else:
        return None
    if not path.endswith("/") and "." not in Path(path).name:
        path += "/"
    return path

errors = []
warnings = []
pages = {}
titles = {}
descs = {}

for path in sorted(ROOT.rglob("index.html")):
    if ".github" in path.parts:
        continue
    p = PageParser()
    p.feed(path.read_text(encoding="utf-8"))
    url = url_for(path)
    pages[url] = (path,p)

    if not p.title:
        errors.append(f"{path}: missing <title>")
    elif len(p.title) < 20 or len(p.title) > 75:
        warnings.append(f"{path}: title length {len(p.title)}")
    if not p.desc:
        errors.append(f"{path}: missing meta description")
    elif len(p.desc) < 70 or len(p.desc) > 190:
        warnings.append(f"{path}: description length {len(p.desc)}")
    if not p.canonical:
        errors.append(f"{path}: missing canonical")
    elif p.canonical != url:
        errors.append(f"{path}: canonical mismatch: {p.canonical} != {url}")
    if len(p.h1) != 1:
        errors.append(f"{path}: expected exactly one H1, found {len(p.h1)}")

    if p.title:
        titles.setdefault(p.title, []).append(str(path.relative_to(ROOT)))
    if p.desc:
        descs.setdefault(p.desc, []).append(str(path.relative_to(ROOT)))

for title, items in titles.items():
    if len(items) > 1:
        errors.append("duplicate title: " + title + " -> " + ", ".join(items))
for desc, items in descs.items():
    if len(items) > 1:
        errors.append("duplicate description -> " + ", ".join(items))

existing_paths = {"/"}
for url in pages:
    path = urlparse(url).path
    existing_paths.add(path)

for url,(path,p) in pages.items():
    for href in p.links:
        internal = normalize_internal(href, url)
        if internal and internal not in existing_paths:
            if internal in ("/favicon.svg","/robots.txt","/sitemap.xml","/marketing.js","/analytics.js"):
                continue
            errors.append(f"{path}: broken internal link {href}")

sitemap = ROOT / "sitemap.xml"
if not sitemap.exists():
    errors.append("missing sitemap.xml")
else:
    try:
        root = ET.parse(sitemap).getroot()
        ns = {"s":"http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = {e.text.strip() for e in root.findall("s:url/s:loc",ns) if e.text}
        page_urls = set(pages.keys())
        missing = sorted(page_urls - urls)
        extra = sorted(urls - page_urls)
        for u in missing:
            errors.append("sitemap missing: " + u)
        for u in extra:
            warnings.append("sitemap extra: " + u)
    except Exception as e:
        errors.append("invalid sitemap.xml: " + str(e))

robots = ROOT / "robots.txt"
if not robots.exists():
    errors.append("missing robots.txt")
else:
    txt = robots.read_text(encoding="utf-8")
    if "Sitemap: https://ecoflot.pro/sitemap.xml" not in txt:
        errors.append("robots.txt missing sitemap reference")

print(f"Checked {len(pages)} HTML pages")
if warnings:
    print("\nWARNINGS")
    for w in warnings:
        print(" -", w)
if errors:
    print("\nERRORS")
    for e in errors:
        print(" -", e)
    sys.exit(1)

print("\nSEO audit passed")
