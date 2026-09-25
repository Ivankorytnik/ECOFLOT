#!/usr/bin/env python3
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
STATE_PATH = Path("tender_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "8"))

SEARCHES = [
    "вывоз мусора Одинцово",
    "вывоз отходов Одинцово",
    "отходы не относящиеся к ТКО Одинцово",
    "ликвидация свалок Одинцово",
    "строительный мусор Одинцово",
    "крупногабаритный мусор Одинцово",
    "контейнер мусор Одинцово",
    "вывоз мусора Московская область",
    "вывоз отходов Московская область",
    "транспортирование отходов Московская область",
    "сбор транспортирование отходов Московская область",
    "отходы IV V класса Московская область",
    "ликвидация свалок Московская область",
    "несанкционированные навалы мусора Московская область",
    "контейнерные площадки вывоз отходов Московская область",
    "строительный мусор Московская область",
    "вывоз мусора Москва",
    "вывоз отходов Москва",
    "строительный мусор Москва",
]

SERVICE_WORDS = (
    "вывоз мусор", "вывоз отход", "транспортирован", "сбор отход",
    "утилизац", "обезврежив", "ликвидац", "свалк", "навал",
    "строительн", "крупногабарит", "кгм", "контейнер",
    "отход", "мусор",
)

def rss_url(query: str) -> str:
    params = {
        "searchString": query,
        "morphology": "on",
        "pageNumber": "1",
        "sortDirection": "false",
        "recordsPerPage": "_50",
        "showLotsInfoHidden": "false",
        "sortBy": "UPDATE_DATE",
        "fz44": "on",
        "fz223": "on",
        "af": "on",
        "currencyIdGeneral": "-1",
    }
    return "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html?" + urllib.parse.urlencode(params)

def fetch(url: str, timeout=30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ECOFLOT-Tender-Monitor/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def text_of(el, names):
    for child in list(el):
        tag = child.tag.split("}")[-1].lower()
        if tag in names:
            if tag == "link" and child.attrib.get("href"):
                return child.attrib.get("href", "").strip()
            return "".join(child.itertext()).strip()
    return ""

def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    return re.sub(r"\s+", " ", s).strip()

def parse_feed(data: bytes):
    root = ET.fromstring(data)
    entries = []
    for el in root.iter():
        local = el.tag.split("}")[-1].lower()
        if local not in ("item", "entry"):
            continue
        title = strip_html(text_of(el, {"title"}))
        desc = strip_html(text_of(el, {"description", "summary", "content"}))
        link = text_of(el, {"link"})
        guid = text_of(el, {"guid", "id"}) or link or title
        date = text_of(el, {"pubdate", "published", "updated"})
        entries.append({"id": guid, "title": title, "description": desc, "link": link, "date": date})
    return entries

def relevant(entry):
    hay = (entry["title"] + " " + entry["description"]).lower()
    # География уже задается поисковым запросом. Не требуем ее повторения
    # в заголовке/описании RSS, иначе ЕИС отсекает подходящие закупки.
    return any(w in hay for w in SERVICE_WORDS)

def load_state():
    if not STATE_PATH.exists():
        return {"sent": {}}
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"sent": {}}

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 1000:
        recent = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:1000]
        state["sent"] = dict(recent)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")

def send_webhook(entry, query):
    comment_parts = []
    if entry["description"]:
        comment_parts.append(entry["description"][:1000])
    if entry["link"]:
        comment_parts.append(entry["link"])
    payload = {
        "type": "Тендер",
        "name": entry["title"][:250] or "Новая закупка",
        "phone": "-",
        "wasteType": "Госзакупка / тендер",
        "volume": "-",
        "when": entry["date"] or "Новая публикация",
        "address": query,
        "source": "ЕИС zakupki.gov.ru",
        "status": "Тендер",
        "comment": "\n".join(comment_parts)[:1800],
        "requestId": "TENDER-" + hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()[:16],
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data=data, method="POST", headers={"User-Agent": "ECOFLOT-Tender-Monitor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        if r.status < 200 or r.status >= 300:
            raise RuntimeError(f"Webhook HTTP {r.status}: {body[:300]}")
        try:
            response = json.loads(body)
            if not response.get("ok"):
                raise RuntimeError(f"Webhook error: {body[:300]}")
        except json.JSONDecodeError:
            pass

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    candidates = []
    seen_this_run = set()
    errors = []

    for query in SEARCHES:
        try:
            for entry in parse_feed(fetch(rss_url(query))):
                if not entry["id"] or not relevant(entry):
                    continue
                key = hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()
                if key in sent or key in seen_this_run:
                    continue
                seen_this_run.add(key)
                candidates.append((entry, query, key))
        except Exception as exc:
            errors.append(f"{query}: {exc}")

    sent_count = 0
    for entry, query, key in candidates[:MAX_SEND]:
        try:
            send_webhook(entry, query)
            sent[key] = datetime.now(timezone.utc).isoformat()
            sent_count += 1
            print("SENT:", entry["title"][:120], entry["link"])
        except Exception as exc:
            errors.append(f"send {entry['title'][:80]}: {exc}")

    save_state(state)
    print(f"Found new: {len(candidates)}, sent: {sent_count}, errors: {len(errors)}")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)

    # Fail only if every search failed and nothing was sent.
    if errors and len(errors) >= len(SEARCHES) and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
