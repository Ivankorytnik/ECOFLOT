#!/usr/bin/env python3
import html
import json
import os
import re
import sys
import time
from social_depth import read_history, scoped_contacts
from source_markup import absolute_link
from card_acquisition import Acquisition, known_card
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from search_reliability import (load_json as reliable_load, atomic_json, finish_metrics,
    record_lead_result, delivery_confirmed, run_id, parse_deadline, tender_service_demand, MSK)

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

SOURCE_COVERAGE = {}
SOCIAL_DEADLINE = None
CHANNELS = [
    ("Всем Подряд", "vsem_podryad"),
    ("Работа для самосвалов", "samosvalam_rabota"),
    ("Горячие заказы МСК МО", "Goryachie_Zakazy"),
    ("Спецтехника аренда Москва и МО", "spetctechnika_arenda_uslugi"),
    ("Аренда спецтехники Заявки", "spectehnikfree"),
    ("Аренда Спецтехники Москва МО", "spetstekhnika_arenda"),
    ("PROMS / dump-truck orders", "rabota_dlya_samosvalov_promsru"),
    ("Samosval.Info", "samosvalinfo"),
    ("Dump-trucks work", "dumptrucks_work"),
    ("Equipment work", "spezteh"),
    ("Quarry truck orders", "tonary_karery"),
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
    return reliable_load(STATE_PATH, {"sent": {}})

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        state["sent"] = dict(sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:5000])
    atomic_json(STATE_PATH, state)

def message_text(block):
    m = re.search(r'(?is)<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block)
    if not m:
        return ""
    raw = re.sub(r"(?i)<br\s*/?>", "\n", m.group(1))
    return clean(raw)

def social_title(text):
    parts = [x.strip(" -—–•\t") for x in re.split(r"[\r\n]+|(?<=[.!?])\s+", text or "") if x.strip()]
    for line in parts:
        low = line.lower().replace("ё","е")
        if any(x in low for x in DEMAND_MARKERS) and len(line) >= 12:
            return line[:220]
    for line in parts:
        if len(line) >= 12:
            return line[:220]
    return "Заявка на спецтехнику / перевозку"


def social_quality_ready(item):
    title = clean(item.get("title") or "")
    url = str(item.get("url") or "").strip()
    date_text = clean(item.get("date") or "")
    if len(title) < 12 or title.lower().startswith(("telegram", "канал")):
        return False, "unclear-title"
    if not url.startswith("https://t.me/"):
        return False, "no-direct-post-link"
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date_text):
        return False, "no-confirmed-date"
    ok, reason = ensure_public_contact(item)
    if not ok:
        return False, reason
    return True, ""


def demand_ok(text):
    low = text.lower().replace("ё", "е")
    if any(x in low for x in EXCLUDE):
        return False
    if not any(x in low for x in DEMAND_MARKERS):
        return False
    return relevant(text[:250], text)

def parse_channel(label, channel):
    report = {}
    budget = min(70, max(0, SOCIAL_DEADLINE-time.monotonic())) if SOCIAL_DEADLINE else 70
    posts = read_history(channel, fetch, days=RECENT_DAYS,
                         max_pages=max(1,min(50,int(os.environ.get('ECOFLOT_TG_MAX_PAGES','30')))),
                         max_seconds=budget, report=report)
    SOURCE_COVERAGE[channel] = report
    out = []
    for post in posts:
        text = post['text']
        if not text or not demand_ok(text):
            continue
        location = matched_geo(text)
        if not location:
            continue
        title = social_title(text)
        item = {
            'request_id':'SOCIAL-TG-'+channel+'-'+post['id'],
            'title':title,'description':text[:1800], 'price':'',
            'date':post['published'].strftime('%Y-%m-%d'),
            'location':location,'volume':extract_volume(text) or '-',
            'url':post['url'],'source':'Telegram / '+label,
            'priority':'\u0412\u044b\u0441\u043e\u043a\u0438\u0439' if lead_class(title,text)=='HOT' else '\u0421\u0440\u0435\u0434\u043d\u0438\u0439',
        }
        item.update(scoped_contacts(post['body'],channel))
        item['card_links'] = [a.attrs['href'] for a in post['body'].find_all('a',attr='href')
                              if known_card(a.attrs['href'])] if post['body'] else []
        score,work,equipment = relevance_score(item)
        item.update(score=score,work=work,equipment=equipment,lead_class=lead_class(title,text))
        if score >= MIN_RELEVANCE_SCORE:
            out.append(item)
    report['eligible_before_contact'] = len(out)
    print('TELEGRAM_DEPTH', json.dumps(report,ensure_ascii=False), flush=True)
    return out, report['posts']

def send_no_results():
    return send_notify_reliable(
        "Поиск Telegram-заявок проведён, новых заявок не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-Social-Monitor/3.0",
        source="Social Leads Telegram",
    )

def main():
    global SOCIAL_DEADLINE
    SOURCE_COVERAGE.clear()
    SOCIAL_DEADLINE = time.monotonic()+240
    acquisition = Acquisition(fetch, limit=24, budget=45)
    state = load_state()
    sent = state.setdefault("sent", {})
    legacy_local = state.get("last_run", {}).get("metrics_version") != 2
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
            coverage = SOURCE_COVERAGE.get(channel,{})
            if not coverage.get('complete'):
                unverified_sources.append('Telegram/'+label+': '+str(coverage.get('stop_reason','unknown')))
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            unverified_sources.append(f"Telegram/{label}: ошибка доступа")

    unique = {x["request_id"]: x for x in candidates}
    candidates = sorted(unique.values(), key=lambda x: (-x["score"], x["source"], x["title"]))

    contact_ready = []
    for item in candidates:
        acquisition.enrich(item)
        ok, reason = ensure_public_contact(item)
        if ok:
            contact_ready.append(item)
        else:
            print("EXCLUDED_CONTACT:", reason, item.get("source"), item.get("request_id"), item.get("url"))
    candidates = contact_ready

    quality_ready = []
    for item in candidates:
        ok, reason = social_quality_ready(item)
        if ok:
            quality_ready.append(item)
        else:
            print("EXCLUDED_SOCIAL_QUALITY:", reason, item.get("source"), item.get("request_id"), item.get("url"))
    candidates = quality_ready

    new_items = []
    for item in candidates:
        sig = signature(item["title"], item["location"], item["description"])
        if (not legacy_local and item["request_id"] in sent) or item["request_id"] in sheet_ids:
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
            save_state(state)
            print("ACCEPTED:", item["source"], item["score"], item["request_id"], item["title"][:120])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")

    if sent_count == 0 and len(errors) < len(CHANNELS) and not SUPPRESS_NO_RESULTS:
        try:
            send_no_results()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"no-results: {exc}")

    unverified_sources.extend(sorted(acquisition.unchecked))
    state["last_run"] = {
        "source_coverage": SOURCE_COVERAGE,
        "contact_acquisition": acquisition.report,
        "at": datetime.now(timezone.utc).isoformat(),
        "cycleKey": os.environ.get("ECOFLOT_CYCLE_KEY", "").strip(),
        "run_id": run_id(),
        "error_details": errors,
        "sent": sent_count,
        "candidates": len(candidates),
        "duplicates_local": len(candidates) - len(new_items),
        "deferred": max(0, len(new_items) - MAX_SEND),
        "errors": len(errors),
        "unverified_sources": sorted(set(unverified_sources)),
    }
    finish_metrics(state)
    save_state(state)
    print(f"Social candidates: {len(candidates)}, new: {len(new_items)}, sent: {sent_count}, errors: {len(errors)}")
    for err in errors:
        print("ERROR:", err, file=sys.stderr)

    if errors and len(errors) >= len(CHANNELS) and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
