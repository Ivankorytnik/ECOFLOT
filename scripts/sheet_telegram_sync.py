#!/usr/bin/env python3
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
SHEET_ID = "1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws"
SHEET_NAME = "Заявки"
STATE_PATH = Path("sheet_telegram_sync_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "50"))
SYNC_MARKER = "SYNC"

COLS = [
    "created_at", "type", "name", "phone", "waste_type", "volume",
    "when", "address", "source", "status", "comment", "request_id", "telegram_route",
]

def fetch_sheet_rows():
    params = urllib.parse.urlencode({
        "sheet": SHEET_NAME,
        "headers": "1",
        "tqx": "out:json",
        "tq": "select A,B,C,D,E,F,G,H,I,J,K,L,M where L is not null",
    })
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ECOFLOT-Sheet-Telegram-Sync/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8", "replace")

    match = re.search(r"google\.visualization\.Query\.setResponse\((.*)\);?\s*$", raw, re.S)
    payload = json.loads(match.group(1) if match else raw)

    rows = []
    for source_row in payload.get("table", {}).get("rows", []):
        values = []
        for cell in (source_row.get("c") or []):
            if not cell:
                values.append("")
                continue
            value = cell.get("f")
            if value is None:
                value = cell.get("v")
            values.append("" if value is None else str(value).strip())
        while len(values) < len(COLS):
            values.append("")
        rows.append(dict(zip(COLS, values[:len(COLS)])))
    return rows

def load_state():
    if not STATE_PATH.exists():
        return {"sent": {}}
    try:
        data = json.loads(STATE_PATH.read_text("utf-8"))
        if not isinstance(data.get("sent"), dict):
            data["sent"] = {}
        return data
    except Exception:
        return {"sent": {}}

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        state["sent"] = dict(
            sorted(sent.items(), key=lambda item: item[1], reverse=True)[:5000]
        )
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )

def first_url(*parts):
    for part in parts:
        found = re.search(r"https?://[^\s<>]+", part or "")
        if found:
            return found.group(0).rstrip(").,;")
    return ""

def compact(text, limit):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"

def lead_action_lines(request_id):
    rid = urllib.parse.quote(request_id, safe="")
    base = "https://ecoflot.pro/?botAction="
    return [
        f"▶ В работу: {base}lead_work&rid={rid}",
        f"🧮 Расчёт / КП: {base}lead_quote&rid={rid}",
        f"🤝 Согласование: {base}lead_approval&rid={rid}",
        f"📅 Запланирована: {base}lead_scheduled&rid={rid}",
        f"🚛 Выполняется: {base}lead_executing&rid={rid}",
        f"✅ Выполнена: {base}lead_done&rid={rid}",
        f"✖ Отказ: {base}lead_lost&rid={rid}",
    ]

def build_message(row):
    request_type = (row["type"] or "").strip()
    is_tender = request_type.lower() == "тендер"
    is_object = request_type.lower() == "потенциальный объект"

    if is_tender:
        header = "📌 Новый тендер ECOFLOT"
        crm_url = "https://ecoflot.pro/#crm/tenders"
    elif is_object:
        header = "🏗 Потенциальный объект ECOFLOT"
        crm_url = "https://ecoflot.pro/#crm/leads"
    else:
        header = "🆕 Новая заявка ECOFLOT"
        crm_url = "https://ecoflot.pro/#crm/leads"

    lines = [
        header,
        "",
        row["name"] or request_type or "Новая запись",
    ]

    if row["address"]:
        lines.append("📍 " + row["address"])
    if row["waste_type"]:
        lines.append("🚛 " + row["waste_type"])
    if row["volume"] and row["volume"] != "-":
        lines.append("Объём: " + row["volume"])
    if row["when"]:
        lines.append("🕒 " + row["when"])
    if row["source"]:
        lines.append("Источник: " + row["source"])
    if row["status"]:
        lines.append("Статус: " + row["status"])

    source_url = first_url(row["comment"], row["source"])
    if source_url:
        lines.append("🔗 " + source_url)

    comment = compact(row["comment"], 1200)
    if comment:
        lines.extend(["", comment])

    lines.extend(["", "📂 CRM: " + crm_url])

    if not is_tender:
        lines.extend([""] + lead_action_lines(row["request_id"]))

    lines.extend(["", "ID: " + row["request_id"]])
    return "\n".join(lines)

def send_notify(message):
    payload = json.dumps(
        {"mode": "notify-only", "message": message},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=payload,
        method="POST",
        headers={
            "User-Agent": "ECOFLOT-Sheet-Telegram-Sync/1.0",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
        if not (200 <= response.status < 300):
            raise RuntimeError(f"Webhook HTTP {response.status}: {body[:300]}")
    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError("Webhook error: " + body[:300])
    recipients = int(result.get("sent") or 0)
    if recipients < 1:
        raise RuntimeError("Telegram delivery returned sent=0")
    return recipients

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    rows = fetch_sheet_rows()

    candidates = [
        row for row in rows
        if row["request_id"]
        and row["telegram_route"].upper() == SYNC_MARKER
        and row["request_id"] not in sent
        and not row["type"].upper().startswith("CRM_ACTION")
        and row["type"].upper() not in {"ТЕСТ", "ТЕСТ ЦЕПОЧКИ", "TENDER_REMINDER"}
    ]

    delivered = 0
    errors = []

    for row in candidates[:MAX_SEND]:
        try:
            recipients = send_notify(build_message(row))
            sent[row["request_id"]] = datetime.now(timezone.utc).isoformat()
            delivered += 1
            print(f"SENT_SYNC {row['request_id']} recipients={recipients}")
        except Exception as exc:
            errors.append(f"{row['request_id']}: {exc}")
            print("ERROR " + errors[-1], file=sys.stderr)

    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "marked_rows": sum(
            1 for row in rows
            if row["request_id"] and row["telegram_route"].upper() == SYNC_MARKER
        ),
        "pending_before_run": len(candidates),
        "delivered": delivered,
        "errors": len(errors),
    }
    save_state(state)

    print(
        f"Sheet Telegram sync: marked={state['last_run']['marked_rows']}, "
        f"pending={len(candidates)}, delivered={delivered}, errors={len(errors)}"
    )

    if errors:
        sys.exit(1)

if __name__ == "__main__":
    main()
