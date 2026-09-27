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
RECENT_DAYS = 7
MIN_RELEVANCE_SCORE = 60

NPD_SOURCES = [
    ("Одинцово", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-odincovo"),
    ("Краснознаменск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-krasnoznamensk"),
    ("Звенигород", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-zvenigorod"),
    ("Красногорск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-krasnogorsk"),
    ("Истра", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-istra"),
    ("Апрелевка", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-aprelevka"),
    ("Наро-Фоминск", "https://www.napodrabotku.ru/msk/jobs-stroyka-remont/vyvoz-musora/town-naro-fominsk"),
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

P24_SOURCES = [
    ("Перевозка24 / все заказы спецтехники", "https://perevozka24.ru/dolgosrochnaya-arenda"),
]

VEZETVSEM_SOURCES = [
    ("Везёт Всем / вывоз мусора", "https://www.vezetvsem.ru/listing/all/vyvoz_musora"),
    ("Везёт Всем / строительные грузы", "https://www.vezetvsem.ru/listing/moskva/stroitelnye_gruzy_i_oborudovanie"),
]

DOZZR_SOURCES = [
    ("Dozzr / самосвалы и тонары", "https://dozzr.ru/catalog/28"),
    ("Dozzr / общая лента", "https://dozzr.ru/"),
]

NERUDONLINE_SOURCES = [
    ("НерудОнлайн / работа для самосвалов", "https://nerudonline.ru/rabota/samosvaly"),
]

SPECTEX_SOURCES = [
    ("Spectex / заявки спецтехники", "https://www.spectex.su/"),
]

YELLTY_SOURCES = [
    ("Yellty / свежие заказы", "https://yellty.ru/zakazy"),
]

BETON24_SOURCES = [
    ("Бетон24 / заявки спецтехники МО", "https://beton24.ru/moskovskaya-oblast/orders/arenda-spectehniki-368/"),
    ("Бетон24 / заявки спецтехники", "https://beton24.ru/orders/arenda-spectehniki-368/"),
]

EXKAVATOR_SOURCES = [
    ("Экскаватор Ру / заявки на аренду", "https://exkavator.ru/exchange/rent/main.html"),
]

VSEMPODRYAD_SOURCES = [
    ("Всем Подряд / Москва / земляные работы", "https://vsem-podryad.ru/request/" + urllib.parse.quote("Москва") + "/" + urllib.parse.quote("Дорожные, земляные работы, благоустройство") + "/"),
    ("Всем Подряд / МО / земляные работы", "https://vsem-podryad.ru/request/" + urllib.parse.quote("Московская область") + "/" + urllib.parse.quote("Дорожные, земляные работы, благоустройство") + "/"),
    ("Всем Подряд / Москва / демонтаж", "https://vsem-podryad.ru/request/" + urllib.parse.quote("Москва") + "/" + urllib.parse.quote("Демонтажные работы, разборка и снос зданий") + "/"),
    ("Всем Подряд / МО / демонтаж", "https://vsem-podryad.ru/request/" + urllib.parse.quote("Московская область") + "/" + urllib.parse.quote("Демонтажные работы, разборка и снос зданий") + "/"),
]

GEO_ALLOW = (
    "одинцов", "барвиха", "горки-2", "горки 2", "горки-10", "горки 10",
    "рублев", "рублёв", "усово", "жуковка", "николина гора", "раздоры",
    "новоивановск", "новоивановский", "лесной городок", "внуково",
    "кубинк", "голицыно", "большие вяземы", "малые вяземы",
    "краснознаменск", "звенигород", "красногорск", "нахабино",
    "истра", "дедовск", "апрелевка", "наро-фоминск", "наро фоминск",
    "новая москва", "троицк", "московский", "коммунарка", "щербинка",
    "кокошкино", "первомайское", "марушкинское", "филимонковское"
)

POSITIVE = (
    "вывоз строительного мусора", "строительные отходы", "отходы ремонта",
    "отходы демонтажа", "контейнер 8", "контейнер 20", "контейнер 27",
    "вывоз грунта", "бой бетона", "кирпич", "крупногабаритный мусор",
    "кгм", "кго", "вывоз мебели", "бытовой хлам", "ветки", "древесина",
    "металлолом", "производственные отходы", "смешанные отходы",
    "вывоз тко", "контейнерная площадка", "механизированная погрузка",
    "погрузка мусора", "погрузка грунта", "расчистка территории",
    "очистка строительной площадки", "земляные работы",
    "погрузка самосвалов", "перевозка песка", "перевозка щебня",
    "вывоз мусора", "самосвал", "тонар", "экскаватор-погрузчик",
    "экскаватор погрузчик", "мусоровоз", "ломовоз", "бункеровоз", "мультилифт",
    "демонтаж", "снос здания", "снос строения", "разбор здания", "разбор строения",
    "гидромолот", "выемка грунта", "разработка грунта", "выборка грунта",
    "котлован", "расчистка участка", "очистка участка", "уборка территории",
    "порубочные остатки", "подготовка площадки",
)
EXCLUDE = (
    "откачка", "септик", "канализац", "медицинск", "ртут", "ламп",
    "аккумулятор", "шины", "пищев", "реактив",
)

def fetch(url: str, timeout=10, attempts=2) -> str:
    last_exc = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,*/*",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout + attempt * 4) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as exc:
            last_exc = exc
    raise last_exc

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

def geo_allowed(location, title="", description=""):
    hay = " ".join([location or "", title or "", description or ""]).lower().replace("ё", "е")
    return any(term.replace("ё", "е") in hay for term in GEO_ALLOW)

def relevant(title, description):
    hay = (title + " " + description).lower()
    if any(x in hay for x in EXCLUDE):
        return False
    return any(x in hay for x in POSITIVE)

def lead_class(title, description):
    hay = normalize((title or "") + " " + (description or ""))
    hot = (
        "вывоз", "контейнер", "самосвал", "тонар", "мусоровоз", "ломовоз",
        "бункеровоз", "мультилифт", "погрузка мусора", "погрузка грунта",
        "нужен экскаватор", "требуется экскаватор", "требуются самосвалы",
        "требуется самосвал",
    )
    if any(x in hay for x in hot):
        return "HOT"
    warm = (
        "демонтаж", "снос", "разбор", "гидромолот", "выемка грунта",
        "разработка грунта", "выборка грунта", "котлован", "земляные работы",
        "расчистка", "подготовка площадки", "порубочные остатки",
    )
    if any(x in hay for x in warm):
        return "WARM"
    return "HOT"

def infer_work_equipment(title, description):
    hay = normalize((title or "") + " " + (description or ""))
    if any(x in hay for x in ("экскаватор-погрузчик","экскаватор погрузчик")):
        return "Погрузка / земляные работы", "Экскаватор-погрузчик"
    if any(x in hay for x in ("мусоровоз","регулярный вывоз тко")):
        return "Регулярный вывоз ТКО / обслуживание площадок", "Мусоровоз"
    if any(x in hay for x in ("бункеровоз","мультилифт","контейнер 8","контейнер 20","контейнер 27","бункер")):
        return "Контейнерный вывоз", "Бункеровоз / мультилифт"
    if any(x in hay for x in ("грунт","котлован","земляные работы")):
        return "Вывоз / погрузка грунта", "Самосвал / экскаватор-погрузчик"
    if any(x in hay for x in ("металлолом","металлическ","грейфер")):
        return "Вывоз металлолома / механизированная погрузка", "Ломовоз с КМУ и грейфером"
    if any(x in hay for x in ("ветк","древес","доски")):
        return "Вывоз древесины", "Ломовоз с КМУ / бункеровоз"
    if any(x in hay for x in ("тко","контейнерная площадка","регулярный вывоз")):
        return "Регулярный вывоз ТКО / обслуживание площадок", "Мусоровоз"
    if any(x in hay for x in ("кгм","кго","крупногабарит","мебель","диван","шкаф","хлам")):
        return "Вывоз КГМ / мебели и хлама", "Газель / бункеровоз / мультилифт"
    if any(x in hay for x in ("строитель","ремонт","демонтаж","снос","разбор","гидромолот","кирпич","бетон")):
        return "Вывоз строительного мусора / отходов демонтажа", "Бункеровоз / мультилифт / самосвал / экскаватор-погрузчик"
    if any(x in hay for x in ("расчистка территории","очистка стройплощадки","погрузка мусора","погрузка отходов")):
        return "Расчистка / погрузка и вывоз", "Экскаватор-погрузчик + самосвал / контейнер"
    if any(x in hay for x in ("перевозка песка","перевозка щебня","сыпучие материалы","самосвал","тонар")):
        return "Работа самосвала / перевозка сыпучих материалов", "Самосвал"
    if any(x in hay for x in ("производственные отходы","смешанные отходы")):
        return "Вывоз производственных / смешанных отходов", "Мультилифт / бункеровоз"
    return "", ""

def relevance_score(item):
    work, equipment = infer_work_equipment(item.get("title",""), item.get("description",""))
    if not work or not equipment:
        return 0, work, equipment
    score = 60
    if lead_class(item.get("title",""), item.get("description","")) == "HOT":
        score += 5
    loc = normalize(item.get("location",""))
    if "одинцов" in loc:
        score += 20
    elif geo_allowed(loc):
        score += 15
    else:
        return 0, work, equipment
    dt = parse_date(item.get("date",""))
    if dt:
        age = datetime.now(timezone.utc) - dt
        if age <= timedelta(days=1):
            score += 10
        elif age <= timedelta(days=3):
            score += 6
        elif age <= timedelta(days=7):
            score += 3
    else:
        score += 3
    if item.get("volume") and item.get("volume") != "-":
        score += 3
    if item.get("price") and "договор" not in str(item.get("price")).lower():
        score += 2
    return min(score,100), work, equipment

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

def parse_day_month(text):
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\b", text or "")
    if not m:
        return None
    now = datetime.now(timezone.utc)
    try:
        dt = datetime(now.year, int(m.group(2)), int(m.group(1)), tzinfo=timezone.utc)
        if dt - now > timedelta(days=30):
            dt = dt.replace(year=now.year - 1)
        return dt
    except ValueError:
        return None

def matched_geo(text):
    hay = normalize(text or "")
    for term in GEO_ALLOW:
        if normalize(term) in hay:
            return term
    return ""

def parse_p24_orders(page, source_label, source_url):
    lines = lines_from_html(page)
    out = []
    starts = [i for i, line in enumerate(lines) if re.search(r"\b№\d+\b", line)]
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 16)
        block_lines = lines[start:end]
        block = " ".join(block_lines)
        m_id = re.search(r"\b№(\d+)\b", block_lines[0])
        m_order = re.search(r"Заказ\s+([^:]{2,90}):\s*(.*)", block, re.I)
        if not m_id or not m_order:
            continue
        order_id = m_id.group(1)
        order_type = clean(m_order.group(1))
        desc = re.split(
            r"Адрес объекта:|Способ оплаты:|Бюджет:|Посмотреть контакты|Получать уведомления|Заказ просматривает",
            m_order.group(2),
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        if not desc:
            continue
        addr_m = re.search(
            r"Адрес объекта:\s*(.*?)(?:Способ оплаты:|Бюджет:|Посмотреть контакты|Получать уведомления|$)",
            block,
            re.I,
        )
        header_loc = re.sub(r"^\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}\s*", "", block_lines[0])
        header_loc = re.split(r"\s+№\d+", header_loc, maxsplit=1)[0].strip()
        location = clean(addr_m.group(1)) if addr_m else header_loc
        if not geo_allowed(location, order_type, desc):
            continue
        title = f"Заказ {order_type}: {desc[:140]}"
        if not relevant(title, desc):
            continue
        dt = parse_day_month(block_lines[0])
        if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
            continue
        budget_m = re.search(r"Бюджет:\s*([\d\s]+\s*руб\.?)", block, re.I)
        out.append({
            "request_id": "WEB-P24-" + order_id,
            "title": title[:250],
            "description": desc[:1800],
            "price": clean(budget_m.group(1)) if budget_m else "договорная",
            "date": dt.strftime("%Y-%m-%d") if dt else "актуальная заявка",
            "location": location[:250],
            "volume": extract_volume(desc) or "-",
            "url": source_url + "#order-" + order_id,
            "source": "Перевозка24",
            "priority": priority_for(title + " " + desc),
        })
    return out

def vezetvsem_listing_links(page, source_url):
    links = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
        url = urllib.parse.urljoin(source_url, html.unescape(href))
        if "vezetvsem.ru/" not in url:
            continue
        if re.search(r"_\d{6,}/?$", url) or re.search(r"/\d{6,}(?:[/?#]|$)", url):
            links.add(url.split("#", 1)[0])
    return sorted(links)[:80]

def parse_vezetvsem_order(url, source_label):
    page = fetch(url)
    lines = lines_from_html(page)
    text = " ".join(lines)
    low = text.lower()
    if "заказ не актуален" in low or "торги завершены" in low:
        return None
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    title = clean(h1.group(1)) if h1 else (lines[0] if lines else "Грузовой заказ")
    if not relevant(title, text):
        return None
    geo = matched_geo(text)
    if not geo:
        return None
    m_date = re.search(r"Дата размещения:\s*(\d{1,2}\.\d{1,2}\.20\d{2})", text, re.I)
    dt = None
    if m_date:
        try:
            dt = datetime.strptime(m_date.group(1), "%d.%m.%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
    if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
        return None
    desc_m = re.search(
        r"Информация о грузе(?:\s*№\s*\d+)?:?\s*(.*?)(?:Погрузка|Выгрузка|Ценовые предложения|Вопросы и обсуждения|$)",
        text,
        re.I,
    )
    description = clean(desc_m.group(1)) if desc_m else clean(text[:1800])
    m_id = re.search(r"(\d{6,})(?:/?$|[?#])", url)
    order_id = m_id.group(1) if m_id else hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return {
        "request_id": "WEB-VV-" + order_id,
        "title": title[:250],
        "description": description[:1800],
        "price": "договорная",
        "date": dt.strftime("%Y-%m-%d") if dt else "актуальная заявка",
        "location": geo[:250],
        "volume": extract_volume(description) or "-",
        "url": url,
        "source": "Везёт Всем",
        "priority": priority_for(title + " " + description),
    }

def parse_ddmmyy(text):
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2}|\d{2})\b", text or "")
    if not m:
        return None
    year = int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime(year, int(m.group(2)), int(m.group(1)), tzinfo=timezone.utc)
    except ValueError:
        return None

def relative_age_ok(text):
    t = normalize(text)
    m = re.search(r"\b(\d+)\s*дн", t)
    if m:
        return int(m.group(1)) <= RECENT_DAYS
    return True

def build_open_feed_item(source, source_url, key, title, description, date_text, location="", price="договорная", url=None):
    description = clean(description)[:1800]
    title = clean(title)[:250] or "Заявка на технику / перевозку"
    if not description:
        return None
    if not relevant(title, description):
        return None
    location = clean(location) or matched_geo(title + " " + description)
    if not geo_allowed(location, title, description):
        return None
    dt = parse_ddmmyy(date_text)
    if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
        return None
    if not relative_age_ok(date_text + " " + description):
        return None
    req_key = key or hashlib.sha1((source + "|" + title + "|" + description[:500]).encode("utf-8")).hexdigest()[:20]
    return {
        "request_id": "WEB-" + re.sub(r"[^A-Z0-9]+", "", source.upper().replace("Ё","Е"))[:10] + "-" + req_key,
        "title": title,
        "description": description,
        "price": clean(price)[:120] or "договорная",
        "date": dt.strftime("%Y-%m-%d") if dt else (clean(date_text) or "актуальная заявка"),
        "location": location[:250],
        "volume": extract_volume(description) or "-",
        "url": url or source_url,
        "source": source,
        "priority": priority_for(title + " " + description),
    }

def parse_dozzr(page, source_url):
    out = []
    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']*/catalog/item/(\d+)[^"\']*)["\'][^>]*>(.*?)</a>', page):
        href, item_id, raw = m.group(1), m.group(2), m.group(3)
        text = clean(raw)
        if len(text) < 20:
            continue
        text = re.sub(r"\s*Показать номер\s*$", "", text, flags=re.I)
        age_m = re.search(r"(\d+\s*(?:мин\.?|ч\.?|дн\.?)\s*назад)", text, re.I)
        age = age_m.group(1) if age_m else "свежая заявка"
        if age_m:
            text = text[:age_m.start()].strip()
        item = build_open_feed_item(
            "Dozzr", source_url, item_id, text[:180], text, age,
            location=matched_geo(text),
            url=urllib.parse.urljoin(source_url, href),
        )
        if item:
            out.append(item)
    return out

def parse_yellty(page, source_url):
    out = []
    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']*/zakazy/[^"\']+)["\'][^>]*>(.*?)</a>', page):
        href = html.unescape(m.group(1))
        title = clean(m.group(2))
        if "заказ" not in title.lower():
            continue
        start = m.start()
        end = min(len(page), start + 2600)
        context = clean(page[start:end])
        next_card = re.search(r"Свежие заказы|Заказ на ", context[80:], re.I)
        if next_card:
            context = context[:80 + next_card.start()]
        date_m = re.search(r"\b\d{1,2}\.\d{1,2}\.20\d{2}\b", context)
        date_text = date_m.group(0) if date_m else ""
        desc_m = re.search(r"Заказ на\s+[^.]{1,100}\.\s*Регион:\s*[^.]{1,100}\.\s*(.*?)(?:Договорная|\d{1,2}\.\d{1,2}\.20\d{2}|$)", context, re.I)
        description = clean(desc_m.group(1)) if desc_m else context
        key_m = re.search(r"([a-f0-9]{8})(?:[/?#]|$)", href, re.I)
        key = key_m.group(1) if key_m else hashlib.sha1(href.encode("utf-8")).hexdigest()[:16]
        item = build_open_feed_item(
            "Yellty", source_url, key, title, description, date_text,
            location=matched_geo(context),
            url=urllib.parse.urljoin(source_url, href),
        )
        if item:
            out.append(item)
    return out

def parse_spectex(page, source_url):
    lines = lines_from_html(page)
    out = []
    for i, line in enumerate(lines):
        m = re.search(r"(.+?)\s*•\s*(.+?)\s*•\s*(\d{1,2}\.\d{1,2}\.20\d{2})", line)
        if not m:
            continue
        title, location, date_text = m.group(1), m.group(2), m.group(3)
        block = " ".join(lines[i:i+28])
        if "открыта" not in block.lower() and "контакт" not in block.lower():
            continue
        item = build_open_feed_item(
            "Spectex", source_url, hashlib.sha1(block.encode("utf-8")).hexdigest()[:16],
            title, block, date_text, location=location, url=source_url,
        )
        if item:
            out.append(item)
    return out

def parse_beton24(page, source_url):
    lines = lines_from_html(page)
    out = []
    for i, line in enumerate(lines):
        if not line.lower().startswith("требуется:"):
            continue
        block_lines = lines[max(0, i-2):min(len(lines), i+10)]
        block = " ".join(block_lines)
        date_m = re.search(r"\b\d{1,2}\.\d{1,2}\.20\d{2}\b", block)
        date_text = date_m.group(0) if date_m else ""
        location = ""
        if date_m:
            for x in block_lines:
                if x == date_text:
                    continue
                if geo_allowed(x):
                    location = x
                    break
        title = lines[i-1] if i > 0 else "Заявка Бетон24"
        item = build_open_feed_item(
            "Бетон24", source_url, hashlib.sha1(block.encode("utf-8")).hexdigest()[:16],
            title, block, date_text, location=location, url=source_url,
        )
        if item:
            out.append(item)
    return out

def parse_exkavator(page, source_url):
    lines = lines_from_html(page)
    out = []
    for i, line in enumerate(lines):
        if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", line):
            continue
        block_lines = lines[max(0, i-5):min(len(lines), i+8)]
        block = " ".join(block_lines)
        title = ""
        for x in lines[i+1:min(len(lines), i+6)]:
            if len(x) > 12 and not re.fullmatch(r"[\d\s₽.,]+", x):
                title = x
                break
        if not title:
            title = "Заявка на аренду техники"
        location = ""
        for x in block_lines:
            if geo_allowed(x):
                location = x
                break
        item = build_open_feed_item(
            "Экскаватор Ру", source_url, hashlib.sha1(block.encode("utf-8")).hexdigest()[:16],
            title, block, line, location=location, url=source_url,
        )
        if item:
            out.append(item)
    return out

def parse_nerudonline(page, source_url):
    lines = lines_from_html(page)
    out = []
    for i, line in enumerate(lines):
        low = normalize(line)
        if not any(k in low for k in ("самосвал","перевоз","прием грунта","приемка грунта","грунт","песок","щебень")):
            continue
        block = " ".join(lines[max(0,i-3):min(len(lines),i+8)])
        if len(block) < 40:
            continue
        date_m = re.search(r"\b\d{1,2}\.\d{1,2}\.(?:20\d{2}|\d{2})\b", block)
        date_text = date_m.group(0) if date_m else "актуальная заявка"
        item = build_open_feed_item(
            "НерудОнлайн", source_url, hashlib.sha1(block.encode("utf-8")).hexdigest()[:16],
            line, block, date_text, location=matched_geo(block), url=source_url,
        )
        if item:
            out.append(item)
    return out[:80]

def vsempodryad_listing_links(page, source_url):
    links = set()
    for href in re.findall(r'href=["\']([^"\']*/request/[0-9a-fA-F-]{32,40}[^"\']*)["\']', page, re.I):
        url = urllib.parse.urljoin(source_url, html.unescape(href))
        url = url.split("?", 1)[0].split("#", 1)[0]
        links.add(url)
    return sorted(links)[:80]

def parse_vsempodryad_order(url, source_label):
    page = fetch(url, timeout=15)
    lines = lines_from_html(page)
    text = " ".join(lines)
    low = normalize(text)

    if "заказчик уже нашел исполнителей" in low or "заявка закрыта" in low:
        return None

    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    title = clean(h1.group(1)) if h1 else (lines[0] if lines else "Строительный заказ")

    description = section_after_label(
        lines,
        "Дополнительное описание",
        ("Предпочтительный способ связи", "Бюджет", "Заявка опубликована", "Представитель заказчика"),
        max_chars=2200,
    )
    if not description:
        description = text[:1800]

    location = section_after_label(
        lines,
        "Место работ",
        ("Дополнительное описание", "Предпочтительный способ связи", "Бюджет", "Заявка опубликована"),
        max_chars=350,
    )
    location = re.sub(r"^Image:\s*Маркер\s*", "", location, flags=re.I).strip()
    if not location:
        location = matched_geo(title + " " + description)

    if not relevant(title, description):
        return None
    if not geo_allowed(location, title, description):
        return None

    date_text = value_after_label(lines, "Заявка опубликована")
    dt = parse_ddmmyy(date_text)
    if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
        return None

    budget = value_after_label(lines, "Бюджет") or "договорная"
    m_id = re.search(r"/request/([0-9a-fA-F-]{32,40})", url)
    order_id = m_id.group(1) if m_id else hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]

    return {
        "request_id": "WEB-VP-" + order_id,
        "title": title[:250],
        "description": description[:1800],
        "price": budget[:120],
        "date": dt.strftime("%Y-%m-%d") if dt else (date_text or "актуальная заявка"),
        "location": location[:250],
        "volume": extract_volume(description) or "-",
        "url": url,
        "source": "Всем Подряд",
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
        if not geo_allowed(location, title, description):
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

    for source_label, source_url in P24_SOURCES:
        try:
            page = fetch(source_url, timeout=12)
            found = parse_p24_orders(page, source_label, source_url)
            print(f"P24_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Perevozka24 {source_label}: {exc}")

    vv_links = {}
    for source_label, source_url in VEZETVSEM_SOURCES:
        try:
            page = fetch(source_url, timeout=12)
            links = vezetvsem_listing_links(page, source_url)
            print(f"VEZETVSEM_SOURCE {source_label}: {len(links)} order links")
            for link in links:
                vv_links.setdefault(link, source_label)
        except Exception as exc:
            errors.append(f"VezetVsem listing {source_label}: {exc}")

    def fetch_vv_order(args):
        link, source_label = args
        return link, parse_vezetvsem_order(link, source_label)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_vv_order, item): item for item in vv_links.items()}
        for future in as_completed(futures):
            link, source_label = futures[future]
            try:
                _, item = future.result()
                if item:
                    candidates.append(item)
            except Exception as exc:
                errors.append(f"VezetVsem order {link}: {exc}")

    for source_label, source_url in DOZZR_SOURCES:
        try:
            page = fetch(source_url, timeout=15)
            found = parse_dozzr(page, source_url)
            print(f"DOZZR_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Dozzr {source_label}: {exc}")

    for source_label, source_url in NERUDONLINE_SOURCES:
        try:
            page = fetch(source_url, timeout=15)
            found = parse_nerudonline(page, source_url)
            print(f"NERUDONLINE_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"NerudOnline {source_label}: {exc}")

    for source_label, source_url in SPECTEX_SOURCES:
        try:
            page = fetch(source_url, timeout=20)
            found = parse_spectex(page, source_url)
            print(f"SPECTEX_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Spectex {source_label}: {exc}")

    for source_label, source_url in YELLTY_SOURCES:
        try:
            page = fetch(source_url, timeout=15)
            found = parse_yellty(page, source_url)
            print(f"YELLTY_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Yellty {source_label}: {exc}")

    for source_label, source_url in BETON24_SOURCES:
        try:
            page = fetch(source_url, timeout=15)
            found = parse_beton24(page, source_url)
            print(f"BETON24_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Beton24 {source_label}: {exc}")

    for source_label, source_url in EXKAVATOR_SOURCES:
        try:
            page = fetch(source_url, timeout=20)
            found = parse_exkavator(page, source_url)
            print(f"EXKAVATOR_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Exkavator {source_label}: {exc}")

    vp_links = {}
    for source_label, source_url in VSEMPODRYAD_SOURCES:
        try:
            page = fetch(source_url, timeout=15)
            links = vsempodryad_listing_links(page, source_url)
            print(f"VSEMPODRYAD_SOURCE {source_label}: {len(links)} order links")
            for link in links:
                vp_links.setdefault(link, source_label)
        except Exception as exc:
            errors.append(f"VsemPodryad listing {source_label}: {exc}")

    def fetch_vp_order(args):
        link, source_label = args
        return link, parse_vsempodryad_order(link, source_label)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_vp_order, item): item for item in list(vp_links.items())[:120]}
        for future in as_completed(futures):
            link, source_label = futures[future]
            try:
                _, item = future.result()
                if item:
                    candidates.append(item)
            except Exception as exc:
                errors.append(f"VsemPodryad order {link}: {exc}")

    unique = {}
    for item in candidates:
        unique[item["request_id"]] = item
    return list(unique.values()), errors

def send_webhook(item):
    comment = (
        f"Релевантность: {item.get('score',0)}/100\n"
        f"Тип лида: {item.get('lead_class','HOT')}\n"
        f"Работа ECOFLOT: {item.get('work','')}\n"
        f"Техника: {item.get('equipment','')}\n"
        f"Описание: {item['description']}\n"
        f"Цена: {item['price']}\n"
        f"Дата публикации: {item['date']}\n"
        f"Ссылка: {item['url']}\n"
        f"Excel: https://docs.google.com/spreadsheets/d/1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws/export?format=xlsx"
    )
    action_lines = [
        comment,
        f"▶ В работу: https://ecoflot.pro/?botAction=lead_work&rid={urllib.parse.quote(item['request_id'])}",
        f"✖ Не подходит: https://ecoflot.pro/?botAction=lead_lost&rid={urllib.parse.quote(item['request_id'])}",
        "📂 Открыть CRM: https://ecoflot.pro/#crm/leads",
    ]
    payload = {
        "type": "Интернет-заявка",
        "name": item["title"],
        "phone": "-",
        "wasteType": item.get("work") or "Работа ECOFLOT",
        "volume": item["volume"],
        "when": item["date"],
        "address": item["location"],
        "source": item["source"],
        "status": "Новая",
        "comment": "\n".join(action_lines)[:3500],
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

def send_no_results_message():
    payload = {
        "mode": "notify-only",
        "message": "Поиск интернет-заявок проведён, новых заявок не обнаружено",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=data,
        method="POST",
        headers={
            "User-Agent": "ECOFLOT-Internet-Leads/1.0",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        if not (200 <= r.status < 300):
            raise RuntimeError(f"Webhook HTTP {r.status}: {body[:300]}")
        resp = json.loads(body)
        if not resp.get("ok"):
            raise RuntimeError(f"Webhook error: {body[:300]}")

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    sheet_ids, sheet_links, sheet_sigs, sheet_ok = load_sheet_index()
    print(
        f"SHEET_DEDUPE: {'ok' if sheet_ok else 'fallback-to-state'}, "
        f"ids={len(sheet_ids)}, links={len(sheet_links)}, sigs={len(sheet_sigs)}"
    )

    candidates, errors = collect_candidates()
    for item in candidates:
        score, work, equipment = relevance_score(item)
        item["score"] = score
        item["work"] = work
        item["equipment"] = equipment
        item["lead_class"] = lead_class(item.get("title",""), item.get("description",""))
    candidates = [x for x in candidates if x.get("score",0) >= MIN_RELEVANCE_SCORE]
    candidates.sort(key=lambda x: (-x.get("score",0), x["source"], x["title"]))

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

    if sent_count == 0 and len(errors) < (
        len(NPD_SOURCES) + len(PROFI_SOURCES) + len(YOUDO_SOURCES)
        + len(P24_SOURCES) + len(VEZETVSEM_SOURCES)
        + len(DOZZR_SOURCES) + len(NERUDONLINE_SOURCES) + len(SPECTEX_SOURCES)
        + len(YELLTY_SOURCES) + len(BETON24_SOURCES) + len(EXKAVATOR_SOURCES)
        + len(VSEMPODRYAD_SOURCES)
    ):
        try:
            send_no_results_message()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"send no-results notice: {exc}")

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
