#!/usr/bin/env python3
from pathlib import Path
from datetime import date
import re

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://ecoflot.pro"

exclude = {
    "404.html",
    "yandex_64ad02abcd9d31bd.html",
}
urls = []

for p in ROOT.rglob("index.html"):
    rel = p.relative_to(ROOT).as_posix()
    if rel == "index.html":
        url = BASE + "/"
        priority = "1.0"
    else:
        if rel.startswith(".github/"):
            continue
        slug = rel[:-10]
        url = BASE + "/" + slug
        priority = "0.8"
        if slug in ("vyvoz-musora-odincovo/","vyvoz-musora-moskva/","vyvoz-stroitelnogo-musora/","arenda-konteynera/"):
            priority = "0.9"
        elif slug in ("faq/","karta-saita/","kak-vybrat-konteyner/","chto-mozhno-vyvozit/"):
            priority = "0.7"
    urls.append((url, priority))

urls = sorted(set(urls), key=lambda x: (x[0] != BASE + "/", x[0]))
today = date.today().isoformat()
body = ['<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for url, priority in urls:
    freq = "weekly" if float(priority) >= 0.8 else "monthly"
    body.append(f'  <url><loc>{url}</loc><lastmod>{today}</lastmod><changefreq>{freq}</changefreq><priority>{priority}</priority></url>')
body.append('</urlset>')
(ROOT / "sitemap.xml").write_text("\n".join(body) + "\n", encoding="utf-8")
print(f"Generated sitemap.xml with {len(urls)} URLs")
