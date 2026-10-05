#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
QUEUE_DIR = Path("automation_queue")

def load_items(path):
    data = json.loads(path.read_text("utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, dict):
        return [data]
    raise ValueError("Unsupported queue format")

def normalize(item):
    out = {
        "type": str(item.get("type") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "phone": str(item.get("phone") or "-").strip(),
        "wasteType": str(item.get("wasteType") or item.get("waste_type") or "").strip(),
        "volume": str(item.get("volume") or "-").strip(),
        "when": str(item.get("when") or "").strip(),
        "address": str(item.get("address") or "").strip(),
        "source": str(item.get("source") or "ECOFLOT automation").strip(),
        "status": str(item.get("status") or "Новая").strip(),
        "comment": str(item.get("comment") or "").strip(),
        "requestId": str(item.get("requestId") or item.get("request_id") or "").strip(),
    }
    for key in ("type","name","status","requestId"):
        if not out[key]:
            raise ValueError("Missing required field: " + key)

    # Hard QA gate: technical placeholders must never become CRM/Telegram leads.
    bad_names = {"без названия", "заявка", "лид", "lead", "test", "тест"}
    if out["name"].strip().lower() in bad_names:
        raise ValueError("Invalid lead name: " + out["name"])

    if out["source"].strip().lower() in {"ecoflot automation", "automation", "unknown", "-"}:
        raise ValueError("Invalid lead source: " + out["source"])

    # Real Internet/Social/Object leads require traceable source and contact path.
    # Tender cards are allowed without phone, but still require direct source link
    # to be carried in comment/link by the producing contour.
    hay = " ".join([out["comment"], out["source"], out["name"], out["address"], out["when"]])
    has_url = "http://" in hay or "https://" in hay
    has_phone = bool(__import__("re").search(r"(?<!\d)(?:\+?7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)", hay))
    kind = out["type"].lower()
    is_tender = "тендер" in kind
    if not is_tender and not (has_phone or has_url):
        raise ValueError("Lead has no public phone or direct contact/source URL")

    # Freshness/traceability: no blank date for ordinary leads.
    if not is_tender and not out["when"]:
        raise ValueError("Lead has no publication/need date")

    return out

def send(item):
    payload = normalize(item)
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=data,
        method="POST",
        headers={"User-Agent":"ECOFLOT-Automation-Queue/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8","replace")
        if not (200 <= r.status < 300):
            raise RuntimeError("Webhook HTTP %s: %s" % (r.status, body[:300]))
    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError("Webhook error: " + body[:300])
    if result.get("duplicate"):
        print("DUPLICATE", payload["requestId"])
        return
    sent = int(result.get("telegramSent") or 0)
    if sent < 1:
        raise RuntimeError("telegramSent=0 for " + payload["requestId"])
    print("SENT", payload["requestId"], "telegramSent=" + str(sent))

def main():
    QUEUE_DIR.mkdir(exist_ok=True)
    files = sorted(QUEUE_DIR.glob("*.json"))
    if not files:
        print("QUEUE_EMPTY")
        return
    errors = []
    for path in files:
        try:
            for item in load_items(path):
                send(item)
            path.unlink()
            print("PROCESSED_FILE", str(path))
        except Exception as exc:
            errors.append("%s: %s" % (path, exc))
            print("ERROR", errors[-1], file=sys.stderr)
    if errors:
        sys.exit(1)

if __name__ == "__main__":
    main()
