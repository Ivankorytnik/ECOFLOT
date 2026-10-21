#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from source_markup import DOM
from datetime import datetime, timezone, timedelta
from pathlib import Path
from search_reliability import (load_json as reliable_load, atomic_json, finish_metrics,
    record_lead_result, delivery_confirmed, run_id, parse_deadline, tender_service_demand, MSK)

from internet_leads_monitor import (
    WEBHOOK,
    SHEET_ID,
    SHEET_NAME,
    RECENT_DAYS,
    MIN_RELEVANCE_SCORE,
    fetch,
    clean,
    relevant,
    matched_geo,
    relevance_score,
    lead_class,
    infer_work_equipment,
    extract_volume,
    load_sheet_index,
    signature,
    send_webhook,
    send_notify_reliable,
    ensure_public_contact,
    contact_dedupe_keys,
    discovery_result_urls,
    extract_public_contact,
    is_public_contact_url,
)

STATE_PATH = Path("max_public_leads_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "50"))
SUPPRESS_NO_RESULTS = os.environ.get("SUPPRESS_NO_RESULTS", "0") == "1"

SEARCH_QUERIES = [
    "site:max.ru нужен самосвал Москва",
    "site:max.ru требуется самосвал Московская область",
    "site:max.ru нужен самосвал Калужская область",
    "site:max.ru вывоз грунта Москва",
    "site:max.ru вывоз грунта Московская область",
    "site:max.ru вывоз грунта Калужская область",
    "site:max.ru вывоз мусора Москва",
    "site:max.ru вывоз мусора Московская область",
    "site:max.ru вывоз мусора Калужская область",
    "site:max.ru нужен контейнер мусор Москва",
    "site:max.ru нужен контейнер мусор Московская область",
    "site:max.ru нужен контейнер мусор Калужская область",
    "site:max.ru требуется экскаватор Москва",
    "site:max.ru требуется экскаватор Московская область",
    "site:max.ru требуется экскаватор Калужская область",
    "site:max.ru требуется спецтехника Москва",
    "site:max.ru требуется спецтехника Московская область",
    "site:max.ru требуется спецтехника Калужская область",
    "site:max.ru демонтаж Москва",
    "site:max.ru демонтаж Московская область",
    "site:max.ru демонтаж Калужская область",
    "site:max.ru работа для самосвалов Москва",
    "site:max.ru работа для самосвалов Московская область",
    "site:max.ru работа для самосвалов Калужская область",
    "site:max.ru нужен тонар Москва",
    "site:max.ru нужен тонар Московская область",
    "site:max.ru нужен тонар Калужская область",
    "site:max.ru погрузка грунта Москва",
    "site:max.ru погрузка грунта Московская область",
    "site:max.ru перевозка ПГС Московская область",
    "site:max.ru перевозка щебня Московская область",
]

DEMAND_MARKERS = (
    "нужен", "нужна", "нужно", "нужны", "требуется", "требуются",
    "ищем", "заказ", "работа для", "необходим", "вывоз грунта", "вывоз мусора",
)

EXCLUDE = (
    "продам", "продается", "продажа", "лизинг", "вакансия менеджер",
    "реклама", "куплю самосвал", "купить самосвал",
)

def load_state():
    return reliable_load(STATE_PATH, {"sent": {}})

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        state["sent"] = dict(sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:5000])
    atomic_json(STATE_PATH, state)

def max_title(text):
    parts = [x.strip(" -—–•\t") for x in re.split(r"[\r\n]+|(?<=[.!?])\s+", text or "") if x.strip()]
    for line in parts:
        low = line.lower().replace("ё","е")
        if any(x in low for x in DEMAND_MARKERS) and len(line) >= 12:
            return line[:220]
    for line in parts:
        if len(line) >= 12:
            return line[:220]
    return "Заявка MAX на спецтехнику / перевозку"


def demand_ok(text):
    low = (text or "").lower().replace("ё", "е")
    if any(x in low for x in EXCLUDE):
        return False
    if not any(x in low for x in DEMAND_MARKERS):
        return False
    return relevant((text or "")[:250], text or "")

def individual_max_post_url(url):
    """Return only a concrete public post, never a channel/profile or foreign host."""
    try:
        parsed = urllib.parse.urlsplit(str(url or "").strip())
        if (parsed.scheme != "https" or parsed.hostname != "max.ru"
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return ""
        parts = parsed.path.strip("/").split("/")
        if (len(parts) != 2
                or not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", parts[0])
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,90}", parts[1])):
            return ""
        return "https://max.ru/" + "/".join(parts)
    except (TypeError, ValueError):
        return ""


def search_bing(query):
    # Enforce the exact public host and an individual post path. Substrings
    # like example.com/max.ru/ and channel profile pages are not MAX orders.
    return [post for url in discovery_result_urls(query)
            if (post := individual_max_post_url(url))]


def fetch_max_page(url):
    return fetch(url, timeout=10, attempts=1)


def max_post_metadata(page, url):
    """Only verified post-specific metadata or a single article is demand text.

    Page-wide nav/footer text and the channel's own @handle are never contacts.
    """
    root = DOM(page).root
    meta = {}
    for node in root.find_all("meta"):
        key = (node.attrs.get("property") or node.attrs.get("name") or "").lower()
        if key and node.attrs.get("content"):
            meta.setdefault(key, node.attrs["content"])
    canonical = individual_max_post_url(url)
    if not canonical:
        return "", []
    # A redirect to the channel/profile must not be mistaken for the post.
    page_url = meta.get("og:url", "")
    if page_url and individual_max_post_url(page_url) != canonical:
        return "", []
    articles = list(root.find_all("article"))
    content = html.unescape(meta.get("og:description")
                            or meta.get("twitter:description") or "").strip()
    if not content and len(articles) == 1:
        content = articles[0].clean()
    if not content:
        return "", []
    dates = [meta.get(k, "") for k in
             ("article:published_time", "datepublished", "publication_date",
              "article:published", "date")]
    if len(articles) == 1:
        dates.extend(n.attrs.get("datetime", "")
                     for n in articles[0].find_all("time", attr="datetime"))
    # Some public MAX post pages embed schema.org datePublished as JSON-LD.
    for node in root.find_all("script"):
        if node.attrs.get("type", "").lower() != "application/ld+json":
            continue
        raw = "".join(ch for ch in node.children if isinstance(ch, str))
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw, re.I)
        if match:
            dates.append(match.group(1))
    return clean(content), dates


def extract_confirmed_date(page, text=""):
    """Only publication metadata can establish freshness, not job deadlines."""
    candidates = text if isinstance(text, (tuple, list)) else []
    for value in candidates:
        raw = str(value or "").strip()
        if not raw:
            continue
        try:
            if re.fullmatch(r"\d{1,2}\.\d{1,2}\.20\d{2}", raw):
                dt = datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
        except ValueError:
            continue
        age = datetime.now(timezone.utc) - dt
        if timedelta(0) <= age <= timedelta(days=RECENT_DAYS):
            return dt
    return None


def explicit_max_contact(text, post_url):
    """Require customer contact explicitly published in the post body."""
    phone, _ = extract_public_contact(text)
    url = ""
    for match in re.finditer(r"https?://[^\s<>\"']+", text or "", re.I):
        value = match.group(0).rstrip(".,;:!?)]}")
        if not is_public_contact_url(value):
            continue
        target = urllib.parse.urlsplit(value)
        host = (target.hostname or "").lower()
        if host == "max.ru":
            # A self-link or a linked channel post is not the buyer's address.
            if (individual_max_post_url(value)
                    or value.split("?", 1)[0] == post_url):
                continue
            # Profile links count only when explicitly labelled as a contact.
            preceding = (text or "")[max(0, match.start()-55):match.start()].lower()
            if not re.search(r"контакт|связ|пишит|заказчик|обращай", preceding):
                continue
        url = value
        break
    if not url:
        email = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                          text or "", re.I)
        if email:
            url = "mailto:" + email.group(0)
    # Do not turn MAX's own @channel_name into a fictitious Telegram contact.
    return phone, url


def extract_candidates(url):
    url = individual_max_post_url(url)
    if not url:
        return []
    page = fetch_max_page(url)
    text, dates = max_post_metadata(page, url)
    if not text:
        return []
    if not demand_ok(text):
        return []
    geo = matched_geo(text)
    if not geo:
        return []
    dt = extract_confirmed_date(page, dates)
    if not dt:
        return []
    title = max_title(text)
    phone, contact_url = explicit_max_contact(text, url)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    item = {
        "request_id": "SOCIAL-MAX-" + key,
        "title": title,
        "description": text[:1800],
        "contact_text": "",
        "contact_evidence_required": True,
        "phone": phone,
        "contact_url": contact_url,
        "price": "договорная",
        "date": dt.strftime("%Y-%m-%d"),
        "location": geo,
        "volume": extract_volume(text) or "-",
        "url": url,
        "source": "MAX / конкретная публичная публикация",
        "priority": "Высокий" if lead_class(title, text) == "HOT" else "Средний",
    }
    score, work, equipment = relevance_score(item)
    item["score"] = score
    item["work"] = work
    item["equipment"] = equipment
    item["lead_class"] = lead_class(title, text)
    return [item] if score >= MIN_RELEVANCE_SCORE else []

def send_no_results():
    return send_notify_reliable(
        "Поиск MAX-заявок проведён, новых заявок не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-MAX-Monitor/2.0",
        source="Social Leads MAX",
    )

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    legacy_local = state.get("last_run", {}).get("metrics_version") != 2
    sheet_ids, sheet_links, sheet_sigs, _ = load_sheet_index()
    urls = []
    errors = []

    for query in SEARCH_QUERIES:
        try:
            found = search_bing(query)
            print(f"MAX_QUERY {query}: {len(found)} urls")
            urls.extend(found)
        except Exception as exc:
            errors.append(f"{query}: {exc}")

    urls = list(dict.fromkeys(urls))[:120]
    candidates = []
    for url in urls:
        try:
            candidates.extend(extract_candidates(url))
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    unique = {x["request_id"]: x for x in candidates}
    candidates = sorted(unique.values(), key=lambda x: (-x["score"], x["title"]))

    contact_ready = []
    for item in candidates:
        ok, reason = ensure_public_contact(item)
        if ok:
            contact_ready.append(item)
        else:
            print("EXCLUDED_CONTACT:", reason, item.get("source"), item.get("request_id"), item.get("url"))
    candidates = contact_ready

    quality_ready = []
    for item in candidates:
        title = clean(item.get("title") or "")
        url = str(item.get("url") or "").strip()
        date_text = clean(item.get("date") or "")
        ok = len(title) >= 12 and url.startswith("http") and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date_text)
        if ok:
            quality_ready.append(item)
        else:
            print("EXCLUDED_MAX_QUALITY:", item.get("request_id"), url)
    candidates = quality_ready

    new_items = []
    for item in candidates:
        sig = signature(item["title"], item["location"], item["description"])
        if (not legacy_local and item["request_id"] in sent) or item["request_id"] in sheet_ids:
            continue
        if item["url"] in sheet_links or sig in sheet_sigs:
            continue
        if any(key in sheet_links for key in contact_dedupe_keys(item)):
            continue
        new_items.append(item)

    sent_count = 0
    for item in new_items[:MAX_SEND]:
        try:
            send_webhook(item)
            sent[item["request_id"]] = datetime.now(timezone.utc).isoformat()
            sent_count += 1
            save_state(state)
            print("ACCEPTED:", item["score"], item["request_id"], item["title"][:120])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")

    if sent_count == 0 and not SUPPRESS_NO_RESULTS:
        try:
            send_no_results()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"no-results: {exc}")

    unverified_sources = []
    if urls and not candidates:
        unverified_sources.append("MAX: найдены публичные URL, но свежая дата публикации <=7 дней не подтверждена")
    if not urls:
        unverified_sources.append("MAX: публичная поисковая выдача не дала проверяемых страниц")

    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cycleKey": os.environ.get("ECOFLOT_CYCLE_KEY", "").strip(),
        "run_id": run_id(),
        "error_details": errors,
        "sent": sent_count,
        "candidates": len(candidates),
        "duplicates_local": len(candidates) - len(new_items),
        "deferred": max(0, len(new_items) - MAX_SEND),
        "errors": len(errors),
        "unverified_sources": unverified_sources,
    }
    finish_metrics(state)
    save_state(state)

    print(f"MAX candidates: {len(candidates)}, new: {len(new_items)}, sent: {sent_count}, errors: {len(errors)}")
    for err in errors:
        print("ERROR:", err, file=sys.stderr)

if __name__ == "__main__":
    main()
