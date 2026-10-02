#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from internet_leads_monitor import (
    TELEGRAM_RETRY_QUEUE_PATH,
    WEBHOOK,
    send_notify_only,
)

MAX_ATTEMPTS = 12

def load_queue():
    if not TELEGRAM_RETRY_QUEUE_PATH.exists():
        return {"items": []}
    try:
        return json.loads(TELEGRAM_RETRY_QUEUE_PATH.read_text("utf-8"))
    except Exception:
        return {"items": []}

def save_queue(data):
    TELEGRAM_RETRY_QUEUE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )

def main():
    data = load_queue()
    items = data.get("items") or []
    if not items:
        print("TELEGRAM_RETRY_QUEUE_EMPTY")
        return

    remaining = []
    delivered = 0
    failed = 0

    for item in items:
        attempts = int(item.get("attempts", 0))

        # This dispatcher is text-only. Real lead/tender cards must be resent
        # through the card route that rebuilds inline status buttons.
        if item.get("request_id"):
            item["last_error"] = "card retry blocked: use webhook card route"
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            remaining.append(item)
            failed += 1
            print(
                "TELEGRAM_RETRY_CARD_BLOCKED:",
                item.get("source"),
                item.get("key"),
                file=sys.stderr,
            )
            continue

        if attempts >= MAX_ATTEMPTS:
            failed += 1
            item["last_error"] = "max attempts reached"
            remaining.append(item)
            continue

        try:
            send_notify_only(
                item.get("message", ""),
                webhook=WEBHOOK,
                user_agent="ECOFLOT-Telegram-Retry/1.0",
                attempts=3,
            )
            delivered += 1
            print("TELEGRAM_RETRY_DELIVERED:", item.get("source"), item.get("key"))
        except Exception as exc:
            item["attempts"] = attempts + 1
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            item["last_error"] = str(exc)[:500]
            remaining.append(item)
            failed += 1
            print("TELEGRAM_RETRY_FAILED:", item.get("source"), item.get("key"), exc, file=sys.stderr)

    data["items"] = remaining
    data["last_dispatch"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "delivered": delivered,
        "remaining": len(remaining),
        "failed": failed,
    }
    save_queue(data)
    print(f"Retry dispatch delivered={delivered}, remaining={len(remaining)}, failed={failed}")

if __name__ == "__main__":
    main()
