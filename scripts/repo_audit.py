#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXT = {".html", ".js", ".py", ".yml", ".yaml", ".json", ".md", ".txt", ".webmanifest"}
IGNORE_INTERNAL = {"404.html", "yandex_64ad02abcd9d31bd.html"}

errors: list[str] = []
warnings: list[str] = []

class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.scripts = []
        self._in_script = False
        self._script_type = ""
        self._script_buf = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.append(("href", attrs["href"]))
        if tag == "link" and attrs.get("href"):
            self.links.append(("href", attrs["href"]))
        if tag == "script":
            if attrs.get("src"):
                self.links.append(("src", attrs["src"]))
            else:
                self._in_script = True
                self._script_type = attrs.get("type", "")
                self._script_buf = []
        if tag in ("img", "source") and attrs.get("src"):
            self.links.append(("src", attrs["src"]))

    def handle_data(self, data):
        if self._in_script:
            self._script_buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_script:
            code = "".join(self._script_buf).strip()
            if code:
                self.scripts.append((self._script_type, code))
            self._in_script = False
            self._script_type = ""
            self._script_buf = []

def local_target(src: Path, value: str) -> Path | None:
    value = (value or "").strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    p = urlparse(value)
    if p.scheme in ("http", "https") or p.netloc:
        return None
    raw = p.path
    if not raw:
        return None
    if raw.startswith("/"):
        target = ROOT / raw.lstrip("/")
    else:
        target = src.parent / raw
    if raw.endswith("/"):
        target = target / "index.html"
    elif target.is_dir():
        target = target / "index.html"
    return target.resolve()

def check_python():
    for p in sorted((ROOT / "scripts").glob("*.py")):
        try:
            ast.parse(p.read_text("utf-8"), filename=str(p))
        except Exception as exc:
            errors.append(f"Python syntax: {p.relative_to(ROOT)}: {exc}")

def node_check(code: str, label: str):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(code)
        name = f.name
    try:
        cp = subprocess.run(["node", "--check", name], capture_output=True, text=True)
        if cp.returncode:
            errors.append(f"JavaScript syntax: {label}: {(cp.stderr or cp.stdout).strip()[:800]}")
    finally:
        try: os.unlink(name)
        except OSError: pass

def check_js_files():
    for p in sorted(ROOT.glob("*.js")):
        node_check(p.read_text("utf-8"), str(p.relative_to(ROOT)))

def check_html():
    all_html = sorted(ROOT.rglob("*.html"))
    for p in all_html:
        if ".git" in p.parts:
            continue
        rel = p.relative_to(ROOT)
        parser = Parser()
        try:
            parser.feed(p.read_text("utf-8"))
        except Exception as exc:
            errors.append(f"HTML parse: {rel}: {exc}")
            continue

        dup = [k for k,v in Counter(parser.ids).items() if v > 1]
        if dup:
            errors.append(f"Duplicate HTML id: {rel}: {', '.join(dup[:20])}")

        for attr, value in parser.links:
            target = local_target(p, value)
            if target is not None and not target.exists():
                errors.append(f"Broken local {attr}: {rel}: {value}")

        for idx, (stype, code) in enumerate(parser.scripts, 1):
            if stype in ("application/ld+json", "application/json"):
                try:
                    json.loads(code)
                except Exception as exc:
                    errors.append(f"JSON-LD syntax: {rel} script#{idx}: {exc}")
            elif stype in ("", "text/javascript", "application/javascript"):
                node_check(code, f"{rel} inline-script#{idx}")

def check_orphans():
    texts = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or p.suffix.lower() not in TEXT_EXT:
            continue
        try:
            texts.append((p, p.read_text("utf-8", errors="ignore")))
        except Exception:
            pass

    candidates = [
        ROOT / "site-ui.js",
        ROOT / "shared-seo.js",
        ROOT / "notify_webhook_response.txt",
    ]
    for p in candidates:
        if not p.exists():
            continue
        needle = p.name
        refs = []
        for other, txt in texts:
            if other.resolve() == p.resolve():
                continue
            if needle in txt:
                refs.append(str(other.relative_to(ROOT)))
        if not refs:
            warnings.append(f"Unreferenced file: {p.relative_to(ROOT)}")

    for p in sorted((ROOT / "assets" / "fleet").glob("*.jpg")):
        needle = p.name
        refs = [str(other.relative_to(ROOT)) for other,txt in texts if other.resolve()!=p.resolve() and needle in txt]
        if not refs:
            warnings.append(f"Unreferenced image: {p.relative_to(ROOT)}")

def check_public_secrets():
    index = ROOT / "index.html"
    if index.exists():
        text = index.read_text("utf-8", errors="ignore")
        if re.search(r"\bCRM_PASSWORD\s*=\s*['\"][^'\"]+['\"]", text):
            warnings.append("Security: CRM_PASSWORD is embedded in public index.html; client-side password is not real access control.")

def main():
    check_python()
    check_js_files()
    check_html()
    check_orphans()
    check_public_secrets()

    print(f"AUDIT errors={len(errors)} warnings={len(warnings)}")
    if errors:
        print("\nERRORS")
        for x in errors:
            print(" -", x)
    if warnings:
        print("\nWARNINGS")
        for x in warnings:
            print(" -", x)
    if errors:
        sys.exit(1)

if __name__ == "__main__":
    main()
