#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
SHEET_ID = "1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws"
SHEET_NAME = "Заявки"
STATE_PATH = Path("internet_leads_state.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "50"))
RECENT_DAYS = int(os.environ.get("RECENT_DAYS", "21"))

NPD_SOURCES = [
    ("Москва", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora"),
    ("Строительный мусор / Москва", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-stroitelnogo-musora"),
    ("С грузчиками / Москва", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora-s-gruzchikami"),
    ("Контейнерный вывоз / Москва", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora-konteinerom"),
    ("Макулатура / Москва", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-makulatury"),
    ("Одинцово", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-odincovo"),
    ("Красногорск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-krasnogorsk"),
    ("Истра", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-istra"),
    ("Химки", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-ximki"),
    ("Солнечногорск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-solnecnogorsk"),
    ("Наро-Фоминск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-naro-fominsk"),
    ("Можайск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-mozaisk"),
    ("Подольск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-podolsk"),
    ("Апрелевка", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-aprelevka"),
    ("Краснознаменск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-krasnoznamensk"),
    ("Балашиха", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-balasixa"),
    ("Звенигород", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-zvenigorod"),
    ("Видное", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-vidnoe"),
]

PROFI_SOURCES = [
    ("Профи / вывоз мусора", "https://profi.ru/registration/remont/musor/"),
    ("Профи / заказы на вывоз мусора", "https://profi.ru/rabota/remont/vyvoz-musora/"),
    ("Профи / вывоз с грузчиками", "https://profi.ru/rabota/remont/uslugi-po-vyvozu-musora-s-gruzchikami/"),
    ("Профи / уборка строительного мусора", "https://profi.ru/rabota/remont/uslugi-po-uborke-stroitelnogo-musora/"),
]

# YouDo/Yandex/Avito are intentionally not treated as automatic demand feeds here.
# Their public pages currently mix provider profiles with service catalog content,
# which can create false leads. They can be added later only with a reliable public
# order feed or authenticated API.
YOUDO_SOURCES = []

POSITIVE = (
    "вывоз мусор", "вывоз строитель", "вывоз бытов", "строительн", "бытовой мусор",
    "крупногабарит", "кгм", "кго", "контейнер", "утилизац", "отход", "мусор",
    "металлолом", "макулатур", "ветк", "дерев", "грунт", "демонтаж",
)
EXCLUDE = (
    "откачка", "септик", "канализац", "медицинск", "ртут", "ламп",
    "аккумулятор", "шины", "пищев", "реактив",
)

def fetch(url: str, timeout=8) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ECOFLOT-Internet-Leads/1.0)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def lines_from_html(page: str):
    page = re.sub(r"(?is)<(script|style).*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>", "\n", page)
    page = re.sub(r"(?i)</(?:p|div|li|h1|h2|h3|h4|tr|td|section|article|a|span)>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page)
    lines = [re.sub(r"\s+", " ", x).strip() for x in page.splitlines()]
    return [x for x in lines if x]

def value_after_label(lines, label):
    low_label = label.lower()
    for i, line in enumerate(lines):
        low = line.lower()
        if low == low_label and i + 1 < len(lines):
            return lines[i + 1]
        if low.startswith(low_label + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def section_after_label(lines, label, stop_words, max_chars=1600):
    low_label = label.lower()
    start = None
    for i, line in enumerate(lines):
        if line.lower() == low_label:
            start = i + 1
            break
    if start is None:
        return ""
    out = []
    total = 0
    for line in lines[start:]:
        if any(line.lower().startswith(x.lower()) for x in stop_words):
            break
        total += len(line) + 1
        if total > max_chars:
            break
        out.append(line)
    return " ".join(out).strip()

def parse_date(text):
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None

def is_recent(date_text):
    dt = parse_date(date_text)
    if not dt:
        return True
    return datetime.now(timezone.utc) - dt <= timedelta(days=RECENT_DAYS)

def extract_volume(text):
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*(?:м3|м³|куб(?:\.|ов|а|ов)?|куб\.?\s*м)",
        r"контейнер[^0-9]{0,20}(\d+(?:[.,]\d+)?)\s*(?:м3|м³|куб)",
        r"(\d+)\s*мешк",
    ]
    for p in patterns:
        m = re.search(p, text or "", re.I)
        if m:
            value = m.group(1).replace(",", ".")
            if "мешк" in m.group(0).lower():
                return value + " мешков"
            return value + " м³"
    return ""

def relevant(title, description):
    hay = (title + " " + description).lower()
    if any(x in hay for x in EXCLUDE):
        return False
    return any(x in hay for x in POSITIVE)

def priority_for(text):
    hay = text.lower()
    if any(x in hay for x in ("27 м", "20 м", "контейнер", "регуляр", "постоян", "юр. лица", "юрлица", "договор")):
        return "Высокий"
    if any(x in hay for x in ("8 м", "10 м", "12 м", "строительн", "грунт", "демонтаж")):
        return "Средний"
    return "Обычный"

def normalize(s):
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[^a-zа-я0-9]+", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()

def signature(title, location, description):
    base = "|".join([normalize(title), normalize(location), normalize(description)[:350]])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def load_sheet_index():
    params = urllib.parse.urlencode({
        "sheet": SHEET_NAME,
        "headers": "1",
        "tqx": "out:json",
        "tq": "select C,H,K,L where L is not null",
    })
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?{params}"
    ids, links, sigs = set(), set(), set()
    try:
        raw = fetch(url)
        m = re.search(r"google\.visualization\.Query\.setResponse\((.*)\);?\s*$", raw, re.S)
        payload = json.loads(m.group(1) if m else raw)
        for row in payload.get("table", {}).get("rows", []):
            cells = row.get("c") or []
            vals = []
            for cell in cells:
                if not cell:
                    vals.append("")
                    continue
                v = cell.get("v")
                if v is None:
                    v = cell.get("f")
                vals.append(str(v or "").strip())
            while len(vals) < 4:
                vals.append("")
            title, address, comment, request_id = vals[:4]
            if request_id:
                ids.add(request_id)
            for link in re.findall(r"https?://[^\s]+", comment):
                links.add(link.rstrip(").,;"))
            desc_match = re.search(r"Описание:\s*(.*?)(?:\s+Цена:|\s+Дата публикации:|\s+Ссылка:|$)", comment, re.I)
            if desc_match:
                sigs.add(signature(title, address, desc_match.group(1)))
        return ids, links, sigs, True
    except Exception as exc:
        print("SHEET_DEDUPE_WARNING:", exc, file=sys.stderr)
        return ids, links, sigs, False

def load_state():
    if not STATE_PATH.exists():
        return {"sent": {}}
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"sent": {}}

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        recent = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:5000]
        state["sent"] = dict(recent)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")

def npd_listing_links(page):
    links = set()
    for href in re.findall(r'href=["\']([^"\']+/order/\d+[^"\']*)["\']', page, re.I):
        links.add(urllib.parse.urljoin("https://www.napodrabotku.ru", href))
    for href in re.findall(r'href=["\'](/order/\d+[^"\']*)["\']', page, re.I):
        links.add(urllib.parse.urljoin("https://www.napodrabotku.ru", href))
    return sorted(links)

def parse_npd_order(url, source_label):
    page = fetch(url)
    lines = lines_from_html(page)
    text = " ".join(lines)
    if "Откликнуться" not in text:
        return None

    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    title = clean(h1.group(1)) if h1 else (lines[0] if lines else "Заявка на вывоз мусора")
    description = section_after_label(
        lines, "Описание",
        ("Откликнуться", "Похожие", "Часто задаваемые", "Другие заказы", "Заказы"),
        max_chars=1800,
    )
    if not description:
        description = text[:1200]
    if not relevant(title, description):
        return None

    date_text = value_after_label(lines, "Дата публикации")
    if not is_recent(date_text):
        return None
    price = value_after_label(lines, "Стоимость") or "договорная"
    region = value_after_label(lines, "Регион")
    city = value_after_label(lines, "Город")
    metro = value_after_label(lines, "Метро")
    location = ", ".join(x for x in (city, metro, region) if x)
    if not location:
        location = source_label

    m = re.search(r"/order/(\d+)", url)
    order_id = m.group(1) if m else hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    volume = extract_volume(description)
    return {
        "request_id": "WEB-NPD-" + order_id,
        "title": title[:250],
        "description": description[:1800],
        "price": price[:120],
        "date": date_text or "свежая заявка",
        "location": location[:250],
        "volume": volume or "-",
        "url": url,
        "source": "НаПодработку",
        "priority": priority_for(title + " " + description),
    }

def parse_profi_relative_date(text):
    t = (text or "").strip().lower()
    now = datetime.now(timezone.utc)
    if t == "сегодня":
        return now
    if t == "вчера":
        return now - timedelta(days=1)
    m = re.match(r"(\d+)\s*(?:час|часа|часов)\s+назад", t)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*(?:минут|минуты|минуту)\s+назад", t)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    months = {
        "января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
        "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12,
    }
    m = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(20\d{2})", t)
    if m and m.group(2) in months:
        try:
            return datetime(int(m.group(3)), months[m.group(2)], int(m.group(1)), tzinfo=timezone.utc)
        except ValueError:
            return None
    return None

def profi_recent(date_text):
    dt = parse_profi_relative_date(date_text)
    if not dt:
        return True
    return datetime.now(timezone.utc) - dt <= timedelta(days=RECENT_DAYS)

def parse_profi_orders(page, source_label, source_url):
    out = []
    blocks = re.findall(
        r"(?is)<h3[^>]*>(.*?)</h3>(.*?)(?=<h3[^>]*>|</main>|<footer|$)",
        page,
    )
    for raw_title, raw_body in blocks:
        title = clean(raw_title)
        if "вывоз" not in title.lower() and "мусор" not in title.lower():
            continue

        body_lines = lines_from_html(raw_body)
        if not any("Откликнуться" in x for x in body_lines):
            continue

        cleaned_lines = []
        for line in body_lines:
            if line == "Откликнуться" or line.startswith("Image:"):
                continue
            cleaned_lines.append(line)
        if not cleaned_lines:
            continue

        date_text = ""
        date_idx = None
        for i in range(len(cleaned_lines) - 1, -1, -1):
            line = cleaned_lines[i]
            if (
                re.match(r"^\d{1,2}\s+[А-Яа-яЁё]+\s+20\d{2}$", line)
                or re.match(r"^\d+\s+(?:час|часа|часов|минут|минуты|минуту)\s+назад$", line, re.I)
                or line.lower() in ("сегодня", "вчера")
            ):
                date_text = line
                date_idx = i
                break

        if date_idx is not None and date_idx > 0:
            location = cleaned_lines[date_idx - 1]
            desc_lines = cleaned_lines[: max(0, date_idx - 1)]
        else:
            location = source_label
            desc_lines = cleaned_lines

        price = "договорная"
        desc_clean = []
        for line in desc_lines:
            if re.fullmatch(r"(?:до\s*)?[\d\s\u00a0]+\s*₽", line, re.I):
                price = line
                continue
            desc_clean.append(line)

        description = " ".join(desc_clean).strip()
        if not description:
            continue
        if not relevant(title, description):
            continue
        if date_text and not profi_recent(date_text):
            continue

        sig = signature(title, location, description)
        out.append({
            "request_id": "WEB-PROFI-" + sig[:20],
            "title": title[:250],
            "description": description[:1800],
            "price": price[:120],
            "date": date_text or "актуальная заявка",
            "location": location[:250],
            "volume": extract_volume(description) or "-",
            "url": source_url,
            "source": "Профи.ру",
            "priority": priority_for(title + " " + description),
        })
    return out

def extract_youdo_candidates(page, source_label, source_url):
    candidates = []
    seen = set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', page, re.I):
        href = html.unescape(m.group(1))
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        start = max(0, m.start() - 500)
        end = min(len(page), m.end() + 1400)
        context = clean(page[start:end])
        if not relevant(context[:250], context):
            continue
        url = urllib.parse.urljoin(source_url, href)
        if url in seen:
            continue
        seen.add(url)
        title_match = re.search(
            r"(Вывоз[^.!?]{0,120}|Утилизац[^.!?]{0,120}|Мусор[^.!?]{0,120}|Контейнер[^.!?]{0,120})",
            context, re.I
        )
        title = clean(title_match.group(1)) if title_match else "Заявка на вывоз мусора"
        if len(title) > 250:
            title = title[:250]
        price_match = re.search(r"(?:до\s*)?[\d\s\u00a0]{3,}\s*руб", context, re.I)
        price = clean(price_match.group(0)) if price_match else "договорная"
        description = context[:1600]
        candidates.append({
            "request_id": "WEB-YOUDO-" + hashlib.sha1((url + "|" + title).encode("utf-8")).hexdigest()[:20],
            "title": title,
            "description": description,
            "price": price,
            "date": "актуальная выдача",
            "location": source_label,
            "volume": extract_volume(description) or "-",
            "url": url,
            "source": "YouDo",
            "priority": priority_for(title + " " + description),
        })
    return candidates[:50]

def collect_candidates():
    candidates = []
    errors = []
    npd_links = {}

    def fetch_npd_listing(source):
        source_label, source_url = source
        page = fetch(source_url)
        return source_label, npd_listing_links(page)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_npd_listing, src): src for src in NPD_SOURCES}
        for future in as_completed(futures):
            source_label, source_url = futures[future]
            try:
                label, links = future.result()
                print(f"NPD_SOURCE {label}: {len(links)} order links")
                for link in links:
                    npd_links.setdefault(link, label)
            except Exception as exc:
                errors.append(f"NPD listing {source_label}: {exc}")

    def fetch_npd_order(args):
        link, source_label = args
        return link, parse_npd_order(link, source_label)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch_npd_order, item): item for item in npd_links.items()}
        for future in as_completed(futures):
            link, source_label = futures[future]
            try:
                _, item = future.result()
                if item:
                    candidates.append(item)
            except Exception as exc:
                errors.append(f"NPD order {link}: {exc}")

    def fetch_profi(source):
        source_label, source_url = source
        page = fetch(source_url)
        return source_label, parse_profi_orders(page, source_label, source_url)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_profi, src): src for src in PROFI_SOURCES}
        for future in as_completed(futures):
            source_label, source_url = futures[future]
            try:
                label, found = future.result()
                print(f"PROFI_SOURCE {label}: {len(found)} current order blocks")
                candidates.extend(found)
            except Exception as exc:
                errors.append(f"Profi {source_label}: {exc}")

    for source_label, source_url in YOUDO_SOURCES:
        try:
            page = fetch(source_url)
            found = extract_youdo_candidates(page, source_label, source_url)
            print(f"YOUDO_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"YouDo {source_label}: {exc}")

    unique = {}
    for item in candidates:
        unique[item["request_id"]] = item
    return list(unique.values()), errors

def send_webhook(item):
    comment = (
        f"Приоритет: {item['priority']}\n"
        f"Описание: {item['description']}\n"
        f"Цена: {item['price']}\n"
        f"Дата публикации: {item['date']}\n"
        f"Ссылка: {item['url']}"
    )
    payload = {
        "type": "Интернет-заявка",
        "name": item["title"],
        "phone": "-",
        "wasteType": "Вывоз мусора / отходов",
        "volume": item["volume"],
        "when": item["date"],
        "address": item["location"],
        "source": item["source"],
        "status": "Новая",
        "comment": comment[:3500],
        "requestId": item["request_id"],
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=data,
        method="POST",
        headers={"User-Agent": "ECOFLOT-Internet-Leads/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        if not (200 <= r.status < 300):
            raise RuntimeError(f"Webhook HTTP {r.status}: {body[:300]}")
        try:
            resp = json.loads(body)
            if not resp.get("ok"):
                raise RuntimeError(f"Webhook error: {body[:300]}")
        except json.JSONDecodeError:
            pass

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    sheet_ids, sheet_links, sheet_sigs, sheet_ok = load_sheet_index()
    print(
        f"SHEET_DEDUPE: {'ok' if sheet_ok else 'fallback-to-state'}, "
        f"ids={len(sheet_ids)}, links={len(sheet_links)}, sigs={len(sheet_sigs)}"
    )

    candidates, errors = collect_candidates()
    candidates.sort(key=lambda x: (x["priority"] != "Высокий", x["priority"] != "Средний", x["source"], x["title"]))

    new_items = []
    local_seen = set()
    for item in candidates:
        request_id = item["request_id"]
        sig = signature(item["title"], item["location"], item["description"])
        if request_id in sheet_ids or item["url"] in sheet_links or sig in sheet_sigs:
            continue
        if request_id in sent or request_id in local_seen:
            continue
        local_seen.add(request_id)
        new_items.append(item)

    sent_count = 0
    for item in new_items[:MAX_SEND]:
        try:
            send_webhook(item)
            sent[item["request_id"]] = datetime.now(timezone.utc).isoformat()
            sheet_ids.add(item["request_id"])
            sheet_links.add(item["url"])
            sheet_sigs.add(signature(item["title"], item["location"], item["description"]))
            sent_count += 1
            print("SENT:", item["source"], item["request_id"], item["title"][:140], item["location"])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")

    save_state(state)
    print(
        f"Internet candidates: {len(candidates)}, new after dedupe: {len(new_items)}, "
        f"sent: {sent_count}, errors: {len(errors)}"
    )
    for error in errors:
        print("ERROR:", error, file=sys.stderr)

    if errors and not candidates and sent_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
