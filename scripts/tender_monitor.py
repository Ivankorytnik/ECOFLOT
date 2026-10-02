#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from internet_leads_monitor import (
    parse_webhook_response,
    telegram_delivery_confirmed,
    send_notify_reliable,
)

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
STATE_PATH = Path("tender_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "100"))
SHEET_ID = "1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws"
SHEET_NAME = "Заявки"

SOURCES = [
    ("Московская область / отходы", "https://gentender.ru/tenders/utilizaciya-othodov/moskovskaya-oblast"),
    ("Москва / отходы", "https://gentender.ru/tenders/utilizaciya-othodov/moskva"),
    ("Московская область / строительство", "https://gentender.ru/tenders/stroitelstvo/moskovskaya-oblast"),
    ("Москва / строительство", "https://gentender.ru/tenders/stroitelstvo/moskva"),
    ("Московская область / благоустройство", "https://gentender.ru/tenders/blagoustroystvo/moskovskaya-oblast"),
    ("Москва / благоустройство", "https://gentender.ru/tenders/blagoustroystvo/moskva"),
    ("Московская область / транспорт", "https://gentender.ru/tenders/transport/moskovskaya-oblast"),
    ("Москва / транспорт", "https://gentender.ru/tenders/transport/moskva"),
    ("Московская область / спецтехника", "https://gentender.ru/tenders/spetstehnika/moskovskaya-oblast"),
    ("Москва / спецтехника", "https://gentender.ru/tenders/spetstehnika/moskva"),
    ("Калужская область / отходы", "https://gentender.ru/tenders/utilizaciya-othodov/kaluzhskaya-oblast"),
    ("Калужская область / строительство", "https://gentender.ru/tenders/stroitelstvo/kaluzhskaya-oblast"),
    ("Калужская область / благоустройство", "https://gentender.ru/tenders/blagoustroystvo/kaluzhskaya-oblast"),
    ("Калужская область / транспорт", "https://gentender.ru/tenders/transport/kaluzhskaya-oblast"),
    ("Калужская область / спецтехника", "https://gentender.ru/tenders/spetstehnika/kaluzhskaya-oblast"),
]

DIRECT_SOURCES = [
    ("ЕАСУЗ / Электронный магазин МО", "https://easuz.mosreg.ru/torgi", "Московская область"),
    ("Портал поставщиков Москвы", "https://zakupki.mos.ru/", "Москва"),
    ("ПИК ETP", "https://etp.pik.ru/trades", "Москва / Московская область"),
    ("А101", "https://a101.ru/company/partnership/tenders", "Новая Москва / Московская область"),
    ("Самолёт S.Tender", "https://partner.samolet.ru/", "Москва / Московская область"),
    ("Sminex", "https://corp.sminex.com/sotrudnichestvo/tendery-developera", "Москва / Московская область"),
    ("Level Group ETP", "https://etp.level.ru/trades", "Москва / Московская область"),
    ("B2B-Center / самосвалы / Москва", "https://www.b2b-center.ru/search/moskva/samosvaly/", "Москва"),
    ("B2B-Center / самосвалы / Московская область", "https://www.b2b-center.ru/search/moskovskaya-oblast/samosvaly/", "Московская область"),
    ("B2B-Center / самосвалы / Калужская область", "https://www.b2b-center.ru/search/kaluzhskaya-oblast/samosvaly/", "Калужская область"),
    ("B2B-Center / спецтехника / Москва", "https://www.b2b-center.ru/search/moskva/spectexnika/", "Москва"),
    ("B2B-Center / спецтехника / Московская область", "https://www.b2b-center.ru/search/moskovskaya-oblast/spectexnika/", "Московская область"),
    ("B2B-Center / спецтехника / Калужская область", "https://www.b2b-center.ru/search/kaluzhskaya-oblast/spectexnika/", "Калужская область"),
]

TELEGRAM_TENDER_SOURCES = [
    ("ФСК тендеры", "fsk_tenders", "Москва / Московская область"),
]

TENDER_WEB_DISCOVERY_QUERIES = [
    'site:fabrikant.ru самосвал закупка Москва',
    'site:fabrikant.ru спецтехника закупка Московская область',
    'site:fabrikant.ru самосвал закупка Калужская область',
    'site:roseltorg.ru самосвал закупка Москва',
    'site:roseltorg.ru спецтехника закупка Московская область',
    'site:roseltorg.ru самосвал закупка Калужская область',
    'site:rts-tender.ru самосвал закупка Москва',
    'site:rts-tender.ru спецтехника закупка Московская область',
    'site:rts-tender.ru самосвал закупка Калужская область',
    'site:sberbank-ast.ru самосвал закупка Москва',
    'site:sberbank-ast.ru спецтехника закупка Московская область',
    'site:sberbank-ast.ru самосвал закупка Калужская область',
    'site:etpgpb.ru самосвал закупка Москва',
    'site:etpgpb.ru спецтехника закупка Московская область',
    'site:etpgpb.ru самосвал закупка Калужская область',
]

POSITIVE = (
    "вывоз", "транспортирован", "транспортировк", "сбор отход",
    "тко", "кгм", "мусор", "свалк", "навал", "шлам", "фильтрат",
    "отходов производства и потребления",
)

EXCLUDE = (
    "медицинск", "класса «б»", 'класса "б"', "списанного имущества",
    "оргтехник", "технических средств", "медицинского оборудования",
    "огнетушител", "ртуть", "ламп", "аккумулятор", "шин",
    "снег", "дерев", "пней", "порубоч", "картридж",
    "строительного контроля", "фильтров и фильтрующей загрузки",
    "пищевых отходов", "химических реактивов",
)

KNOWN_ALREADY_SENT = {
    "0848300049026000814",
    "0348500002526000035",
    "0348500002526000036",
    "0348500002526000038",
    "32616359218",
    "tt-944900",
    "sb-106940500",
    "0848300057726000038",
    "0848300060626000359",
    "32616351362",
    "32616403656",
    "0373200053626000393",
    "0873200003326000006",
    "32616379842",
    "0373200567226000049",
    "0373200052726000765",
    "0373100108126000461",
    "0373200086526000040",
    "eat-200907385126100091",
    "0373200178126000382",
    "0373200104826000078",
    "0373200575326000076",
    "0373200452826000022",
    "32616394393",
    "tt-941247",
    "32616400837",
    "sb-109308734",
    "32616382864",
    "32616406750",
    "32616405856",
    "32616406641",
    "32616405369",
    "32616409181",
}

def fetch(url: str, timeout=30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ECOFLOT-Tender-Monitor/2.0)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def request_id_for(entry) -> str:
    return "TENDER-" + re.sub(r"[^A-Za-z0-9_-]", "", entry["id"])[:80]

def valid_tender_card_link(entry) -> bool:
    """Тендер допускается только с прямой ссылкой на карточку конкретной закупки."""
    link = str(entry.get("link") or "").strip()
    if not link:
        return False
    try:
        parsed = urllib.parse.urlparse(link)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    path = (parsed.path or "").lower()
    query = urllib.parse.parse_qs(parsed.query or "")
    full = (path + "?" + (parsed.query or "")).lower()

    # Главные, каталожные и поисковые страницы не считаются карточкой.
    listing_only = (
        "/search/" in path and not re.search(r"\d{5,}", full),
        path.rstrip("/") in ("/torgi", "/trades", "/tenders", "/search-tender"),
        path.rstrip("/").endswith("/catalog"),
    )
    if any(listing_only):
        return False

    # Сильные признаки конкретной карточки: числовой ID/номер закупки
    # либо detail-like URL с параметром конкретной процедуры.
    if re.search(r"\d{5,}", full):
        return True
    for key in ("id", "q", "purchase", "procedure", "trade", "tender", "notice"):
        vals = query.get(key, [])
        if any(str(v).strip() for v in vals):
            return True
    if any(token in path for token in ("/procedure/", "/purchase/", "/notice/", "/tender/", "/trade/", "/auction/", "/request/")):
        return True
    return False

def load_sheet_request_ids():
    params = urllib.parse.urlencode({
        "sheet": SHEET_NAME,
        "headers": "1",
        "tqx": "out:json",
        "tq": "select L where L is not null",
    })
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?{params}"
    try:
        raw = fetch(url)
        m = re.search(r"google\.visualization\.Query\.setResponse\((.*)\);?\s*$", raw, re.S)
        payload = json.loads(m.group(1) if m else raw)
        ids = set()
        for row in payload.get("table", {}).get("rows", []):
            cells = row.get("c") or []
            if not cells or not cells[0]:
                continue
            cell = cells[0]
            value = cell.get("v")
            if value is None:
                value = cell.get("f")
            value = str(value or "").strip()
            if value:
                ids.add(value)
        return ids, True
    except Exception as exc:
        print("SHEET_DEDUPE_WARNING:", exc, file=sys.stderr)
        return set(), False

def extract_cards(page: str, source_region: str):
    out = []
    for m in re.finditer(r'<li class="t-card">(.*?)</li>', page, re.I | re.S):
        block = m.group(1)
        q = re.search(r'<a class="t-title" href="/search\?q=([^"]+)">(.*?)</a>', block, re.I | re.S)
        if not q:
            continue
        tender_id = clean(q.group(1))
        title = clean(q.group(2))
        law = clean((re.search(r'<span class="t-law[^"]*">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        region = clean((re.search(r'<span class="t-region">(.*?)</span>', block, re.I | re.S) or [None, source_region])[1])
        customer = clean((re.search(r'<span class="t-cust">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        price = clean((re.search(r'<span class="t-price">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        deadline = clean((re.search(r'<span class="t-dl[^"]*">(.*?)</span>', block, re.I | re.S) or [None, ""])[1])
        out.append({
            "id": tender_id,
            "title": title,
            "law": law,
            "region": region or source_region,
            "customer": customer,
            "price": price,
            "deadline": deadline,
            "link": "https://gentender.ru/search?q=" + urllib.parse.quote(tender_id),
        })
    return out

def direct_relevant(text):
    hay = (text or "").lower().replace("ё", "е")
    include = (
        "вывоз", "мусор", "отход", "грунт", "землян", "котлован",
        "демонтаж", "снос", "благоустрой", "расчист", "погруз",
        "самосвал", "спецтех", "экскаватор", "погрузчик", "контейнер",
        "свалк", "уборк", "содержан", "строительн", "снег",
    )
    exclude = (
        "ваканси", "резюме", "обучение", "новост", "пресс-релиз",
        "политик", "конфиденциаль", "пользовательское соглашение",
    )
    return any(x in hay for x in include) and not any(x in hay for x in exclude)


def extract_direct_cards(page: str, source_label: str, source_url: str, source_region: str):
    out = []
    seen_links = set()
    for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page):
        href = html.unescape(m.group(1)).strip()
        title = clean(m.group(2))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        link = urllib.parse.urljoin(source_url, href).split("#", 1)[0]
        if link in seen_links:
            continue
        seen_links.add(link)

        start = max(0, m.start() - 500)
        end = min(len(page), m.end() + 1200)
        context = clean(page[start:end])
        combined = (title + " " + context).strip()
        if len(title) < 6 and len(context) < 30:
            continue
        generic_titles = (
            "перейти в тендерную систему", "подробнее", "узнать больше",
            "войти", "регистрация", "личный кабинет", "все тендеры",
            "смотреть все", "открыть", "перейти",
        )
        if title.lower().strip() in generic_titles:
            continue
        if not direct_relevant(combined):
            continue

        low = combined.lower().replace("ё", "е")
        if any(x in low for x in ("завершен", "завершён", "архив", "закрыт", "итоги подведены")):
            continue

        deadline = ""
        dm = re.search(r"(?i)(?:до|окончани\w*|срок\w*)[^0-9]{0,20}(\d{1,2}[./]\d{1,2}[./]20\d{2})", combined)
        if dm:
            deadline = dm.group(1)

        price = ""
        pm = re.search(r"(?i)(\d[\d\s]{3,}\s*(?:руб\.?|₽))", combined)
        if pm:
            price = clean(pm.group(1))

        item_id = hashlib.sha1((source_label + "|" + link + "|" + title).encode("utf-8")).hexdigest()[:24]
        out.append({
            "id": "direct-" + item_id,
            "title": (title or combined[:220])[:250],
            "law": "Корпоративная / малая закупка",
            "region": source_region,
            "customer": source_label,
            "price": price,
            "deadline": deadline,
            "link": link,
            "source": source_label,
        })
    return out[:150]


def tender_discovery_urls(query):
    search_url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    page = fetch(search_url, timeout=20)
    urls = []
    allowed_hosts = (
        "fabrikant.ru", "roseltorg.ru", "rts-tender.ru",
        "sberbank-ast.ru", "etpgpb.ru",
    )
    for raw in re.findall(r"https?://[^\"'<>\s]+", page, re.I):
        url = html.unescape(raw).replace("\\u003d", "=").replace("\\u0026", "&")
        url = url.split("&amp;", 1)[0].rstrip(").,;")
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except Exception:
            continue
        if not any(host == d or host.endswith("." + d) for d in allowed_hosts):
            continue
        if url not in urls:
            urls.append(url)
    return urls[:30]

def parse_discovered_tender(url):
    page = fetch(url, timeout=20)
    text = clean(page)
    if not text or not direct_relevant(text):
        return None

    low = text.lower().replace("ё", "е")
    if any(x in low for x in ("завершен", "завершён", "архив", "закрыт", "итоги подведены")):
        return None

    region = ""
    for label, terms in (
        ("Москва", ("москва", "г. москва")),
        ("Московская область", ("московская область", "подмосковье")),
        ("Калужская область", ("калужская область", "калуга", "обнинск")),
    ):
        if any(t in low for t in terms):
            region = label
            break
    if not region:
        return None

    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    title = clean(h1.group(1)) if h1 else ""
    if not title:
        tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
        title = clean(tm.group(1)) if tm else text[:220]

    deadline = ""
    dm = re.search(
        r"(?i)(?:подать заявку до|окончани\w* приема|окончани\w* подачи|до)\D{0,30}"
        r"(\d{1,2}[./]\d{1,2}[./]20\d{2}(?:\s+\d{1,2}:\d{2})?)",
        text,
    )
    if dm:
        deadline = clean(dm.group(1))

    price = ""
    pm = re.search(r"(?i)(?:начальная цена|нмц\w*|цена)\D{0,30}(\d[\d\s]{3,}\s*(?:руб\.?|₽))", text)
    if pm:
        price = clean(pm.group(1))

    customer = ""
    cm = re.search(r"(?i)(?:заказчик|организатор)\s*:?\s*([^\n]{5,220})", text)
    if cm:
        customer = clean(cm.group(1))[:220]

    entry = {
        "id": "discovery-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:24],
        "title": title[:250],
        "law": "Тендер / закупка",
        "region": region,
        "customer": customer,
        "price": price,
        "deadline": deadline,
        "link": url,
        "source": "Tender Web Discovery / " + (urllib.parse.urlparse(url).hostname or "web"),
    }
    return entry if valid_tender_card_link(entry) else None

def extract_telegram_tenders(page: str, source_label: str, channel: str, source_region: str):
    out = []
    marks = list(re.finditer(r'data-post="([^"]+)/(\d+)"', page, re.I))
    procurement_markers = (
        "тендер", "закуп", "прием заяв", "приём заяв", "подача заяв",
        "коммерческое предложение", "запрос предлож", "конкурс",
    )
    work_markers = (
        "котлован", "землян", "снос", "демонтаж", "благоустрой",
        "подготовительн", "расчист", "вывоз", "грунт", "мусор", "отход",
        "контейнер", "самосвал", "спецтех", "экскаватор", "погрузчик",
    )
    informational_exclude = (
        "а вы знали", "архитектур", "дизайн", "офис", "медиахолдинг",
        "цюрих", "швейцари", "история компании", "новости компании",
        "поздравляем", "премия", "рейтинг",
    )

    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else min(len(page), start + 18000)
        block = page[start:end]
        tm = re.search(r'(?is)<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block)
        if not tm:
            continue

        raw = re.sub(r'(?i)<br\s*/?>', '\n', tm.group(1))
        raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        lines = [re.sub(r"\s+", " ", x).strip() for x in raw.splitlines() if re.sub(r"\s+", " ", x).strip()]
        text = " ".join(lines)
        low = text.lower().replace("ё", "е")

        if any(x in low for x in informational_exclude):
            continue
        if not any(x in low for x in procurement_markers):
            continue
        if not any(x in low for x in work_markers):
            continue
        if not any(x in low for x in ("москва", "московск", "химки", "видное", "одинцов", "красногор", "новая москва")):
            continue

        deadline = ""
        dm = re.search(
            r'(?i)(?:до|прием заявок до|приём заявок до)\s+'
            r'(\d{1,2}\s+[а-яё]+|\d{1,2}[./]\d{1,2}(?:[./]20\d{2})?)',
            text,
        )
        if dm:
            deadline = clean(dm.group(1))

        post_channel = m.group(1)
        post_id = m.group(2)
        link = f"https://t.me/{post_channel}/{post_id}"
        item_id = "telegram-" + post_channel + "-" + post_id

        title = next(
            (
                line.strip("🔸📍⚡️✅ ")
                for line in lines
                if any(k in line.lower().replace("ё", "е") for k in work_markers)
            ),
            lines[0] if lines else text[:220],
        )

        out.append({
            "id": item_id,
            "title": title[:250],
            "law": "Корпоративная закупка / Telegram-анонс",
            "region": source_region,
            "customer": source_label,
            "price": "",
            "deadline": deadline,
            "link": link,
            "source": source_label,
        })
    return out

def relevant(entry):
    hay = entry["title"].lower()
    if any(x in hay for x in EXCLUDE):
        return False

    strong = (
        "вывоз мусор", "вывоз отход", "транспортирование отход",
        "транспортировка отход", "сбор, транспортирован", "сбор и транспортирован",
        "некоммунальных отход", "строительный мусор", "строительных отход",
        "отходов строительства", "отходов сноса", "ликвидац", "свалк",
        "навал мусор", "навал отход", "крупногабаритных отход", "кго", "кгм",
        "отходов iii", "отходов iv", "отходов v", "iii класса", "iv класса",
        "v класса", "iii-iv клас", "iv-v клас", "iii-v клас",
        "3 класса опасности", "4 класса опасности", "5 класса опасности",
        "3-4 клас", "4-5 клас", "3-5 клас", "шлам", "фильтрат"
    )
    if any(x in hay for x in strong):
        return True

    if ("строитель" in hay or "снос" in hay or "демонтаж" in hay) and "отход" in hay:
        return True

    if ("контейнер" in hay or "бункер" in hay) and ("отход" in hay or "мусор" in hay):
        return True

    if ("уборк" in hay or "содержан" in hay) and "вывоз" in hay and ("отход" in hay or "мусор" in hay):
        return True

    if "сбор" in hay and "отход" in hay and ("транспорт" in hay or "вывоз" in hay):
        return True

    return False

def load_state():
    if not STATE_PATH.exists():
        return {"sent": {}}
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"sent": {}}

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 3000:
        recent = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:3000]
        state["sent"] = dict(recent)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")

def send_webhook(entry):
    comment = (
        f"Заказчик: {entry['customer'] or 'не указан'}\n"
        f"Цена: {entry['price'] or 'не указана'}\n"
        f"Закон/тип: {entry['law'] or 'не указан'}\n"
        f"Регион: {entry['region']}\n"
        f"Срок: {entry['deadline'] or 'не указан'}\n"
        f"Ссылка: {entry['link']}"
    )
    payload = {
        "type": "Тендер",
        "name": entry["title"][:250],
        "phone": "-",
        "wasteType": "Вывоз / транспортирование отходов",
        "volume": "-",
        "when": entry["deadline"] or "Активная закупка",
        "address": entry["region"],
        "source": f"{entry.get('source') or 'GenTender / данные ЕИС'} | {entry['link']}",
        "link": entry["link"],
        "status": "Новый тендер",
        "comment": comment[:1800],
        "requestId": request_id_for(entry),
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK, data=data, method="POST",
        headers={"User-Agent": "ECOFLOT-Tender-Monitor/3.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        resp = parse_webhook_response(r.status, body, "Tender webhook")

    if not telegram_delivery_confirmed(resp):
        send_notify_reliable(
            (
                "🔎 ECOFLOT Tender Watch\n"
                "Новый тендер\n"
                f"{entry['title'][:600]}\n"
                f"Заказчик: {entry['customer'] or 'не указан'}\n"
                f"Цена: {entry['price'] or 'не указана'}\n"
                f"Регион: {entry['region']}\n"
                f"Срок: {entry['deadline'] or 'не указан'}\n"
                f"Ссылка: {entry['link']}\n"
                f"Request ID: {request_id_for(entry)}"
            ),
            webhook=WEBHOOK,
            user_agent="ECOFLOT-Tender-Monitor/3.0",
            source="Tender Watch",
            request_id=request_id_for(entry),
        )

def send_no_results_message():
    return send_notify_reliable(
        "🔎 ECOFLOT Tender Watch: поиск проведён, новых подходящих тендеров не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-Tender-Monitor/3.0",
        source="Tender Watch",
    )

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    sheet_request_ids, sheet_ok = load_sheet_request_ids()
    print(f"SHEET_DEDUPE: {'ok' if sheet_ok else 'fallback-to-state'}, ids={len(sheet_request_ids)}")
    candidates = []
    seen = set()
    errors = []

    for source_region, url in SOURCES:
        try:
            page = fetch(url)
            cards = extract_cards(page, source_region)
            print(f"SOURCE {source_region}: {len(cards)} active cards")
            for entry in cards:
                if not relevant(entry):
                    continue
                if not valid_tender_card_link(entry):
                    print("EXCLUDED_TENDER_NO_CARD_LINK:", entry.get("id"), entry.get("title","")[:120])
                    continue
                key = hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()
                request_id = request_id_for(entry)
                if request_id in sheet_request_ids:
                    continue
                if entry["id"] in KNOWN_ALREADY_SENT or key in sent or key in seen:
                    continue
                seen.add(key)
                candidates.append((entry, key))
        except Exception as exc:
            errors.append(f"{source_region}: {exc}")

    for source_label, url, source_region in DIRECT_SOURCES:
        try:
            page = fetch(url)
            cards = extract_direct_cards(page, source_label, url, source_region)
            print(f"DIRECT_SOURCE {source_label}: {len(cards)} candidate cards")
            for entry in cards:
                if not valid_tender_card_link(entry):
                    print("EXCLUDED_TENDER_NO_CARD_LINK:", entry.get("id"), entry.get("title","")[:120])
                    continue
                key = hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()
                request_id = request_id_for(entry)
                if request_id in sheet_request_ids:
                    continue
                if key in sent or key in seen:
                    continue
                seen.add(key)
                candidates.append((entry, key))
        except Exception as exc:
            errors.append(f"{source_label}: {exc}")

    discovered_urls = {}
    for query in TENDER_WEB_DISCOVERY_QUERIES:
        try:
            urls = tender_discovery_urls(query)
            print(f"TENDER_DISCOVERY_QUERY {query}: {len(urls)} urls")
            for url in urls:
                discovered_urls[url] = query
        except Exception as exc:
            errors.append(f"Tender discovery {query}: {exc}")

    for url in list(discovered_urls)[:120]:
        try:
            entry = parse_discovered_tender(url)
            if not entry:
                continue
            key = hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()
            request_id = request_id_for(entry)
            if request_id in sheet_request_ids:
                continue
            if key in sent or key in seen:
                continue
            seen.add(key)
            candidates.append((entry, key))
        except Exception as exc:
            errors.append(f"Tender discovery page {url}: {exc}")

    for source_label, channel, source_region in TELEGRAM_TENDER_SOURCES:
        try:
            url = f"https://t.me/s/{channel}"
            page = fetch(url)
            cards = extract_telegram_tenders(page, source_label, channel, source_region)
            print(f"TELEGRAM_TENDER_SOURCE {source_label}: {len(cards)} candidate cards")
            for entry in cards:
                if not valid_tender_card_link(entry):
                    print("EXCLUDED_TENDER_NO_CARD_LINK:", entry.get("id"), entry.get("title","")[:120])
                    continue
                key = hashlib.sha1(entry["id"].encode("utf-8")).hexdigest()
                request_id = request_id_for(entry)
                if request_id in sheet_request_ids:
                    continue
                if key in sent or key in seen:
                    continue
                seen.add(key)
                candidates.append((entry, key))
        except Exception as exc:
            errors.append(f"{source_label}: {exc}")

    # Финальный предохранитель: без ссылки на карточку тендер не отправляется.
    candidates = [(entry, key) for entry, key in candidates if valid_tender_card_link(entry)]

    sent_count = 0
    for entry, key in candidates[:MAX_SEND]:
        try:
            send_webhook(entry)
            sent[key] = datetime.now(timezone.utc).isoformat()
            sheet_request_ids.add(request_id_for(entry))
            sent_count += 1
            print("SENT:", entry["id"], entry["title"][:140], entry["price"], entry["deadline"])
        except Exception as exc:
            errors.append(f"send {entry['id']}: {exc}")

    if sent_count == 0 and len(errors) < (
        len(SOURCES) + len(DIRECT_SOURCES) + len(TELEGRAM_TENDER_SOURCES)
        + len(TENDER_WEB_DISCOVERY_QUERIES)
    ):
        try:
            send_no_results_message()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"send no-results notice: {exc}")

    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "candidates": len(candidates),
        "sent": sent_count,
        "errors": len(errors),
    }
    save_state(state)
    print(f"Found new active relevant: {len(candidates)}, sent: {sent_count}, errors: {len(errors)}")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)

    if errors and len(errors) >= (
        len(SOURCES) + len(DIRECT_SOURCES) + len(TELEGRAM_TENDER_SOURCES)
        + len(TENDER_WEB_DISCOVERY_QUERIES)
    ) and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
