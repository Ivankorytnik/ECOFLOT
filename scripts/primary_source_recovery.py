"""Recover direct demand from ProPokupki and avoid cross-order Samosval contacts.

This module augments the existing collector; no credentials, publication or
Telegram dispatch take place here.
"""
import hashlib
import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone


def collect_propokupki(m):
    sources = list(dict.fromkeys(m.PROPOKUPKI_SOURCES + [
        ("ProPokupki / Московская область",
         "https://propokupki.ru/moskovskaya_oblast/uslugi_dlya_biznesa/")
    ]))
    results, errors, discovered = [], [], {}
    for label, source in sources:
        try:
            page = m.fetch(source, timeout=12, attempts=1)
            for href, raw in re.findall(r"""(?is)<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)</a>""", page):
                title = m.normalize(m.clean(raw))
                if not any(v in title for v in ("самосвал", "тонар", "спецтех", "экскаватор", "вывоз мусора", "перевозка песка")):
                    continue
                url = urllib.parse.urljoin(source, html.unescape(href))
                path = urllib.parse.urlparse(url)
                if (path.scheme == "https" and
                    m._host_matches(url, ("propokupki.ru",)) and
                    "/uslugi_dlya_biznesa/" in path.path and
                    path.path.endswith(".html")):
                    discovered[url] = label
        except Exception as exc:
            errors.append("ProPokupki " + label + ": " + str(exc)[:180])
    def read_card(url):
        page = m.fetch(url, timeout=12, attempts=1)
        heading = re.search(r"(?is)<h1\\b[^>]*>(.*?)</h1>", page)
        if not heading:
            return None
        title = m.clean(heading.group(1))
        fragment = page[heading.start():heading.start() + 12000]
        end = re.search(r"(?is)<footer\\b|похожие объявления|другие объявления", fragment)
        if end:
            fragment = fragment[:end.start()]
        lines = m.lines_from_html(fragment)
        text = " ".join(lines)
        if (not m.relevant(title, text) or
            "условия: предложение услуги" in m.normalize(text)):
            return None
        if not any(t in m.normalize(text) for t in (
            "требуются самосвалы", "требуется самосвал", "нужен самосвал",
            "требуются тонары", "ищем перевозчиков", "вывоз грунта",
            "вывоз мусора", "перевозка песка", "перевозка щебня")):
            return None
        location = m.matched_geo(title + " " + text)
        if not location:
            return None
        # Phone must occur close to the advertisement, not in related cards.
        header = " ".join(lines[:30])
        phone, _ = m.extract_public_contact(header)
        if not phone:
            return None
        date = ""
        for raw in re.findall(r"(?<!\\d)(\\d{1,2}[./-]\\d{1,2}[./-](?:20)?\\d{2})(?!\\d)", title + " " + text[:1400]):
            parts = raw.replace("/", ".").replace("-", ".").split(".")
            if len(parts[-1]) == 2:
                parts[-1] = "20" + parts[-1]
            try:
                dt = datetime.strptime(".".join(parts), "%d.%m.%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if timedelta(days=-1) <= datetime.now(timezone.utc) - dt <= timedelta(days=m.RECENT_DAYS):
                date = dt.strftime("%d.%m.%Y")
                break
        if not date:
            return None
        return dict(
            request_id="WEB-PROPOKUPKI-" + hashlib.sha1(url.encode()).hexdigest()[:20],
            title=title[:250], description=text[:1800], contact_text=header,
            contact_evidence_required=True, phone=phone,
            date=date, location=location, volume=m.extract_volume(text) or "-",
            url=url, source="ProPokupki.ru", price="договорная",
            priority=m.priority_for(text))
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {pool.submit(read_card, url): url for url in list(discovered)[:50]}
        for future in as_completed(jobs):
            try:
                item = future.result()
                if item:
                    results.append(item)
            except Exception as exc:
                errors.append("ProPokupki card " + jobs[future] + ": " + str(exc)[:180])
    return results, errors
