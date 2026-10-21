"""Canonical identities from explicitly observed individual order URLs.

No fuzzy title matching, phone merging, HTTP requests, or URL construction
from generic listing IDs. Used in both Internet and Telegram contours.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlsplit

SAMOSVAL_PATH = "/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php"
PROFI_PATH = "/backoffice/n.php"
URLS = re.compile(r"https?://[^\s<>\"'\[\]\(\)]+", re.I)


def order_key_from_url(value):
    """Only two verified per-order link structures have stable shared IDs."""
    try:
        raw = html.unescape(str(value or "")).strip().rstrip(".,;:!?")
        p = urlsplit(raw)
        host = (p.hostname or "").lower().removeprefix("www.")
        if p.scheme not in ("http", "https") or p.username or p.password:
            return ""
        if p.port not in (None, 80, 443):
            return ""
        query = parse_qs(p.query)
        if host == "profi.ru" and p.path == PROFI_PATH:
            ids = query.get("o", [])
            if len(ids) == 1 and re.fullmatch(r"[1-9]\d{5,11}", ids[0]):
                return "profi:" + ids[0]
        if host == "samosval.info" and p.path == SAMOSVAL_PATH:
            ids = query.get("ID", []) or query.get("id", [])
            if len(ids) == 1 and re.fullmatch(r"[1-9]\d{4,9}", ids[0]):
                return "samosval:" + ids[0]
    except (TypeError, ValueError):
        pass
    return ""


def order_urls_in_text(text):
    return [raw.rstrip(".,;:!?") for raw in URLS.findall(html.unescape(str(text or "")))
            if order_key_from_url(raw.rstrip(".,;:!?"))]


def item_order_key(item):
    """Ambiguous posts with several different orders never get merged."""
    urls = [item.get("url", ""), item.get("contact_url", "")]
    urls.extend(item.get("card_links") or [])
    if str(item.get("source", "")).startswith("Telegram / "):
        urls.extend(order_urls_in_text(item.get("description", "")))
    keys = {key for url in urls if (key := order_key_from_url(url))}
    return next(iter(keys)) if len(keys) == 1 else ""


def known_order_keys(links, request_ids=()):
    keys = {key for url in links if (key := order_key_from_url(url))}
    for rid in request_ids:
        match = re.fullmatch(r"WEB-SAMOSVALIN-([1-9]\d{4,9})", str(rid))
        if match:
            keys.add("samosval:" + match.group(1))
    return keys


def primary_order_link(item):
    """A Telegram repost can use the observed primary order URL for server dedupe.

    Keep the Telegram post as the provenance in the comment; do not infer
    a URL from a title, a category page or an unverified numeric reference.
    """
    if not str(item.get("url") or "").startswith("https://t.me/"):
        return ""
    key = item_order_key(item)
    if not key:
        return ""
    evidence = list(item.get("card_links") or [])
    evidence.extend(order_urls_in_text(item.get("description", "")))
    if not any(order_key_from_url(link) == key for link in evidence):
        return ""
    source, ident = key.split(":", 1)
    if source == "profi":
        return "https://profi.ru/backoffice/n.php?o=" + ident
    if source == "samosval":
        return "https://samosval.info" + SAMOSVAL_PATH + "?ID=" + ident
    return ""
