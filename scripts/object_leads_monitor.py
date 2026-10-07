#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from search_reliability import (load_json as reliable_load, atomic_json, finish_metrics,
    record_lead_result, delivery_confirmed, run_id, parse_deadline, tender_service_demand, MSK)

from internet_leads_monitor import (
    parse_webhook_response,
    telegram_delivery_confirmed,
    send_notify_reliable,
    ensure_public_contact,
    load_sheet_index,
)

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
STATE_PATH = Path("object_leads_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "20"))
RECENT_DAYS = int(os.environ.get("RECENT_DAYS", "5"))
MIN_SCORE = int(os.environ.get("MIN_SCORE", "70"))

GEOS = {
    "Москва": (
        "москва", "мск", "новая москва", "троицк", "щербинка", "московский",
        "коммунарка", "внуково", "кокошкино", "первомайское", "сосенское",
        "десеновское", "филимонковское",
    ),
    "Московская область": (
        "московская область", "подмосковье", "балашиха", "подольск", "химки",
        "мытищи", "люберцы", "королев", "королёв", "красногорск", "одинцово",
        "домодедово", "щелково", "щёлково", "серпухов", "коломна", "раменское",
        "электросталь", "реутов", "долгопрудный", "пушкино", "жуковский",
        "ногинск", "воскресенск", "лобня", "клин", "дмитров", "дубна",
        "чехов", "наро-фоминск", "егорьевск", "ступино", "павловский посад",
        "орехово-зуево", "сергиев посад", "истра", "звенигород", "апрелевка",
        "котельники", "видное", "нахабино", "кубинка", "голицыно", "барвиха",
        "жуковка", "руза", "можайск", "волоколамск", "солнечногорск",
    ),
    "Калужская область": (
        "калужская область", "калуга", "обнинск", "балабаново", "боровск",
        "малоярославец", "белоусово", "ермолино", "жуков", "кременки",
        "таруса", "кондрово", "медынь", "юхнов", "мосальск", "мещовск",
        "сухиничи", "козельск", "сосенский", "людиново", "киров",
        "спас-деменск", "жиздра",
    ),
}
SIGNALS = {
    "Строительство": (
        "началось строительство", "строительство объекта", "строительство жк",
        "строительство склада", "строительство комплекса", "стройплощадк",
        "генподрядчик", "подготовка площадки",
    ),
    "Демонтаж": (
        "демонтаж", "снос здания", "снос объекта", "разбор здания",
        "ликвидация объекта",
    ),
    "Земляные работы": (
        "земляные работы", "котлован", "разработка грунта", "выемка грунта",
        "вертикальная планировка",
    ),
    "Благоустройство": (
        "благоустройство", "реконструкция территории", "реконструкция парка",
        "обустройство территории", "капитальный ремонт территории",
    ),
    "Дороги": (
        "ремонт дороги", "реконструкция дороги", "строительство дороги",
        "дорожные работы",
    ),
}

EXCLUDE = (
    "продажа квартир", "купить квартиру", "ипотека", "ваканс",
    "выставка", "форум", "конференц", "прогноз", "обзор рынка",
    "завершили ремонт", "работы завершены", "благоустройство завершено",
    "строительство завершено", "объект введен", "объект введён",
    "санкт-петербург", "петербург", "ленинградская область",
)

def fetch(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ECOFLOT-Object-Leads/1.0)",
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def norm(s):
    return clean(s).lower().replace("ё", "е")

def detect_geo(text):
    hay = norm(text)
    for label, terms in GEOS.items():
        if any(norm(t) in hay for t in terms):
            return label
    return ""

def detect_signal(text):
    hay = norm(text)
    best = ""
    best_hits = 0
    for label, terms in SIGNALS.items():
        hits = sum(1 for t in terms if norm(t) in hay)
        if hits > best_hits:
            best, best_hits = label, hits
    return best if best_hits else ""

def score_item(title, desc, geo, signal, published):
    hay = norm(title + " " + desc)
    if any(x in hay for x in EXCLUDE):
        return 0
    score = 45
    if geo:
        score += 15
    if signal:
        score += 15
    if any(x in hay for x in ("началось", "приступили", "стартовал", "выбран подрядчик", "генподрядчик")):
        score += 8
    if any(x in hay for x in ("демонтаж", "котлован", "земляные работы", "снос")):
        score += 8
    if geo == "Одинцово":
        score += 5
    if published:
        age = datetime.now(timezone.utc) - published
        if age <= timedelta(days=1):
            score += 7
        elif age <= timedelta(days=3):
            score += 4
    return min(score, 100)

def google_news_url(query):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=ru&gl=RU&ceid=RU:ru"

def queries():
    out = []
    signal_words = [
        '"строительство" OR "стройплощадка" OR "генподрядчик"',
        '"демонтаж" OR "снос" OR "разбор здания"',
        '"земляные работы" OR "котлован" OR "разработка грунта"',
        '"благоустройство" OR "реконструкция территории"',
        '"логистический комплекс" OR "складской комплекс" OR "индустриальный парк"',
        '"строительство дороги" OR "реконструкция дороги" OR "дорожные работы"',
    ]
    for geo in GEOS:
        for s in signal_words:
            out.append((geo, f'"{geo}" {s}'))
    return out

def parse_feed(xml_text, query_geo):
    out = []
    root = ET.fromstring(xml_text)
    for item in root.findall(".//item"):
        title = clean(item.findtext("title") or "")
        link = clean(item.findtext("link") or "")
        desc = clean(item.findtext("description") or "")
        pub_raw = clean(item.findtext("pubDate") or "")
        published = None
        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                published = published.astimezone(timezone.utc)
            except Exception:
                published = None
        if published and datetime.now(timezone.utc) - published > timedelta(days=RECENT_DAYS):
            continue
        text = title + " " + desc
        geo = detect_geo(text)
        if not geo:
            continue
        signal = detect_signal(text)
        score = score_item(title, desc, geo, signal, published)
        if score < MIN_SCORE or not signal:
            continue
        rid = "OBJECT-" + hashlib.sha1((title + "|" + link).encode("utf-8")).hexdigest()[:20]
        out.append({
            "request_id": rid,
            "title": title,
            "description": desc,
            "url": link,
            "location": geo,
            "signal": signal,
            "score": score,
            "date": published.strftime("%Y-%m-%d") if published else "свежая публикация",
        })
    return out

def load_state():
    return reliable_load(STATE_PATH, {"sent": {}})

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        state["sent"] = dict(sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:5000])
    atomic_json(STATE_PATH, state)

def send(item):
    suggested = {
        "Строительство": "Контейнеры, вывоз грунта, самосвалы, экскаватор-погрузчик",
        "Демонтаж": "Демонтаж, погрузка, контейнеры, самосвалы",
        "Земляные работы": "Экскаватор-погрузчик, самосвалы, вывоз грунта",
        "Благоустройство": "Погрузка, вывоз грунта/отходов, расчистка",
        "Дороги": "Самосвалы, вывоз грунта, погрузка",
    }.get(item["signal"], "Техника ECOFLOT")
    rid = urllib.parse.quote(item["request_id"])
    comment = (
        f"Сигнал объекта: {item['signal']}\n"
        f"Релевантность: {item['score']}\n"
        f"Что предложить: {suggested}\n"
        f"Источник: {item['url']}\n"
        f"Описание: {item['description'][:1200]}\n"
        f"🆕 Новая: https://ecoflot.pro/?botAction=lead_new&rid={rid}\n"
        f"▶ В работе: https://ecoflot.pro/?botAction=lead_work&rid={rid}\n"
        f"🧮 Расчёт / КП: https://ecoflot.pro/?botAction=lead_quote&rid={rid}\n"
        f"🤝 Согласование: https://ecoflot.pro/?botAction=lead_approval&rid={rid}\n"
        f"📅 Запланирована: https://ecoflot.pro/?botAction=lead_scheduled&rid={rid}\n"
        f"🚛 Выполняется: https://ecoflot.pro/?botAction=lead_executing&rid={rid}\n"
        f"✅ Выполнена: https://ecoflot.pro/?botAction=lead_done&rid={rid}\n"
        f"✖ Отказ: https://ecoflot.pro/?botAction=lead_lost&rid={rid}\n"
        f"📂 Открыть CRM: https://ecoflot.pro/#crm/leads"
    )
    payload = {
        "type": "Потенциальный объект",
        "name": item["title"][:250],
        "phone": "-",
        "wasteType": suggested,
        "volume": "-",
        "when": item["date"],
        "address": item["location"],
        "source": "ECOFLOT Object Leads | " + item["url"],
        "link": item["url"],
        "status": "Новая",
        "comment": comment[:3000],
        "requestId": item["request_id"],
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK, data=data, method="POST",
        headers={"User-Agent": "ECOFLOT-Object-Leads/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        resp = parse_webhook_response(r.status, body, "Object lead webhook")
    record_lead_result(item["request_id"], resp, "Object Leads")

    if not telegram_delivery_confirmed(resp):
        # Search success and Telegram delivery are separate stages.
        # Never turn a valid search result into a search failure because delivery is pending.
        print("TELEGRAM_DELIVERY_PENDING: queued/reconcile required for current cycle", flush=True)

def notify_none():
    return send_notify_reliable(
        "🏗 ECOFLOT Object Leads: проверка проведена, новых потенциальных объектов не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-Object-Leads/2.0",
        source="Object Leads",
    )

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    legacy_local = state.get("last_run", {}).get("metrics_version") != 2
    sheet_ids, _, _, _ = load_sheet_index()
    found = {}
    errors = []
    for query_geo, query in queries():
        try:
            feed = fetch(google_news_url(query))
            items = parse_feed(feed, query_geo)
            for item in items:
                found[item["request_id"]] = item
        except Exception as exc:
            errors.append(f"{query_geo}: {exc}")
    items = sorted(found.values(), key=lambda x: (-x["score"], x["date"], x["title"]))

    # Object Leads не является тендером, поэтому на него распространяется
    # общее правило ECOFLOT: нужен публичный телефон или прямая контактная ссылка.
    contact_ready = []
    for item in items:
        try:
            page = fetch(item.get("url") or "", timeout=15)
            item["contact_text"] = page[:12000]
        except Exception as exc:
            errors.append(f"contact page {item.get('url')}: {exc}")
            item["contact_text"] = item.get("description", "")
        ok, reason = ensure_public_contact(item)
        if ok:
            contact_ready.append(item)
        else:
            print("EXCLUDED_CONTACT:", reason, item.get("request_id"), item.get("url"))
    items = contact_ready

    fresh = [x for x in items if (legacy_local or x["request_id"] not in sent) and x["request_id"] not in sheet_ids]
    sent_count = 0
    for item in fresh[:MAX_SEND]:
        try:
            send(item)
            sent[item["request_id"]] = datetime.now(timezone.utc).isoformat()
            sent_count += 1
            save_state(state)
            print("ACCEPTED", item["score"], item["location"], item["signal"], item["title"][:120])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")
    if os.environ.get("SUPPRESS_NO_RESULTS", "0") != "1" and sent_count == 0 and len(errors) < len(queries()):
        try:
            notify_none()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append("notify-none: " + str(exc))
    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cycleKey": os.environ.get("ECOFLOT_CYCLE_KEY", "").strip(),
        "run_id": run_id(),
        "error_details": errors,
        "candidates": len(items),
        "duplicates_local": len(items) - len(fresh),
        "deferred": max(0, len(fresh) - MAX_SEND),
        "new": len(fresh),
        "sent": sent_count,
        "errors": len(errors),
    }
    finish_metrics(state)
    save_state(state)
    print(f"Object leads candidates={len(items)}, new={len(fresh)}, sent={sent_count}, errors={len(errors)}")
    for err in errors:
        print("ERROR:", err, file=sys.stderr)
    if errors and len(errors) >= len(queries()) and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
