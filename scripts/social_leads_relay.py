#!/usr/bin/env python3
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WEBHOOK = "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec"
QUEUE = Path("social_leads_queue.json")
STATE = Path("social_leads_state.json")

def load_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default

def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")

def message_for(item):
    if item.get("kind") == "notice":
        return str(item.get("message") or "Поиск Telegram/MAX проведён, новых заявок не обнаружено")
    return (
        "🔥 ECOFLOT Social Lead\n"
        f"Релевантность: {item.get('score', 0)}/100\n"
        f"{item.get('title','')}\n\n"
        f"Работа: {item.get('work','-')}\n"
        f"Техника: {item.get('equipment','-')}\n"
        f"Объём/плечо: {item.get('volume','-')}\n"
        f"Когда: {item.get('when','-')}\n"
        f"Адрес: {item.get('address','-')}\n"
        f"Телефон: {item.get('phone','-')}\n"
        f"Источник: {item.get('source','-')}\n"
        f"Описание: {item.get('description','-')}\n"
        f"Ссылка: {item.get('sourceUrl','-')}\n"
        f"CRM: https://ecoflot.pro/#crm/leads"
    )

def send_notify(message):
    payload = json.dumps(
        {"mode": "notify-only", "message": message},
        ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=payload,
        method="POST",
        headers={
            "User-Agent": "ECOFLOT-Social-Leads/1.1",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        if not (200 <= r.status < 300):
            raise RuntimeError(f"Webhook HTTP {r.status}: {body[:300]}")
        data = json.loads(body)
        if not data.get("ok"):
            raise RuntimeError(f"Webhook error: {body[:300]}")
        return body

def main():
    queue = load_json(QUEUE, {"items": []})
    state = load_json(STATE, {"sent": {}})
    sent = state.setdefault("sent", {})
    sent_now = 0

    for item in queue.get("items", []):
        rid = str(item.get("requestId", "")).strip()
        if not rid or rid in sent:
            continue
        send_notify(message_for(item))
        sent[rid] = datetime.now(timezone.utc).isoformat()
        sent_now += 1
        print("SENT:", rid, item.get("kind", "lead"), item.get("title", ""))

    save_state(state)
    print(f"Social queue: {len(queue.get('items', []))}, sent now: {sent_now}")

if __name__ == "__main__":
    main()
