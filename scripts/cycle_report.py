#!/usr/bin/env python3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from internet_leads_monitor import WEBHOOK, send_notify_reliable

MSK = timezone(timedelta(hours=3))
MAX_AGE = timedelta(hours=2, minutes=15)

MONITORS = [
    ("♻️ Internet Leads", Path("internet_leads_state.json")),
    ("🔎 Tender Watch", Path("tender_state.json")),
    ("🏗 Object Leads", Path("object_leads_state.json")),
]

def read_last_run(path):
    try:
        data = json.loads(path.read_text("utf-8"))
        last = data.get("last_run") or {}
        if isinstance(last, str):
            return {"at": last}
        return last
    except Exception:
        return {}

def parse_at(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def monitor_line(label, path):
    last = read_last_run(path)
    dt = parse_at(last.get("at"))
    now = datetime.now(timezone.utc)
    if not dt or now - dt > MAX_AGE:
        return f"❌ {label}: нет свежего отчёта"

    sent = int(last.get("sent", 0) or 0)
    errors = int(last.get("errors", 0) or 0)
    candidates = int(last.get("candidates", 0) or 0)
    mark = "✅" if errors == 0 else "⚠️"
    t = dt.astimezone(MSK).strftime("%H:%M")
    return f"{mark} {label}: проверено {t}, новых отправлено {sent}, кандидатов {candidates}, ошибок {errors}"

def social_line():
    tg = read_last_run(Path("social_public_leads_state.json"))
    mx = read_last_run(Path("max_public_leads_state.json"))
    dt_tg = parse_at(tg.get("at"))
    dt_mx = parse_at(mx.get("at"))
    now = datetime.now(timezone.utc)
    if not dt_tg or not dt_mx or now - min(dt_tg, dt_mx) > MAX_AGE:
        return "❌ 🔷 Telegram/MAX: нет свежего отчёта"

    sent = int(tg.get("sent", 0) or 0) + int(mx.get("sent", 0) or 0)
    errors = int(tg.get("errors", 0) or 0) + int(mx.get("errors", 0) or 0)
    candidates = int(tg.get("candidates", 0) or 0) + int(mx.get("candidates", 0) or 0)
    mark = "✅" if errors == 0 else "⚠️"
    t = max(dt_tg, dt_mx).astimezone(MSK).strftime("%H:%M")
    return f"{mark} 🔷 Telegram/MAX: проверено {t}, новых отправлено {sent}, кандидатов {candidates}, ошибок {errors}"

def main():
    lines = ["📋 ECOFLOT. Контроль полного цикла"]
    lines.extend(monitor_line(label, path) for label, path in MONITORS)
    lines.append(social_line())
    lines.append("")
    lines.append("Если есть ❌ или ⚠️, это видно сразу: тихого пропуска отчёта больше быть не должно.")

    message = "\n".join(lines)
    send_notify_reliable(
        message,
        webhook=WEBHOOK,
        user_agent="ECOFLOT-Cycle-Control/1.0",
        source="Cycle Control",
    )
    print(message)

if __name__ == "__main__":
    main()
