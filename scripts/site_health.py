#!/usr/bin/env python3
import sys, urllib.request, urllib.error, ssl
from xml.etree import ElementTree as ET

BASE="https://ecoflot.pro"
URLS=[
  BASE+"/",
  BASE+"/sitemap.xml",
  BASE+"/robots.txt",
  BASE+"/vyvoz-musora-odincovo/",
  BASE+"/vyvoz-stroitelnogo-musora/",
  BASE+"/kalkulyator/"
]

errors=[]
ctx=ssl.create_default_context()

def fetch(url):
    req=urllib.request.Request(url, headers={"User-Agent":"ECOFLOT-Uptime-Check/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            code=r.getcode()
            body=r.read()
            final=r.geturl()
            return code, body, final
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.geturl()
    except Exception as e:
        errors.append(f"{url}: {e}")
        return None,b"",url

for url in URLS:
    code,body,final=fetch(url)
    if code != 200:
        errors.append(f"{url}: HTTP {code}")
    if not final.startswith("https://"):
        errors.append(f"{url}: not HTTPS after redirects -> {final}")

code,body,final=fetch("http://ecoflot.pro/")
if code != 200:
    errors.append(f"http://ecoflot.pro/: HTTP {code}")
if not final.startswith("https://ecoflot.pro"):
    errors.append(f"HTTP does not redirect to HTTPS: {final}")

code,body,final=fetch(BASE+"/sitemap.xml")
if code==200:
    try:
        root=ET.fromstring(body)
        ns={"s":"http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs=[e.text.strip() for e in root.findall("s:url/s:loc",ns) if e.text]
        if len(locs) < 10:
            errors.append(f"sitemap suspiciously small: {len(locs)} URLs")
    except Exception as e:
        errors.append(f"invalid sitemap.xml: {e}")

code,body,final=fetch(BASE+"/robots.txt")
if code==200:
    txt=body.decode("utf-8","replace")
    if "Sitemap: https://ecoflot.pro/sitemap.xml" not in txt:
        errors.append("robots.txt missing sitemap reference")

code,body,final=fetch(BASE+"/")
if code==200:
    html=body.decode("utf-8","replace")
    for marker in ['id="leadform"','id="leadSubmitBtn"','ECOFLOT_SHEET_WEBHOOK']:
        if marker not in html:
            errors.append(f"homepage missing form marker: {marker}")

if errors:
    print("ECOFLOT uptime/content check FAILED")
    for e in errors:
        print(" -",e)
    sys.exit(1)

print("ECOFLOT uptime/content check PASSED")
