#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
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

def post_message(message):
    webhook = read_webhook()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip() or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1"
    payload = {
        "mode": "notify-only",
        "message": message + f"\nПрогон: {run_id}.{attempt}",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ECOFLOT-Search-Completion/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
        if not (200 <= response.status < 300):
            raise RuntimeError(f"HTTP {response.status}: {body[:500]}")
        parsed = json.loads(body)
        if not parsed.get("ok"):
            raise RuntimeError(f"Webhook returned ok=false: {body[:500]}")
        if parsed.get("duplicate") is True:
            raise RuntimeError(f"Final Telegram report was deduplicated: {body[:500]}")
        sent = parsed.get("telegramSent")
        try:
            sent_count = int(sent)
        except Exception:
            sent_count = 0
        if sent_count < 1:
            raise RuntimeError(f"Final Telegram report was not confirmed as sent: {body[:500]}")
        print("SEARCH_COMPLETE_ACK:", body[:500])

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SEARCHES:
        raise SystemExit("usage: search_completion_report.py internet|social|tender|object")
    cfg = SEARCHES[sys.argv[1]]
    sent, duplicates, status, error_text, details = aggregate(cfg)
    status_label = "успешно" if status == "ok" else "ошибка"
    message = (
        f"✅ ECOFLOT {cfg['name']}: поиск завершён\n"
        f"Статус: {status_label}\n"
        f"Новых результатов: {sent}\n"
        f"Отсеяно / уже было: {duplicates}"
    )
    if error_text:
        message += f"\nОшибка: {error_text}"
    print("SEARCH_COMPLETE:", message.replace("\n", " | "), details)
    post_message(message)

if __name__ == "__main__":
    main()
