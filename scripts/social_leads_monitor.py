#!/usr/bin/env python3
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from internet_leads_monitor import (
    WEBHOOK,
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
    send_notify_reliable,
    ensure_public_contact,
    contact_dedupe_keys,
)

STATE_PATH = Path("social_public_leads_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "50"))
SUPPRESS_NO_RESULTS = os.environ.get("SUPPRESS_NO_RESULTS", "0") == "1"

CHANNELS = [
    ("Всем Подряд", "vsem_podryad"),
    ("Работа для самосвалов", "samosvalam_rabota"),
    ("Горячие заказы МСК МО", "Goryachie_Zakazy"),
    ("Спецтехника аренда Москва и МО", "spetctechnika_arenda_uslugi"),
    ("Аренда спецтехники Заявки", "spectehnikfree"),
    ("Аренда Спецтехники Москва МО", "spetstekhnika_arenda"),
]

DEMAND_MARKERS = (
    "нужен", "нужна", "нужно", "нужны", "требуется", "требуются",
    "ищем", "заказ", "работа для", "самосвалам", "в работу",
    "необходим", "вывоз грунта", "вывоз мусора",
)

EXCLUDE = (
    "продам", "продается", "продажа", "лизинг", "вакансия менеджер",
    "пропуск в москву", "оформим пропуск", "реклама",
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

def message_text(block):
    m = re.search(r'(?is)<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block)
    if not m:
        return ""
    raw = re.sub(r"(?i)<br\s*/?>", "\n", m.group(1))
    return clean(raw)

def demand_ok(text):
    low = text.lower().replace("ё", "е")
    if any(x in low for x in EXCLUDE):
        return False
    if not any(x in low for x in DEMAND_MARKERS):
        return False
    return relevant(text[:250], text)

def parse_channel(label, channel):
    page = fetch(f"https://t.me/s/{channel}", timeout=20)

    # Telegram periodically changes attributes around public post wrappers.
    # Support both data-post and message-date href forms instead of assuming one layout.
    markers = []
    for m in re.finditer(r'data-post=["\']([^"\']+)/(\d+)["\']', page, re.I):
        markers.append((m.start(), m.group(1), m.group(2)))
    if not markers:
        for m in re.finditer(
            r'href=["\']https://t\.me/([^/"\']+)/(\d+)["\'][^>]*class=["\'][^"\']*tgme_widget_message_date',
            page, re.I
        ):
            markers.append((m.start(), m.group(1), m.group(2)))
    if not markers:
        for m in re.finditer(r'href=["\']https://t\.me/([^/"\']+)/(\d+)["\']', page, re.I):
            markers.append((m.start(), m.group(1), m.group(2)))

    # Preserve order, de-duplicate repeated links within the same message wrapper.
    seen_marker = set()
    marks = []
    for pos, post_channel, post_id in sorted(markers):
        key = (post_channel.lower(), post_id)
        if key in seen_marker:
            continue
        seen_marker.add(key)
        marks.append((pos, post_channel, post_id))

    print(f"TELEGRAM_HTML {label}: bytes={len(page)} post_markers={len(marks)}")
    out = []
    for i, (start, post_channel, post_id) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else min(len(page), start + 18000)
        block = page[start:end]

        text = message_text(block)
        if not text:
            # Fallback for minor Telegram class changes.
            tm = re.search(
                r'(?is)<div[^>]+class=["\'][^"\']*tgme_widget_message_text[^"\']*["\'][^>]*>(.*?)</div>',
                block,
            )
            if tm:
                raw = re.sub(r"(?i)<br\s*/?>", "\n", tm.group(1))
                text = clean(raw)
        if not text or not demand_ok(text):
            continue

        location = matched_geo(text)
        if not location:
            continue

        time_m = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', block, re.I)
        dt = None
        if time_m:
            try:
                dt = datetime.fromisoformat(time_m.group(1).replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                dt = None
        if not dt:
            print("EXCLUDED_FRESHNESS: no-confirmed-date", label, post_id)
            continue
        if datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
            continue

        url = f"https://t.me/{post_channel}/{post_id}"
        rid = "SOCIAL-TG-" + re.sub(r"[^A-Za-z0-9_-]+", "", post_channel)[:40] + "-" + post_id
        title = next((x.strip() for x in text.splitlines() if x.strip()), "Telegram-заявка")[:220]

        item = {
            "request_id": rid,
            "title": title,
            "description": text[:1800],
            "price": "договорная",
            "date": dt.strftime("%Y-%m-%d"),
            "location": location,
            "volume": extract_volume(text) or "-",
            "url": url,
            "source": "Telegram / " + label,
            "priority": "Высокий" if lead_class(title, text) == "HOT" else "Средний",
        }
        score, work, equipment = relevance_score(item)
        item["score"] = score
        item["work"] = work
        item["equipment"] = equipment
        item["lead_class"] = lead_class(title, text)
        if score >= MIN_RELEVANCE_SCORE:
            out.append(item)
    return out, len(marks)

def send_no_results():
    return send_notify_reliable(
        "Поиск Telegram-заявок проведён, новых заявок не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-Social-Monitor/3.0",
        source="Social Leads Telegram",
    )

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    sheet_ids, sheet_links, sheet_sigs, _ = load_sheet_index()
    candidates = []
    errors = []
    unverified_sources = []

    for label, channel in CHANNELS:
        try:
            found, marker_count = parse_channel(label, channel)
            print(f"TELEGRAM_SOURCE {label}: {len(found)} candidates")
            if marker_count == 0:
                unverified_sources.append(f"Telegram/{label}: публичные посты недоступны")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            unverified_sources.append(f"Telegram/{label}: ошибка доступа")

    unique = {x["request_id"]: x for x in candidates}
    candidates = sorted(unique.values(), key=lambda x: (-x["score"], x["source"], x["title"]))

    contact_ready = []
    for item in candidates:
        ok, reason = ensure_public_contact(item)
        if ok:
            contact_ready.append(item)
        else:
            print("EXCLUDED_CONTACT:", reason, item.get("source"), item.get("request_id"), item.get("url"))
    candidates = contact_ready

    new_items = []
    for item in candidates:
        sig = signature(item["title"], item["location"], item["description"])
        if item["request_id"] in sent or item["request_id"] in sheet_ids:
            continue
        if item["url"] in sheet_links or sig in sheet_sigs:
            continue
        if any(key in sheet_links for key in contact_dedupe_keys(item)):
            continue
        new_items.append(item)

    sent_count = 0
    for item in new_items[:MAX_SEND]:
        try:
            send_webhook(item)
            sent[item["request_id"]] = datetime.now(timezone.utc).isoformat()
            sent_count += 1
            print("SENT:", item["source"], item["score"], item["request_id"], item["title"][:120])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")

    if sent_count == 0 and len(errors) < len(CHANNELS) and not SUPPRESS_NO_RESULTS:
        try:
            send_no_results()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"no-results: {exc}")

    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cycleKey": os.environ.get("ECOFLOT_CYCLE_KEY", "").strip(),
        "sent": sent_count,
        "candidates": len(candidates),
        "errors": len(errors),
        "unverified_sources": sorted(set(unverified_sources)),
    }
    save_state(state)
    print(f"Social candidates: {len(candidates)}, new: {len(new_items)}, sent: {sent_count}, errors: {len(errors)}")
    for err in errors:
        print("ERROR:", err, file=sys.stderr)

    if errors and len(errors) >= len(CHANNELS) and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
