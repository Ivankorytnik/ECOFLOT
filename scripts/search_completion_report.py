#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from pathlib import Path

SEARCHES = {
    "internet": {
        "name": "Internet Leads",
        "states": ["internet_leads_state.json"],
        "outcomes": ["SCAN_OUTCOME"],
    },
    "social": {
        "name": "Telegram/MAX",
        "states": ["social_public_leads_state.json", "max_public_leads_state.json"],
        "outcomes": ["TELEGRAM_OUTCOME", "MAX_OUTCOME"],
    },
    "tender": {
        "name": "Tender Watch",
        "states": ["tender_state.json"],
        "outcomes": ["SCAN_OUTCOME"],
    },
    "object": {
        "name": "Object Leads",
        "states": ["object_leads_state.json"],
        "outcomes": ["SCAN_OUTCOME"],
    },
}

def load_state(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return {}

def read_webhook():
    value = os.environ.get("ECOFLOT_WEBHOOK", "").strip()
    if value:
        return value
    text = Path("scripts/internet_leads_monitor.py").read_text("utf-8")
    marker = "https://script.google.com/macros/s/"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError("ECOFLOT webhook not found")
    end = text.find('"', start)
    if end < 0:
        end = text.find("'", start)
    if end < 0:
        raise RuntimeError("ECOFLOT webhook end not found")
    return text[start:end]

def aggregate(cfg):
    sent = 0
    candidates = 0
    errors = 0
    found_state = False
    details = []
    for path in cfg["states"]:
        state = load_state(path)
        last = state.get("last_run") or {}
        if last:
            found_state = True
        sent += int(last.get("sent", 0) or 0)
        candidates += int(last.get("candidates", 0) or 0)
        errors += int(last.get("errors", 0) or 0)
        details.append(f"{path}: sent={int(last.get('sent', 0) or 0)}, candidates={int(last.get('candidates', 0) or 0)}, errors={int(last.get('errors', 0) or 0)}")
    outcomes = [os.environ.get(key, "").strip().lower() for key in cfg["outcomes"]]
    failed = any(x and x not in ("success", "skipped") for x in outcomes)
    status = "error" if failed or not found_state else "ok"
    error_text = ""
    if status == "error":
        error_text = "Техническая ошибка выполнения поиска"
        if outcomes:
            error_text += ": " + ", ".join(x or "unknown" for x in outcomes)
    duplicates = max(candidates - sent, 0)
    return sent, duplicates, status, error_text, "; ".join(details)

def post(payload):
    webhook = read_webhook()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ECOFLOT-Search-Completion/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
        if not (200 <= response.status < 300):
            raise RuntimeError(f"HTTP {response.status}: {body[:500]}")
        parsed = json.loads(body)
        if not parsed.get("ok"):
            raise RuntimeError(f"Webhook returned ok=false: {body[:500]}")
        print("SEARCH_COMPLETE_ACK:", body[:500])

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SEARCHES:
        raise SystemExit("usage: search_completion_report.py internet|social|tender|object")
    cfg = SEARCHES[sys.argv[1]]
    sent, duplicates, status, error_text, details = aggregate(cfg)
    payload = {
        "event": "search_complete",
        "searchName": cfg["name"],
        "status": status,
        "newCount": sent,
        "duplicates": duplicates,
        "error": error_text,
    }
    print("SEARCH_COMPLETE:", json.dumps(payload, ensure_ascii=False), details)
    post(payload)

if __name__ == "__main__":
    main()
