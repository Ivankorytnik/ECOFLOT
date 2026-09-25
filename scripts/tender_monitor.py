#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
STATE_PATH = Path("tender_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "100"))

SOURCES = [
    ("Московская область", "https://gentender.ru/tenders/utilizaciya-othodov/moskovskaya-oblast"),
    ("Москва", "https://gentender.ru/tenders/utilizaciya-othodov/moskva"),
]

POSITIVE = (
    "вывоз", "транспортирован", "транспортировк", "сбор отход",
    "тко", "кгм", "мусор", "свалк", "навал", "шлам", "фильтрат",
    "отходов производства и потребления",
)

EXCLUDE = (
    "медицинск", "класса «б»", "класса "б"", "списанного имущества",
    "оргтехник", "технических средств", "медицинского оборудования",
    "огнетушител", "ртуть", "ламп", "аккумулятор", "шин",
)

KNOWN_ALREADY_SENT = {
    "0848300049026000814",
    "0348500002526000035",
    "0348500002526000036",
    "0348500002526000038",
}

def fetch(url: str, timeout=30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ECOFLOT-Tender-Monitor/2.0)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def extract_cards(page: str, source_region: str):
    out = []
    for m in re.finditer(r'<li class="t-card">(.*?)</li>', page, re.I | re.S):
        block = m.group(1)
        q = re.search(r'<a class="t-title" href="/search\?q=([^"]+)">(.*?)</a>', block, re.I | re.S)
        if not q:
            continue
        tender_id = clean(q.group(1))
        title = clean(q.group(2))
        law = clean((re.search(r'<span class="t-law[^"]*">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        region = clean((re.search(r'<span class="t-region">(.*?)</span>', block, re.I | re.S) or [None, source_region])[1])
        customer = clean((re.search(r'<span class="t-cust">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        price = clean((re.search(r'<span class="t-price">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        deadline = clean((re.search(r'<span class="t-dl[^"]*">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        out.append({
            "id": tender_id,
            "title": title,
            "law": law,
            "region": region or source_region,
            "customer": customer,
            "price": price,
            "deadline": deadline,
            "link": "https://gentender.ru/search?q=" + urllib.parse.quote(tender_id),
        })
    return out

def relevant(entry):
    hay = entry["title"].lower()
    if any(x in hay for x in EXCLUDE):
        return False
    return any(x in hay for x in POSITIVE)

def load_state():
    if not STATE_PATH.exists():
        return {"sent": {}}
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"sent": {}}

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 3000:
        recent = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:3000]
        state["sent"] = dict(recent)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")

def send_webhook(entry):
    comment = (
        f"Заказчик: {entry['customer'] or 'не указан'}\n"
        f"Цена: {entry['price'] or 'не указана'}\n"
        f"Закон/тип: {entry['law'] or 'не указан'}\n"
        f"Регион: {entry['region']}\n"
        f"Срок: {entry['deadline'] or 'не указан'}\n"
        f"Ссылка: {entry['link']}"
    )
    payload = {
        "type": "Тендер",
        "name": entry["title"][:250],
        "phone": "-",
        "wasteType": "Вывоз / транспортирование отходов",
        "volume": "-",
        "when": entry["deadline"] or "Активная закупка",
        "address": entry["region"],
        "source": "GenTender / данные ЕИС",
        "status": "Новый тендер",
        "comment": comment[:1800],
        "requestId": "TENDER-" + re.sub(r"[^A-Za-z0-9_-]", "", entry["id"])[:80],
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK, data=data, method="POST",
        headers={"User-Agent": "ECOFLOT-Tender-Monitor/2.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        if not (200 <= r.status < 300):
            raise RuntimeError(f"Webhook HTTP {r.status}: {body[:300]}")
        try:
            resp = json.loads(body)
            if not resp.get("ok"):
                raise RuntimeError(f"Webhook error: {body[:300]}")
        except json.JSONDecodeError:
            pass

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    candidates = []
    seen = set()
    errors = []

    for source_region, url in SOURCES:
        try:
            page = fetch(url)
            cards = extract_cards(page, source_region)
            print(f"SOURCE {source_region}: {len(cards)} active cards")
            for entry in cards:
                if not relevant(entry):
                    continue
                key = hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()
                if entry["id"] in KNOWN_ALREADY_SENT or key in sent or key in seen:
                    continue
                seen.add(key)
                candidates.append((entry, key))
        except Exception as exc:
            errors.append(f"{source_region}: {exc}")

    sent_count = 0
    for entry, key in candidates[:MAX_SEND]:
        try:
            send_webhook(entry)
            sent[key] = datetime.now(timezone.utc).isoformat()
            sent_count += 1
            print("SENT:", entry["id"], entry["title"][:140], entry["price"], entry["deadline"])
        except Exception as exc:
            errors.append(f"send {entry['id']}: {exc}")

    save_state(state)
    print(f"Found new active relevant: {len(candidates)}, sent: {sent_count}, errors: {len(errors)}")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)

    if errors and len(errors) >= len(SOURCES) and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
