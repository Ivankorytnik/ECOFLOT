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
    send_notify_only,
)

STATE_PATH = Path("max_public_leads_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "50"))
SUPPRESS_NO_RESULTS = os.environ.get("SUPPRESS_NO_RESULTS", "0") == "1"

SEARCH_QUERIES = [
    "site:max.ru самосвал Москва",
    "site:max.ru самосвал Одинцово",
    "site:max.ru вывоз грунта Московская область",
    "site:max.ru вывоз мусора Одинцово",
    "site:max.ru демонтаж Московская область",
    "site:max.ru требуется экскаватор Москва",
    "site:max.ru контейнер мусор Московская область",
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
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    page = fetch(url, timeout=20)
    out = []
    for m in re.finditer(r'https://max\.ru/[^"&<> ]+', page, re.I):
        u = html.unescape(m.group(0))
        u = u.split("&",1)[0].rstrip(").,;")
        out.append(u)
    return list(dict.fromkeys(out))

def fetch_max_page(url):
    page = fetch(url, timeout=20)
    text = clean(page)
    return page, text

def extract_candidates(url):
    page, text = fetch_max_page(url)
    if not text or not demand_ok(text):
        return []
    geo = matched_geo(text)
    if not geo:
        return []
    title = next((x.strip() for x in text.splitlines() if x.strip()), "MAX-заявка")[:220]
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    item = {
        "request_id": "SOCIAL-MAX-" + key,
        "title": title,
        "description": text[:1800],
        "price": "договорная",
        "date": "актуальная публикация",
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
    return send_notify_only(
        "Поиск MAX-заявок проведён, новых заявок не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-MAX-Monitor/2.0",
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

    new_items = []
    for item in candidates:
        sig = signature(item["title"], item["location"], item["description"])
        if item["request_id"] in sent or item["request_id"] in sheet_ids:
            continue
        if item["url"] in sheet_links or sig in sheet_sigs:
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
