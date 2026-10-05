#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"sent": {}}

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        state["sent"] = dict(sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:5000])
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")

def demand_ok(text):
    low = (text or "").lower().replace("ё", "е")
    if any(x in low for x in EXCLUDE):
        return False
    if not any(x in low for x in DEMAND_MARKERS):
        return False
    return relevant((text or "")[:250], text or "")

def search_bing(query):
    # Multi-engine discovery is implemented in internet_leads_monitor.
    return [u for u in discovery_result_urls(query) if "max.ru/" in u.lower()]

def fetch_max_page(url):
    page = fetch(url, timeout=20)
    text = clean(page)
    return page, text

def extract_confirmed_date(page, text):
    patterns = [
        r'(?i)(?:datePublished|article:published_time)[^>]{0,120}(20\d{2}-\d{2}-\d{2})',
        r'(?<!\d)(\d{1,2}\.\d{1,2}\.20\d{2})(?!\d)',
        r'(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)',
    ]
    for pattern in patterns:
        m = re.search(pattern, page + " " + text)
        if not m:
            continue
        raw = m.group(1)
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - dt <= timedelta(days=RECENT_DAYS):
                    return dt
                return None
            except ValueError:
                pass
    return None


def extract_candidates(url):
    page, text = fetch_max_page(url)
    if not text or not demand_ok(text):
        return []
    geo = matched_geo(text)
    if not geo:
        return []
    dt = extract_confirmed_date(page, text)
    if not dt:
        return []
    title = next((x.strip() for x in text.splitlines() if x.strip()), "MAX-заявка")[:220]
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    item = {
        "request_id": "SOCIAL-MAX-" + key,
        "title": title,
        "description": text[:1800],
        "price": "договорная",
        "date": dt.strftime("%Y-%m-%d"),
        "location": geo,
        "volume": extract_volume(text) or "-",
        "url": url,
        "source": "MAX / публичная страница",
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

    new_items = []
    for item in candidates:
        sig = signature(item["title"], item["location"], item["description"])
        if item["request_id"] in sent or item["request_id"] in sheet_ids:
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
            print("SENT:", item["score"], item["request_id"], item["title"][:120])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")

    if sent_count == 0 and not SUPPRESS_NO_RESULTS:
        try:
            send_no_results()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"no-results: {exc}")

    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cycleKey": os.environ.get("ECOFLOT_CYCLE_KEY", "").strip(),
        "sent": sent_count,
        "candidates": len(candidates),
        "errors": len(errors),
    }
    save_state(state)

    print(f"MAX candidates: {len(candidates)}, new: {len(new_items)}, sent: {sent_count}, errors: {len(errors)}")
    for err in errors:
        print("ERROR:", err, file=sys.stderr)

if __name__ == "__main__":
    main()
