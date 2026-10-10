#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import sys
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from search_reliability import (load_json as reliable_load, atomic_json, finish_metrics,
    record_lead_result, delivery_confirmed, run_id, parse_deadline, tender_service_demand, MSK)

WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)
SHEET_ID = "1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws"
SHEET_NAME = "Заявки"
STATE_PATH = Path("internet_leads_state.json")
TELEGRAM_RETRY_QUEUE_PATH = Path("telegram_retry_queue.json")
MAX_SEND = int(os.environ.get("MAX_SEND", "50"))
RECENT_DAYS = int(os.environ.get("RECENT_DAYS", "7"))
MIN_RELEVANCE_SCORE = 60
SUPPRESS_NO_RESULTS = os.environ.get("SUPPRESS_NO_RESULTS", "0") == "1"

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
    ("Профи / земляные работы", "https://profi.ru/rabota/remont/zakazy-na-zemlyanye-raboty/"),
    ("Профи / расчистка участка", "https://profi.ru/rabota/remont/zakazy-na-raschistku-uchastka/"),
    ("Профи / демонтаж", "https://profi.ru/rabota/remont/zakazy-na-demontazh-kvartir/"),
    ("Профи / обслуживание септиков", "https://profi.ru/rabota/remont/zakazy-na-obsluzhivanie-septikov/"),
    ("Профи / установка септиков", "https://profi.ru/rabota/remont/zakazy-na-ustanovku-septikov/"),
]

# YouDo/Yandex/Avito are intentionally not treated as automatic demand feeds here.
# Their public pages currently mix provider profiles with service catalog content,
# which can create false leads. They can be added later only with a reliable public
# order feed or authenticated API.
YOUDO_SOURCES = []

# Перевозка24 исключена из базового ТЗ ECOFLOT.
P24_SOURCES = []

VEZETVSEM_SOURCES = [
    ("Везёт Всем / вывоз мусора", "https://www.vezetvsem.ru/listing/all/vyvoz_musora"),
    ("Везёт Всем / строительные грузы", "https://www.vezetvsem.ru/listing/moskva/stroitelnye_gruzy_i_oborudovanie"),
]

# Dozzr исключен из базового ТЗ ECOFLOT.
DOZZR_SOURCES = []

EXCLUDED_DOMAINS = (
    "dozzr.ru",
    "www.dozzr.ru",
    "perevozka24.ru",
    "www.perevozka24.ru",
)

# Источники, где данные заказчика скрыты до регистрации/авторизации/отклика.
REGISTRATION_GATED_DOMAINS = (
)

# Пользовательские исключения: эти площадки остаются в поиске даже если
# контакты заказчика раскрываются только после входа. В таком случае сама
# карточка заказа считается допустимым маршрутом контакта.
CONTACT_GATED_ALLOWED_DOMAINS = (
    "profi.ru", "www.profi.ru",
    "vezetvsem.ru", "www.vezetvsem.ru",
)

NERUDONLINE_SOURCES = [
    ("НерудОнлайн / работа для самосвалов", "https://nerudonline.ru/rabota/samosvaly"),
]

PROPOKUPKI_SOURCES = [
    ("ProPokupki / Московская область", "https://propokupki.ru/moskovskaya_oblast/uslugi_dlya_biznesa/"),
    ("ProPokupki / Москва", "https://propokupki.ru/moskva/uslugi_dlya_biznesa/"),
    ("ProPokupki / Калужская область", "https://propokupki.ru/kaluzhskaya_oblast/uslugi_dlya_biznesa/"),
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

SPCTEH_RU_SOURCES = [
    ("SPCTEH / заявки аренды", "https://spcteh.ru/bids/arenda/"),
]

RENTAG_SOURCES = [
    ("Rentag / биржа заявок", "https://rentag.ru/arenda-spectehniki/zayavki"),
]

SAMOSVAL_INFO_SOURCES = [
    ("Samosval.info / Московская область", "https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/moskovskaya-oblast/"),
    ("Samosval.info / Москва", "https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/moskva/"),
]

PROMINDEX_SOURCES = [
    ("Promindex / Москва / заявки", "https://promindex.ru/msk/orders"),
    ("Promindex / Московская область / заявки", "https://promindex.ru/moskovskaya-oblast/orders"),
]

SPECTEHINFO_SOURCES = [
    ("СПЕЦТЕХНИКА-ИНФО / Москва / самосвалы", "https://moskva.spectehinfo.ru/arenda/samosvaly"),
    ("СПЕЦТЕХНИКА-ИНФО / Московская область / самосвалы", "https://mosobl.spectehinfo.ru/arenda/samosvaly"),
    ("СПЕЦТЕХНИКА-ИНФО / Московская область / заявки по области", "https://mosobl.spectehinfo.ru/arenda/samosvaly/po_oblasti"),
    ("СПЕЦТЕХНИКА-ИНФО / Калужская область / самосвалы", "https://kaluga.spectehinfo.ru/arenda/samosvaly"),
]

# Дополнительный discovery-слой: поиск открытого спроса по всему публичному интернету,
# а не только по заранее известным площадкам. Кандидат все равно проходит географию,
# проверку намерения, открытого контакта, актуальности, скоринг и антидубли.
WEB_DISCOVERY_QUERIES = [
    '"нужен самосвал" Москва телефон',
    '"требуются самосвалы" "Московская область"',
    '"требуются самосвалы" "Калужская область"',
    '"нужен тонар" Москва',
    '"работа для самосвалов" "Московская область"',
    '"вывоз грунта" "нужен" Москва',
    '"перевозка ПГС" самосвал "Московская область"',
    '"нужен экскаватор" "Московская область"',
    '"нужен экскаватор-погрузчик" Москва',
    '"нужен контейнер" "вывоз мусора" Москва',
    '"требуется спецтехника" "Калужская область"',
    '"нужен ассенизатор" Москва',
    '"нужен илосос" "Московская область"',
    '"откачка ЖБО" "Калужская область" заказ',
    'site:propokupki.ru/moskovskaya_oblast "требуются самосвалы"',
    'site:propokupki.ru/moskovskaya_oblast "вывоз грунта" самосвалы',
    'site:propokupki.ru/moskovskaya_oblast "перевозка песка" самосвалы',
    'site:propokupki.ru/moskva "самосвал" "телефон"',
    'site:propokupki.ru/kaluzhskaya_oblast самосвал',
]

# Жесткая география базового ТЗ: только Москва, Московская область, Калужская область.
# Если географию нельзя подтвердить по тексту/полю адреса, заявка не выдается.
GEO_ALLOW = (
    # Москва
    "москва", "мск", "новая москва", "троицк", "щербинка", "московский",
    "коммунарка", "внуково", "кокошкино", "первомайское", "марушкинское",
    "филимонковское", "сосенское", "воскресенское", "десеновское",
    # Московская область
    "московская область", "подмосковье", "балаших", "подольск", "химк",
    "мытищ", "люберц", "королев", "королёв", "красногорск", "одинцов",
    "домодедов", "щелков", "щёлков", "серпухов", "коломн", "раменск",
    "электростал", "реутов", "долгопрудн", "пушкино", "жуковск", "ногинск",
    "богородск", "воскресенск", "лобня", "клин", "дмитров", "дубна",
    "чехов", "наро-фоминск", "наро фоминск", "егорьевск", "ступино",
    "павловский посад", "орехово-зуево", "орехово зуево", "сергиев посад",
    "истра", "звенигород", "апрелевка", "дзержинск", "котельник", "лыткарино",
    "видное", "ленинский округ", "краснознаменск", "нахабино", "дедовск",
    "кубинк", "голицыно", "большие вяземы", "малые вяземы", "барвиха",
    "горки-2", "горки 2", "горки-10", "горки 10", "рублев", "рублёв",
    "усово", "жуковка", "николина гора", "раздоры", "новоивановск",
    "новоивановский", "лесной городок", "фрязино", "ивантеевк", "красноармейск",
    "лосино-петровск", "лосино петровск", "ликino-дулево", "ликино-дулево",
    "куровское", "шатура", "розаль", "озеры", "озёры", "кашира", "зарайск",
    "луховицы", "протвино", "пущино", "электрогорск", "черноголовк",
    "солнечногорск", "талдом", "волоколамск", "можайск", "руза",
    "лотошино", "шаховская", "бронницы",
    # Калужская область
    "калужская область", "калуга", "обнинск", "балабанов", "боровск",
    "малоярослав", "белоусово", "ермолино", "жуков", "кременки", "таруса",
    "кондрово", "медынь", "юхнов", "мосальск", "мещовск", "сухиничи",
    "козельск", "сосенский", "людиново", "киров калуж", "спас-деменск",
    "спас деменск", "жиздра"
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
    "порубочные остатки", "подготовка площадки", "аренда спецтехники",
    "ассенизатор", "илосос", "жбо", "откачка жбо", "откачка септика",
    "разработка котлована", "благоустройство", "ликвидация свалки",
    "погрузка и вывоз", "содержание территории", "экскаватор", "погрузчик",
    "освободить участок", "освободить помещение", "освободить склад",
    "убрать после ремонта", "вывезти после ремонта", "очистить склад",
    "расчистить участок", "сломать гараж", "разобрать гараж",
    "нужен контейнер", "нужны контейнеры", "заказать контейнер",
    "нужен самосвал", "нужны самосвалы", "требуется самосвал",
    "требуются самосвалы", "ищу самосвал", "нужна спецтехника",
    "требуется спецтехника", "нужен экскаватор", "нужен погрузчик",
    "нужен манипулятор", "требуется манипулятор", "вывезти грунт",
    "вывезти мусор", "вывезти ветки", "убрать ветки",
    "перевозка пгс", "перевезти пгс", "асфальтовая крошка",
    "бой кирпича", "бой бетона", "работа для самосвалов",
    "работа для тонаров", "постоянка", "плечо", "рейсы самосвал",
)
DEMAND_INTENT = (
    "нужен", "нужна", "нужно", "нужны", "требуется", "требуются",
    "ищем", "ищу", "необходим", "необходимы", "заказ", "работа для",
    "кто вывезет", "нужно вывезти", "надо вывезти", "подрядчик",
)
COMMERCIAL_SIGNALS = (
    "постоянка", "постоянная работа", "до конца года", "на месяц",
    "на 2 месяца", "на 3 месяца", "долгосрочно", "24/7", "круглосуточно",
    "оплата ежедневно", "оплата раз в неделю", "безнал", "с ндс",
    "плечо", "рейс", "рейсы", "смена", "смены", "тонн", "м3", "м³",
)
EXCLUDE = (
    "медицинск", "ртут", "ламп",
    "аккумулятор", "шины", "пищев", "реактив",
    "вакансия", "резюме", "ищу работу", "продам самосвал", "продажа самосвала",
    "продам экскаватор", "продажа экскаватора", "продам контейнер",
    "продажа контейнера", "оказываем услуги", "предлагаем услуги",
    "сдаем в аренду", "сдаём в аренду", "наша компания оказывает",
    "перевозка24",
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

def fetch_relaxed_ssl(url: str, timeout=20) -> str:
    # Used only for explicitly known public read-only sources with broken certificate chains.
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
        },
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def _host_matches(url, domains):
    try:
        host = (urllib.parse.urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        host = ""
    return any(host == d or host.endswith("." + d) for d in domains)

def is_public_contact_url(url):
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").strip("/")
        query = urllib.parse.parse_qs(parsed.query or "")
    except Exception:
        return False
    if not host or not path:
        return False

    # Ссылки «поделиться» и служебные маршруты не являются контактом заявителя.
    if host in ("t.me", "telegram.me"):
        first = path.split("/", 1)[0].lower()
        return first not in ("share", "iv", "addstickers", "proxy", "socks")
    if host == "wa.me":
        return bool(re.fullmatch(r"\+?\d{7,15}", path))
    if host in ("api.whatsapp.com", "web.whatsapp.com"):
        phone = "".join(query.get("phone", []))
        return bool(re.sub(r"\D", "", phone))
    if host == "vk.me":
        return path.lower() not in ("share", "share.php")
    if host == "vk.com":
        first = path.split("/", 1)[0].lower()
        return first not in ("share.php", "share", "widget_share.php")
    if host == "max.ru":
        first = path.split("/", 1)[0].lower()
        return first not in ("share", "invite")
    return False

def extract_public_contact(text):
    raw = html.unescape(str(text or ""))
    # Маскированные контакты ("Телефон скрыт") не считаются доступным контактом.
    phone = ""
    phone_re = re.compile(
        r"(?<!\d)(?:\+?7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
    )
    m = phone_re.search(raw)
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 11:
            phone = "+7" + digits[-10:]

    contact_url = ""
    for m in re.finditer(r"https?://[^\s<>\]\[)]+", raw, re.I):
        candidate = m.group(0).rstrip(".,;:!?")
        if is_public_contact_url(candidate):
            contact_url = candidate
            break

    if not contact_url:
        email_m = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", raw, re.I)
        if email_m:
            contact_url = "mailto:" + email_m.group(0)

    if not contact_url:
        handle_m = re.search(r"(?<![\w.])@([A-Za-z0-9_]{5,32})\b", raw)
        if handle_m:
            contact_url = "https://t.me/" + handle_m.group(1)

    return phone, contact_url

def is_verified_order_route(url):
    """Known individual order/card routes that are usable contact paths."""
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        query = urllib.parse.parse_qs(parsed.query or "")
    except Exception:
        return False
    if not host or not path:
        return False
    if host.endswith("profi.ru"):
        return path.rstrip("/") == "/backoffice/n.php" and bool(query.get("o"))
    if host.endswith("spectehinfo.ru"):
        return bool(re.search(r"/zayavki/(?:arenda|uslugi)/[^/]+/b\d+/?$", path, re.I))
    if host.endswith("vezetvsem.ru"):
        return "/request/" in path.lower() or "/perevozka_" in path.lower()
    return False


def ensure_public_contact(item):
    source_url = str(item.get("url") or "")
    if _host_matches(source_url, REGISTRATION_GATED_DOMAINS):
        return False, "registration-gated"

    phone = str(item.get("phone") or "").strip()
    if len(normalize_phone(phone)) not in (10, 11):
        phone = ""
    contact_url = str(item.get("contact_url") or "").strip()
    if contact_url and not (contact_url.startswith("mailto:") or is_public_contact_url(contact_url)):
        contact_url = ""

    if not phone or not contact_url:
        found_phone, found_url = extract_public_contact(
            " ".join([
                str(item.get("title") or ""),
                str(item.get("description") or ""),
                str(item.get("contact_text") or ""),
            ])
        )
        if not phone:
            phone = found_phone
        if not contact_url:
            contact_url = found_url

    if not phone and not contact_url:
        # Individual order routes are acceptable contact paths. Profi/VezetVsem
        # are explicit user-approved contact-gated exceptions; Spectehinfo
        # individual request cards expose the customer-contact action publicly.
        if is_verified_order_route(source_url):
            contact_url = source_url
        elif _host_matches(source_url, CONTACT_GATED_ALLOWED_DOMAINS) and not is_listing_url_for_dedupe(item):
            contact_url = source_url
        else:
            return False, "no-public-contact-or-direct-order-link"

    item["phone"] = phone
    item["contact_url"] = contact_url
    return True, ""

def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "7" + digits[-10:]
    if len(digits) == 10:
        return "7" + digits
    return digits

def is_listing_url_for_dedupe(item):
    source = normalize(item.get("source") or "")
    url = str(item.get("url") or "").lower()
    if is_verified_order_route(url):
        return False
    if "профи" in source or "profi.ru/rabota/" in url or "profi.ru/registration/" in url:
        return True
    if "спецтехника-инфо" in source or "spectehinfo.ru/arenda/" in url:
        return True
    if "экскаватор ру" in source and "/exchange/rent/" in url:
        return True
    if "нерудонлайн" in source and "/rabota/samosvaly" in url:
        return True
    return False


def contact_dedupe_keys(item):
    return []  # Dedupe by request ID, direct order URL and content signature instead.

def parse_webhook_response(status, body, context="webhook"):
    if not (200 <= status < 300):
        raise RuntimeError(f"{context} HTTP {status}: {body[:500]}")
    try:
        resp = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context} returned non-JSON response: {body[:500]}") from exc
    if not isinstance(resp, dict) or not resp.get("ok"):
        raise RuntimeError(f"{context} returned ok=false: {body[:500]}")
    return resp

def _truthy_delivery(value):
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "ok", "sent", "delivered")
    return False

def telegram_delivery_confirmed(resp):
    return delivery_confirmed(resp)

def send_structured_cycle_report(message, cycle_key, report, webhook=WEBHOOK,
                                 user_agent="ECOFLOT-Cycle-Report/2.0", attempts=2):
    payload = json.dumps({
        "mode": "notify-only",
        "cycleKey": str(cycle_key or "").strip(),
        "message": str(message or ""),
        "report": report if isinstance(report, dict) else {},
    }, ensure_ascii=False).encode("utf-8")
    last_exc = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            req = urllib.request.Request(
                webhook,
                data=payload,
                method="POST",
                headers={
                    "User-Agent": user_agent,
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                resp = parse_webhook_response(r.status, body, "Telegram structured cycle report")
            if resp.get("ignored") is True:
                raise RuntimeError("STRUCTURED_REPORT_IGNORED")
            if not (telegram_delivery_confirmed(resp) or resp.get("telegramQueued") is True):
                raise RuntimeError("STRUCTURED_REPORT_NOT_ACCEPTED")
            print("TELEGRAM_STRUCTURED_REPORT_ACK:", json.dumps(resp, ensure_ascii=False)[:500])
            return resp
        except Exception as exc:
            last_exc = exc
            print(f"TELEGRAM_STRUCTURED_REPORT_RETRY {attempt}/{max(1, attempts)}: {exc}", file=sys.stderr)
            if attempt < max(1, attempts):
                time.sleep(min(3 * attempt, 6))
    raise last_exc


def send_notify_only(message, webhook=WEBHOOK, user_agent="ECOFLOT-Notify/2.0", attempts=1):
    payload = json.dumps({
        "mode": "notify-only",
        "message": message,
    }, ensure_ascii=False).encode("utf-8")
    last_exc = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            req = urllib.request.Request(
                webhook,
                data=payload,
                method="POST",
                headers={
                    "User-Agent": user_agent,
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                resp = parse_webhook_response(r.status, body, "Telegram notify-only")
                if not telegram_delivery_confirmed(resp):
                    raise RuntimeError("NOTIFY_DELIVERY_UNCONFIRMED")
                print(
                    "TELEGRAM_NOTIFY_ACK:",
                    json.dumps(resp, ensure_ascii=False)[:500],
                )
                return resp
        except Exception as exc:
            last_exc = exc
            print(
                f"TELEGRAM_NOTIFY_RETRY {attempt}/{max(1, attempts)}: {exc}",
                file=sys.stderr,
            )
            if attempt < max(1, attempts):
                time.sleep(attempt)
    raise RuntimeError(f"Telegram notify-only failed after {attempts} attempts: {last_exc}")

def queue_telegram_retry(message, source="ECOFLOT", request_id=""):
    try:
        if TELEGRAM_RETRY_QUEUE_PATH.exists():
            data = json.loads(TELEGRAM_RETRY_QUEUE_PATH.read_text("utf-8"))
        else:
            data = {"items": []}
    except Exception:
        data = {"items": []}

    items = data.setdefault("items", [])
    now = datetime.now(timezone.utc).isoformat()
    dedupe_key = request_id or hashlib.sha1(
        (source + "|" + message).encode("utf-8")
    ).hexdigest()[:24]

    for item in items:
        if item.get("key") == dedupe_key:
            item["message"] = message
            item["source"] = source
            item["updated_at"] = now
            item["attempts"] = int(item.get("attempts", 0))
            break
    else:
        items.append({
            "key": dedupe_key,
            "request_id": request_id,
            "source": source,
            "message": message,
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
        })

    data["items"] = items[-500:]
    TELEGRAM_RETRY_QUEUE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    print("TELEGRAM_RETRY_QUEUED:", source, dedupe_key)

def send_notify_reliable(
    message,
    webhook=WEBHOOK,
    user_agent="ECOFLOT-Notify/2.0",
    attempts=3,
    source="ECOFLOT",
    request_id="",
):
    # notify-only is for service messages only. Real lead/tender cards must
    # never be converted into plain text, otherwise inline status buttons
    # disappear and a visible duplicate may be created.
    if request_id:
        raise RuntimeError(
            "Plain-text Telegram fallback is forbidden for card request_id="
            + str(request_id)
        )
    try:
        cycle_key = (
            os.environ.get("ECOFLOT_CYCLE_KEY", "").strip()
            or datetime.now(MSK).strftime("%Y-%m-%d %H:%M") + " SERVICE"
        )
        report = {
            "status": "SERVICE_NOTICE",
            "searchMode": source,
            "new": 0,
            "accepted": 0,
            "errors": 0,
            "uncheckedSources": [],
            "message": message,
        }
        return send_structured_cycle_report(
            message,
            cycle_key,
            report,
            webhook=webhook,
            user_agent=user_agent,
            attempts=attempts,
        )
    except Exception:
        queue_telegram_retry(
            message,
            source=source,
            request_id=request_id,
        )
        raise

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
    dt = parse_date(date_text) or parse_profi_relative_date(date_text) or parse_deadline(date_text)
    if dt is None:
        return False
    age = datetime.now(timezone.utc) - dt
    return timedelta(0) <= age <= timedelta(days=RECENT_DAYS)

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
    # Жесткий геофильтр. Если площадка дала адрес/локацию, доверяем только этому полю.
    # К тексту заявки обращаемся лишь когда отдельного адреса нет.
    loc = normalize(location or "")
    if loc:
        return any(normalize(term) in loc for term in GEO_ALLOW)
    hay = normalize(" ".join([title or "", description or ""]))
    return any(normalize(term) in hay for term in GEO_ALLOW)

def relevant(title, description):
    hay = (title + " " + description).lower()
    if any(x in hay for x in EXCLUDE):
        return False

    # Reject labor/vacancy-style orders that only mention construction cleanup
    # as one of the worker duties. Keep them only when there is an explicit
    # ECOFLOT transport/equipment demand in the same order.
    labor_markers = (
        "ищу подсобного", "нужен подсобный", "подсобный рабочий",
        "разнорабочий", "разнорабочие", "официальное трудоустройство",
        "испытательный срок", "оплата за рабочий день", "человек на работу",
    )
    explicit_ecoflot_demand = (
        "нужен самосвал", "нужны самосвалы", "требуется самосвал",
        "требуются самосвалы", "нужен тонар", "требуется тонар",
        "нужен контейнер", "заказать контейнер", "вывоз мусора",
        "вывоз грунта", "вывезти мусор", "вывезти грунт",
        "перевозка песка", "перевозка щебня", "перевозка пгс",
        "нужен экскаватор", "требуется экскаватор", "нужен погрузчик",
        "ассенизатор", "илосос", "откачка септика",
    )
    if any(x in hay for x in labor_markers) and not any(x in hay for x in explicit_ecoflot_demand):
        return False

    return any(x in hay for x in POSITIVE)

def lead_class(title, description):
    hay = normalize((title or "") + " " + (description or ""))
    hot = (
        "вывоз", "контейнер", "самосвал", "тонар", "мусоровоз", "ломовоз",
        "бункеровоз", "мультилифт", "погрузка мусора", "погрузка грунта",
        "нужен экскаватор", "требуется экскаватор", "требуются самосвалы",
        "требуется самосвал", "нужен погрузчик", "требуется погрузчик",
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
    if any(x in hay for x in ("экскаватор", "погрузчик")):
        return "Земляные / погрузочные работы", "Экскаватор / погрузчик / экскаватор-погрузчик"
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
        elif age <= timedelta(days=14):
            score += 2
        elif age <= timedelta(days=30):
            score += 1
    else:
        score += 3
    if item.get("volume") and item.get("volume") != "-":
        score += 3
    if item.get("price") and "договор" not in str(item.get("price")).lower():
        score += 2
    commercial_text = normalize(
        " ".join([
            str(item.get("title") or ""),
            str(item.get("description") or ""),
        ])
    )
    commercial_hits = sum(1 for signal in COMMERCIAL_SIGNALS if normalize(signal) in commercial_text)
    if commercial_hits >= 4:
        score += 8
    elif commercial_hits >= 2:
        score += 5
    elif commercial_hits == 1:
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
        "tq": "select C,D,H,K,L,N where L is not null",
    })
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?{params}"
    ids, links, sigs = set(), set(), set()
    try:
        raw = fetch(url)
        m = re.search(r"google\.visualization\.Query\.setResponse\((.*)\);?\s*$", raw, re.S)
        payload = json.loads(m.group(1) if m else raw)
        if payload.get("status") != "ok" or "table" not in payload:
            raise RuntimeError("SHEET_DEDUPE_UNAVAILABLE")
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
            while len(vals) < 6:
                vals.append("")
            title, phone, address, comment, request_id, direct_link = vals[:6]
            if direct_link:
                links.add(direct_link)
            if request_id:
                ids.add(request_id)
            phone_key = normalize_phone(phone)
            if phone_key:
                links.add("contact:tel:" + phone_key)
            for link in re.findall(r"https?://[^\s]+", comment):
                clean_link = link.rstrip(").,;")
                links.add(clean_link)
                if is_public_contact_url(clean_link):
                    links.add("contact:url:" + clean_link.lower())
            desc_match = re.search(r"Описание:\s*(.*?)(?:\s+Цена:|\s+Дата публикации:|\s+Ссылка:|$)", comment, re.I)
            if desc_match:
                sigs.add(signature(title, address, desc_match.group(1)))
        return ids, links, sigs, True
    except Exception as exc:
        print("SHEET_DEDUPE_WARNING:", exc, file=sys.stderr)
        raise RuntimeError("SHEET_DEDUPE_UNAVAILABLE: refusing unsafe resend") from exc

def load_state():
    return reliable_load(STATE_PATH, {"sent": {}})

def save_state(state):
    sent = state.get("sent", {})
    if len(sent) > 5000:
        recent = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)[:5000]
        state["sent"] = dict(recent)
    atomic_json(STATE_PATH, state)

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

def parse_samosval_info(page, source_url):
    out = []
    for m in re.finditer(r"(?is)<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page):
        href = html.unescape(m.group(1))
        title = clean(m.group(2))
        if len(title) < 12:
            continue
        start = max(0, m.start() - 800)
        end = min(len(page), m.end() + 2200)
        context = clean(page[start:end])
        combined = (title + " " + context).strip()
        low = normalize(combined)
        if not any(x in low for x in ("требуются самосвалы","требуется самосвал","тонар","самосвал","вывоз грунта","перевозка грунта","песок","щебень","грунт")):
            continue
        if not geo_allowed("", title, context):
            continue
        published_m = re.search(r'(?i)дата публикации:\s*(\d{1,2}\.\d{1,2}\.20\d{2})', combined)
        if not published_m:
            continue
        date_text = published_m.group(1)
        link = urllib.parse.urljoin(source_url, href)
        key = hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]
        item = build_open_feed_item(
            "Samosval.info", source_url, key, title[:180], combined[:1800], date_text,
            location=matched_geo(combined),
            url=link,
        )
        if item:
            out.append(item)

    # Current Samosval.info listing pages often render order text as plain
    # blocks rather than clickable order titles. Fall back to ID-based blocks.
    if not out:
        lines = lines_from_html(page)
        positions = []
        for idx, line in enumerate(lines):
            m = re.match(r"^ID:\s*(\d+)\s*$", line, re.I)
            if m:
                positions.append((idx, m.group(1)))

        for pos, (idx, order_id) in enumerate(positions):
            next_idx = positions[pos + 1][0] if pos + 1 < len(positions) else min(len(lines), idx + 45)
            block_start = max(0, idx - 8)
            block_lines = lines[block_start:next_idx]
            block = " ".join(block_lines).strip()
            low = normalize(block)
            if "объявление было актуально до" in low or "было активно до" in low:
                continue
            if not any(x in low for x in ("требуются самосвалы","требуется самосвал","тонар","самосвал","вывоз грунта","перевозка грунта","песок","щебень","грунт")):
                continue
            if not geo_allowed("", block, block):
                continue

            title = ""
            for j in range(idx - 1, max(-1, idx - 10), -1):
                candidate = lines[j].strip()
                if "работа для" in normalize(candidate) and any(x in normalize(candidate) for x in ("самосвал", "тонар")):
                    title = candidate
                    break
            if not title:
                title = f"Заявка Samosval.info {order_id}"

            published_m = re.search(r"(?i)дата публикации:\s*(\d{1,2}\.\d{1,2}\.20\d{2})", block)
            if not published_m:
                continue
            date_text = published_m.group(1)
            link = "https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=" + order_id
            item = build_open_feed_item(
                "Samosval.info", source_url, order_id, title[:180], block[:1800], date_text,
                location=matched_geo(block),
                url=link,
            )
            if item:
                out.append(item)

    unique = {x["request_id"]: x for x in out}
    return list(unique.values())

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

def parse_spcteh_ru(page, source_url):
    lines = lines_from_html(page)
    out = []
    starts = [i for i, line in enumerate(lines) if normalize(line).startswith("требуется ")]
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 18)
        block_lines = lines[start:end]
        block = " ".join(block_lines)
        title = block_lines[0]
        submitted = ""
        m_date = re.search(r"Подана:\s*(\d{1,2}\.\d{1,2}\.20\d{2})", block, re.I)
        if m_date:
            submitted = m_date.group(1)
            dt = parse_ddmmyy(submitted)
            if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
                continue
        location = matched_geo(block)
        if not location:
            continue
        key = hashlib.sha1((title + "|" + location + "|" + submitted + "|" + block[:600]).encode("utf-8")).hexdigest()[:16]
        item = build_open_feed_item(
            "SPCTEH", source_url, key, title, block, submitted or "актуальная заявка",
            location=location, url=source_url,
        )
        if item:
            out.append(item)
    return out


def parse_rentag(page, source_url):
    lines = lines_from_html(page)
    out = []
    starts = [i for i, line in enumerate(lines) if normalize(line).startswith("заявка на аренду спецтехники в ")]
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 45)
        block_lines = lines[start:end]
        block = " ".join(block_lines)
        low = normalize(block)
        if "не активна" in low or "завершена" in low or "закрыта" in low:
            continue
        location = matched_geo(block)
        if not location:
            continue
        date_m = re.search(r"\b(\d{1,2}\.\d{1,2}\.\d{2,4})(?:,?\s+\d{1,2}:\d{2})?\b", block)
        date_text = date_m.group(1) if date_m else ""
        dt = parse_ddmmyy(date_text)
        if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
            continue
        id_m = re.search(r"(?<!\d)(\d{5,9})(?!\d)", block)
        order_id = id_m.group(1) if id_m else hashlib.sha1(block.encode("utf-8")).hexdigest()[:16]
        title = block_lines[0]
        item = build_open_feed_item(
            "Rentag", source_url, order_id, title, block, date_text or "актуальная заявка",
            location=location, url=source_url,
        )
        if item:
            out.append(item)
    return out


def parse_promindex(page, source_url):
    lines = lines_from_html(page)
    out = []
    seen = set()
    months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
        "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }
    for i, line in enumerate(lines):
        id_m = re.search(r"№\s*(\d{6,})", line)
        if not id_m:
            continue
        order_id = id_m.group(1)
        if order_id in seen:
            continue
        seen.add(order_id)
        block_lines = lines[max(0, i - 3):min(len(lines), i + 8)]
        block = " ".join(block_lines)
        if not relevant(line, block):
            continue
        location = matched_geo(block)
        if not location:
            continue
        dt = None
        date_text = ""
        dm = re.search(r"\b(\d{1,2})\s+([а-яё]+)\s+(20\d{2})\b", block.lower())
        if dm and dm.group(2) in months:
            try:
                dt = datetime(int(dm.group(3)), months[dm.group(2)], int(dm.group(1)), tzinfo=timezone.utc)
                date_text = dt.strftime("%Y-%m-%d")
            except ValueError:
                dt = None
        if dt and datetime.now(timezone.utc) - dt > timedelta(days=RECENT_DAYS):
            continue
        title = line
        item = {
            "request_id": "WEB-PROMINDEX-" + order_id,
            "title": clean(title)[:250],
            "description": clean(block)[:1800],
            "price": "договорная",
            "date": date_text or "актуальная заявка",
            "location": location[:250],
            "volume": extract_volume(block) or "-",
            "url": source_url,
            "source": "Promindex",
            "priority": priority_for(block),
        }
        out.append(item)
    return out[:100]


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
    if dt is None:
        return False
    return timedelta(0) <= datetime.now(timezone.utc) - dt <= timedelta(days=RECENT_DAYS)

def parse_profi_orders(page, source_label, source_url):
    out = []
    blocks = re.findall(
        r"(?is)<h3[^>]*>(.*?)</h3>(.*?)(?=<h3[^>]*>|</main>|<footer|$)",
        page,
    )
    for raw_title, raw_body in blocks:
        title = clean(raw_title)

        # Profi exposes a stable per-order response route in the "Откликнуться"
        # anchor. Keep it instead of replacing every order with the category URL.
        order_url = ""
        for href, anchor_html in re.findall(
            r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            raw_body,
        ):
            if "откликнуться" in normalize(clean(anchor_html)):
                candidate = urllib.parse.urljoin(source_url, html.unescape(href))
                if is_verified_order_route(candidate):
                    order_url = candidate
                    break

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
            "url": order_url or source_url,
            "contact_url": order_url,
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

def spectehinfo_activity_current(date_text):
    low = normalize(date_text)
    if any(marker in low for marker in (
        "сегодня", "завтра", "в течение недели", "на этой неделе",
        "срочно", "как можно скорее",
    )):
        return True
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(clean(date_text), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta = dt.date() - datetime.now(timezone.utc).date()
        return -1 <= delta.days <= RECENT_DAYS
    return False


def parse_spectehinfo_requests(page, source_label, source_url):
    out = []
    anchors = []
    for m in re.finditer(
        r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        page or "",
    ):
        anchor_text = clean(m.group(2))
        if "заявка на аренду" not in normalize(anchor_text):
            continue
        direct_url = urllib.parse.urljoin(source_url, html.unescape(m.group(1)))
        if not is_verified_order_route(direct_url):
            continue
        anchors.append((m.start(), m.end(), direct_url, anchor_text))

    for pos, (block_start, anchor_end, direct_url, anchor_text) in enumerate(anchors):
        block_end = anchors[pos + 1][0] if pos + 1 < len(anchors) else min(len(page), anchor_end + 5000)
        raw_block = page[block_start:block_end]
        # Stop before the site's "all requests"/provider listings when possible.
        stop = re.search(r'(?is)>\s*Все заявки\s*<|>\s*Добавить заявку\s*<|>\s*Свободен\s*<', raw_block)
        if stop:
            raw_block = raw_block[:stop.start()]
        block_lines = lines_from_html(raw_block)
        if not block_lines:
            continue
        block = " ".join(block_lines)
        if not relevant(anchor_text, block):
            continue

        location = ""
        date_text = ""
        for idx, line in enumerate(block_lines):
            low = normalize(line)
            if low.startswith("место работ"):
                location = clean(re.sub(r"(?i)^место работ\s*:\s*", "", line))
                if not location and idx + 1 < len(block_lines):
                    location = block_lines[idx + 1]
            elif low.startswith("дата начала работ"):
                date_text = clean(re.sub(r"(?i)^дата начала работ\s*:\s*", "", line))
                if not date_text and idx + 1 < len(block_lines):
                    date_text = block_lines[idx + 1]

        if not geo_allowed(location, anchor_text, block):
            continue
        if not spectehinfo_activity_current(date_text):
            continue

        bid = re.search(r"/(b\d+)/?$", urllib.parse.urlparse(direct_url).path, re.I)
        rid = "WEB-SPECTEHINFO-" + (
            bid.group(1).upper() if bid else hashlib.sha1(direct_url.encode("utf-8")).hexdigest()[:20]
        )
        out.append({
            "request_id": rid,
            "title": anchor_text[:250],
            "description": block[:1800],
            "contact_text": block,
            "contact_url": direct_url,
            "price": "договорная",
            "date": date_text,
            "activity_confirmed": True,
            "location": location or matched_geo(block),
            "volume": extract_volume(block) or "-",
            "url": direct_url,
            "source": source_label,
            "priority": priority_for(block),
        })
    return out

def discovery_result_urls(query):
    urls = []
    blocked_hosts = (
        "google.", "gstatic.", "youtube.", "ecoflot.pro",
        "bing.com", "duckduckgo.com", "live.com", "bingj.com",
        "microsoft.com", "msn.com", "softonic.com", "fandom.com",
        "facebook.com", "storeopeninghours.com", "mystore411.com",
        "apkpure.com", "perevozka24.ru", "dozzr.ru",
    )

    def add_url(raw):
        raw = html.unescape(str(raw or "")).replace("\\u003d", "=").replace("\\u0026", "&")
        raw = raw.rstrip(").,;")
        if raw.startswith("/url?q="):
            raw = urllib.parse.unquote(raw.split("/url?q=", 1)[1].split("&", 1)[0])
        if "uddg=" in raw:
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
                if qs.get("uddg"):
                    raw = qs["uddg"][0]
            except Exception:
                return
        try:
            parsed = urllib.parse.urlparse(raw)
            host = (parsed.hostname or "").lower()
        except Exception:
            return
        if not raw.startswith(("http://", "https://")):
            return
        if not host or any(x in host for x in blocked_hosts):
            return
        if raw not in urls:
            urls.append(raw)

    # Parse only actual search-result anchors, not every URL embedded in engine HTML.
    try:
        page = fetch("https://www.google.com/search?q=" + urllib.parse.quote(query), timeout=12, attempts=1)
        for href in re.findall(r'href=["\'](/url\?q=[^"\']+)["\']', page, re.I):
            add_url(href)
    except Exception:
        pass

    try:
        page = fetch("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query), timeout=12, attempts=1)
        for m in re.finditer(r'(?is)<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)["\']', page):
            add_url(m.group(1))
    except Exception:
        pass

    try:
        page = fetch("https://www.bing.com/search?q=" + urllib.parse.quote(query), timeout=12, attempts=1)
        for block in re.findall(r'(?is)<li[^>]+class=["\'][^"\']*b_algo[^"\']*["\'][^>]*>(.*?)</li>', page):
            m = re.search(r'(?is)<a[^>]+href=["\'](https?://[^"\']+)["\']', block)
            if m:
                add_url(m.group(1))
    except Exception:
        pass

    return urls[:25]

def discovery_activity_context(text):
    hay = str(text or "")
    low = normalize(hay)
    positions = []
    for marker in DEMAND_INTENT:
        pos = low.find(normalize(marker))
        if pos >= 0:
            positions.append(pos)
    if not positions:
        return hay[:3500]
    pos = min(positions)
    start = max(0, pos - 1400)
    end = min(len(hay), pos + 2600)
    return hay[start:end]

def extract_publication_date(page):
    patterns = [
        r'(?is)(?:article:published_time|datePublished|datepublished)[^>]{0,180}(20\d{2}-\d{2}-\d{2})',
        r'(?is)<time[^>]+datetime=["\'](20\d{2}-\d{2}-\d{2})',
        r'(?i)\b(20\d{2}-\d{2}-\d{2})\b',
    ]
    for pattern in patterns:
        m = re.search(pattern, page or "")
        if m:
            return m.group(1)
    return ""

def undated_activity_confirmed(text):
    low = normalize(text)
    markers = (
        "сегодня", "вчера", "срочно", "прямо сейчас", "актуально",
        "требуются", "нужны машины", "добираем машины", "машин не хватает",
        "постоянная работа", "долгосрочно", "работа 24 7", "до конца месяца",
    )
    return any(normalize(x) in low for x in markers)

def parse_discovery_candidate(url):
    page = fetch(url, timeout=15)
    text = clean(page)
    low = normalize(text)
    if not text or not any(normalize(marker) in low for marker in DEMAND_INTENT):
        return None
    if not relevant(text[:250], text):
        return None

    publication_date = extract_publication_date(page)
    if publication_date:
        if not is_recent(publication_date):
            return None
    elif not undated_activity_confirmed(text):
        # Без подтвержденной даты нужен отдельный признак, что спрос живой сейчас.
        return None

    location = matched_geo(text)
    if not location:
        return None
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    title = clean(h1.group(1)) if h1 else clean(re.sub(r"(?is).*?<title[^>]*>(.*?)</title>.*", r"\1", page))
    title = (title or text[:180])[:250]

    # Контакт ищем только рядом с текстом спроса, а не в footer/support площадки.
    demand_context = discovery_activity_context(text)
    phone, contact_url = extract_public_contact(demand_context)
    rid = "WEB-DISC-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return {
        "request_id": rid,
        "title": title,
        "description": demand_context[:1800],
        "contact_text": demand_context,
        "phone": phone,
        "contact_url": contact_url,
        "price": "договорная",
        "date": publication_date or "актуальность подтверждена текстом",
        "location": location,
        "volume": extract_volume(demand_context) or "-",
        "url": url,
        "source": "Web Discovery / " + (urllib.parse.urlparse(url).hostname or "web"),
        "priority": priority_for(demand_context),
    }

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

    for source_label, source_url in SAMOSVAL_INFO_SOURCES:
        try:
            page = fetch(source_url, timeout=20)
            found = parse_samosval_info(page, source_url)
            print(f"SAMOSVAL_INFO_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Samosval.info {source_label}: {exc}")

    for source_label, source_url in YELLTY_SOURCES:
        try:
            page = fetch(source_url, timeout=15)
            found = parse_yellty(page, source_url)
            print(f"YELLTY_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Yellty {source_label}: {exc}")

    for source_label, source_url in SPCTEH_RU_SOURCES:
        try:
            page = fetch(source_url, timeout=20)
            found = parse_spcteh_ru(page, source_url)
            print(f"SPCTEH_RU_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"SPCTEH {source_label}: {exc}")

    for source_label, source_url in RENTAG_SOURCES:
        try:
            try:
                page = fetch(source_url, timeout=20)
            except ssl.SSLCertVerificationError:
                page = fetch_relaxed_ssl(source_url, timeout=20)
                print(f"RENTAG_SSL_FALLBACK {source_label}: public read-only fetch")
            found = parse_rentag(page, source_url)
            print(f"RENTAG_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Rentag {source_label}: {exc}")

    for source_label, source_url in PROMINDEX_SOURCES:
        try:
            page = fetch(source_url, timeout=20)
            found = parse_promindex(page, source_url)
            print(f"PROMINDEX_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Promindex {source_label}: {exc}")

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

    for source_label, source_url in SPECTEHINFO_SOURCES:
        try:
            page = fetch(source_url, timeout=20)
            found = parse_spectehinfo_requests(page, source_label, source_url)
            print(f"SPECTEHINFO_SOURCE {source_label}: {len(found)} candidate blocks")
            candidates.extend(found)
        except Exception as exc:
            errors.append(f"Spectehinfo {source_label}: {exc}")

    discovered_urls = {}
    for query in WEB_DISCOVERY_QUERIES:
        try:
            urls = discovery_result_urls(query)
            print(f"WEB_DISCOVERY_QUERY {query}: {len(urls)} urls")
            for url in urls:
                discovered_urls[url] = query
        except Exception as exc:
            errors.append(f"Web discovery {query}: {exc}")

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(parse_discovery_candidate, url): url for url in list(discovered_urls)[:80]}
        for future in as_completed(futures):
            url = futures[future]
            try:
                item = future.result()
                if item:
                    candidates.append(item)
            except Exception as exc:
                errors.append(f"Web discovery page {url}: {exc}")

    # Жесткий фильтр исключенных доменов применяется ко всем найденным кандидатам,
    # независимо от того, каким источником или парсером они были обнаружены.
    filtered_candidates = []
    for item in candidates:
        item_url = str(item.get("url") or "").lower()
        if any(domain in item_url for domain in EXCLUDED_DOMAINS):
            print("EXCLUDED_DOMAIN:", item.get("request_id"), item_url)
            continue
        filtered_candidates.append(item)
    candidates = filtered_candidates

    unique = {}
    for item in candidates:
        unique[item["request_id"]] = item
    return list(unique.values()), errors

def human_lead_title(item):
    work = clean(item.get("work") or "")
    location = clean(item.get("location") or "")
    volume = clean(item.get("volume") or "")
    original = clean(item.get("title") or "")
    generic_tokens = (
        "мастер", "специалист", "дизайнер", "демонтажник", "разнорабоч",
        "telegram-заявка", "max-заявка", "заявка на технику",
    )
    if work and (not original or any(x in normalize(original) for x in generic_tokens)):
        title = work
        if location:
            title += " — " + location
        if volume and volume != "-":
            title += ", " + volume
        return title[:250]
    return original[:250] or ((work or "Заявка ECOFLOT") + ((" — " + location) if location else ""))[:250]


def propokupki_listing_links(page, source_url):
    out = []
    for href, raw_title in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page):
        title = clean(raw_title)
        low = normalize(title)
        if not any(x in low for x in (
            "самосвал", "тонар", "спецтех", "экскаватор", "погрузчик",
            "вывоз грунта", "вывоз мусора", "грунт", "щебень", "песок"
        )):
            continue
        url = urllib.parse.urljoin(source_url, html.unescape(href))
        if "/uslugi_dlya_biznesa/" not in url:
            continue
        if url not in out:
            out.append(url)
    return out[:80]


def parse_propokupki_order(url):
    page = fetch(url, timeout=20)
    lines = lines_from_html(page)
    text = " ".join(lines)
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    title = clean(h1.group(1)) if h1 else ""
    if not title:
        title = next((x for x in lines if len(x) > 20), "Заявка на самосвалы / спецтехнику")
    if not relevant(title, text):
        return None

    location = matched_geo(title + " " + text)
    if not location:
        return None

    phone, contact_url = extract_public_contact(text)
    if not phone:
        return None

    date_text = ""
    exact_dates = re.findall(r"(?<!\d)(\d{1,2}[./-]\d{1,2}[./-](?:20)?\d{2})(?!\d)", title + " " + text)
    for raw in exact_dates:
        normalized_date = raw.replace("/", ".").replace("-", ".")
        parts = normalized_date.split(".")
        if len(parts) == 3 and len(parts[2]) == 2:
            normalized_date = parts[0] + "." + parts[1] + ".20" + parts[2]
        try:
            dt = datetime.strptime(normalized_date, "%d.%m.%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age = datetime.now(timezone.utc) - dt
        if timedelta(days=-1) <= age <= timedelta(days=RECENT_DAYS):
            date_text = dt.strftime("%d.%m.%Y")
            break
    if not date_text:
        return None

    req_key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    item = {
        "request_id": "WEB-PROPOKUPKI-" + req_key,
        "title": title[:250],
        "description": text[:1800],
        "contact_text": text,
        "phone": phone,
        "contact_url": contact_url,
        "price": "договорная",
        "date": date_text,
        "location": location,
        "volume": extract_volume(text) or "-",
        "url": url,
        "source": "ProPokupki.ru",
        "priority": priority_for(title + " " + text),
    }
    return item


def internet_quality_ready(item):
    title = clean(item.get("title") or "")
    source = normalize(item.get("source") or "")
    url = str(item.get("url") or "").strip()
    date_text = clean(item.get("date") or "")
    if len(title) < 12 or title.lower() in ("telegram-заявка", "заявка на технику / перевозку", "актуальная заявка"):
        return False, "unclear-title"
    if not url.startswith(("http://", "https://")):
        return False, "no-direct-link"
    if date_text.lower() in ("", "-", "актуальная заявка"):
        return False, "no-confirmed-date"
    if not is_recent(date_text) and not item.get("activity_confirmed"):
        return False, "date-unverified-stale-or-future"
    # Contact validation follows date verification.
    ok, reason = ensure_public_contact(item)
    if not ok:
        return False, reason
    return True, ""


def send_webhook(item):
    item["title"] = human_lead_title(item)
    comment = (
        f"Релевантность: {item.get('score',0)}/100\n"
        f"Тип лида: {item.get('lead_class','HOT')}\n"
        f"Работа ECOFLOT: {item.get('work','')}\n"
        f"Техника: {item.get('equipment','')}\n"
        f"Описание: {item['description']}\n"
        f"Цена: {item['price']}\n"
        f"Дата/актуальность: {item['date']}\n"
        f"Телефон: {item.get('phone') or '-'}\n"
        f"Контакт: {item.get('contact_url') or '-'}\n"
        f"Ссылка: {item['url']}\n"
        f"Excel: https://docs.google.com/spreadsheets/d/1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws/export?format=xlsx"
    )
    rid = urllib.parse.quote(item["request_id"])
    action_lines = [
        comment,
        f"🆕 Новая: https://ecoflot.pro/?botAction=lead_new&rid={rid}",
        f"▶ В работе: https://ecoflot.pro/?botAction=lead_work&rid={rid}",
        f"🧮 Расчёт / КП: https://ecoflot.pro/?botAction=lead_quote&rid={rid}",
        f"🤝 Согласование: https://ecoflot.pro/?botAction=lead_approval&rid={rid}",
        f"📅 Запланирована: https://ecoflot.pro/?botAction=lead_scheduled&rid={rid}",
        f"🚛 Выполняется: https://ecoflot.pro/?botAction=lead_executing&rid={rid}",
        f"✅ Выполнена: https://ecoflot.pro/?botAction=lead_done&rid={rid}",
        f"✖ Отказ: https://ecoflot.pro/?botAction=lead_lost&rid={rid}",
        "📂 Открыть CRM: https://ecoflot.pro/#crm/leads",
    ]
    payload = {
        "type": "Интернет-заявка",
        "name": item["title"],
        "phone": item.get("phone") or "-",
        "wasteType": item.get("work") or "Работа ECOFLOT",
        "volume": item["volume"],
        "when": item["date"],
        "address": item["location"],
        "source": item["source"],
        "link": item["url"],
        "status": "Новая",
        "comment": "\n".join(action_lines)[:3500],
        "requestId": item["request_id"],
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=data,
        method="POST",
        headers={"User-Agent": "ECOFLOT-Internet-Leads/2.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        resp = parse_webhook_response(r.status, body, "Internet lead webhook")
    record_lead_result(item["request_id"], resp, item.get("source", "Internet Leads"))

    if not telegram_delivery_confirmed(resp):
        # Search success and Telegram delivery are separate stages.
        # Never turn a valid search result into a search failure because delivery is pending.
        print("TELEGRAM_DELIVERY_PENDING: queued/reconcile required for current cycle", flush=True)

def send_no_results_message():
    return send_notify_reliable(
        "♻️ ECOFLOT Internet Leads: поиск проведён, новых заявок не обнаружено",
        webhook=WEBHOOK,
        user_agent="ECOFLOT-Internet-Leads/2.0",
        source="Internet Leads",
    )

def main():
    state = load_state()
    sent = state.setdefault("sent", {})
    legacy_local = state.get("last_run", {}).get("metrics_version") != 2
    sheet_ids, sheet_links, sheet_sigs, sheet_ok = load_sheet_index()
    print(
        f"SHEET_DEDUPE: {'ok' if sheet_ok else 'fallback-to-state'}, "
        f"ids={len(sheet_ids)}, links={len(sheet_links)}, sigs={len(sheet_sigs)}"
    )

    candidates, errors = collect_candidates()
    print(f"FILTER_STAGE raw_unique_candidates={len(candidates)}")
    # Финальный географический предохранитель перед скорингом и отправкой.
    candidates = [
        x for x in candidates
        if geo_allowed(x.get("location",""), x.get("title",""), x.get("description",""))
    ]

    print(f"FILTER_STAGE after_geo={len(candidates)}")
    # Обязательное правило контактности: показываем только заявки, где
    # уже есть открытый телефон или прямая публичная ссылка на контакт.
    contact_ready = []
    for item in candidates:
        ok, reason = ensure_public_contact(item)
        if ok:
            contact_ready.append(item)
        else:
            print("EXCLUDED_CONTACT:", reason, item.get("source"), item.get("request_id"), item.get("url"))
    candidates = contact_ready
    print(f"FILTER_STAGE after_contact={len(candidates)}")

    quality_ready = []
    for item in candidates:
        ok, reason = internet_quality_ready(item)
        if ok:
            quality_ready.append(item)
        else:
            print("EXCLUDED_QUALITY:", reason, item.get("source"), item.get("request_id"), item.get("url"))
    candidates = quality_ready
    print(f"FILTER_STAGE after_quality={len(candidates)}")

    for item in candidates:
        score, work, equipment = relevance_score(item)
        item["score"] = score
        item["work"] = work
        item["equipment"] = equipment
        item["lead_class"] = lead_class(item.get("title",""), item.get("description",""))
    candidates = [x for x in candidates if x.get("score",0) >= MIN_RELEVANCE_SCORE]
    print(f"FILTER_STAGE after_score={len(candidates)}")
    candidates.sort(key=lambda x: (-x.get("score",0), x["source"], x["title"]))

    new_items = []
    local_seen = set()
    for item in candidates:
        request_id = item["request_id"]
        sig = signature(item["title"], item["location"], item["description"])
        url_is_duplicate = (not is_listing_url_for_dedupe(item)) and item["url"] in sheet_links
        if request_id in sheet_ids or url_is_duplicate or sig in sheet_sigs:
            continue
        if any(key in sheet_links for key in contact_dedupe_keys(item)):
            continue
        if (not legacy_local and request_id in sent) or request_id in local_seen:
            continue
        local_seen.add(request_id)
        new_items.append(item)

    print(f"FILTER_STAGE after_dedupe={len(new_items)}")
    sent_count = 0
    for item in new_items[:MAX_SEND]:
        try:
            send_webhook(item)
            sent[item["request_id"]] = datetime.now(timezone.utc).isoformat()
            sheet_ids.add(item["request_id"])
            if not is_listing_url_for_dedupe(item):
                sheet_links.add(item["url"])
            for key in contact_dedupe_keys(item):
                sheet_links.add(key)
            sheet_sigs.add(signature(item["title"], item["location"], item["description"]))
            sent_count += 1
            save_state(state)
            print("ACCEPTED:", item["source"], item["request_id"], item["title"][:140], item["location"])
        except Exception as exc:
            errors.append(f"send {item['request_id']}: {exc}")

    if not SUPPRESS_NO_RESULTS and sent_count == 0 and len(errors) < (
        len(NPD_SOURCES) + len(PROFI_SOURCES) + len(YOUDO_SOURCES)
        + len(P24_SOURCES) + len(VEZETVSEM_SOURCES)
        + len(DOZZR_SOURCES) + len(NERUDONLINE_SOURCES) + len(PROPOKUPKI_SOURCES) + len(SPECTEX_SOURCES)
        + len(YELLTY_SOURCES) + len(BETON24_SOURCES) + len(EXKAVATOR_SOURCES)
        + len(VSEMPODRYAD_SOURCES) + len(SPCTEH_RU_SOURCES)
        + len(RENTAG_SOURCES) + len(PROMINDEX_SOURCES) + len(SAMOSVAL_INFO_SOURCES)
        + len(SPECTEHINFO_SOURCES) + len(WEB_DISCOVERY_QUERIES)
    ):
        try:
            send_no_results_message()
            print("NO_RESULTS_NOTICE_SENT")
        except Exception as exc:
            errors.append(f"send no-results notice: {exc}")

    state["last_run"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cycleKey": os.environ.get("ECOFLOT_CYCLE_KEY", "").strip(),
        "run_id": run_id(),
        "error_details": errors,
        "candidates": len(candidates),
        "duplicates_local": len(candidates) - len(new_items),
        "deferred": max(0, len(new_items) - MAX_SEND),
        "new": len(new_items),
        "sent": sent_count,
        "errors": len(errors),
    }
    finish_metrics(state)
    save_state(state)
    print(
        f"Internet candidates: {len(candidates)}, new after dedupe: {len(new_items)}, "
        f"sent: {sent_count}, errors: {len(errors)}"
    )
    for error in errors:
        print("ERROR:", error, file=sys.stderr)

    if errors:
        print(f"INTERNET_WARNINGS: {len(errors)} source/page errors; cycle continues", file=sys.stderr)

if __name__ == "__main__":
    main()
