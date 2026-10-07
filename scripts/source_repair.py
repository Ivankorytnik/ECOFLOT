"""Bounded, read-only source parsing. No network access at import time.

Login/CAPTCHA/unknown responses are not evidence of an empty search.
Only URLs actually present in result anchors are followed. No access bypass.
"""
from __future__ import annotations
import base64
import html
import ipaddress
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, parse_qs, quote, unquote
from zoneinfo import ZoneInfo

ENGINES = {
    'google': 'https://www.google.com/search?q=',
    'duckduckgo': 'https://html.duckduckgo.com/html/?q=',
    'bing': 'https://www.bing.com/search?q=',
}
BLOCKED = ('ecoflot.pro', 'dozzr.ru', 'perevozka24.ru', 'google.com',
           'gstatic.com', 'duckduckgo.com', 'bing.com', 'bingj.com', 'microsoft.com')
PRIMARY_TENDER_HOSTS = ('zakupki.gov.ru', 'roseltorg.ru', 'rts-tender.ru',
                       'sberbank-ast.ru', 'b2b-center.ru', 'fabrikant.ru',
                       'etpgpb.ru', 'zakupki.mos.ru', 'easuz.mosreg.ru')

class UnverifiedSearch(RuntimeError):
    pass


def host_is(host, domains):
    return any(host == d or host.endswith('.'+d) for d in domains)


def public_url(raw):
    """Reject local addresses, credentials and non-HTTP links before fetching."""
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or '').lower()
        if parts.scheme not in ('https', 'http') or not host or parts.username or parts.password:
            return ''
        if parts.port not in (None, 80, 443) or '.' not in host or host.endswith(('.local', '.internal')):
            return ''
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                return ''
        except ValueError:
            pass
        if len(raw) > 4096 or any(ord(c) < 32 for c in raw) or host_is(host, BLOCKED):
            return ''
        return raw
    except (ValueError, TypeError):
        return ''


def unwrap_result(raw, engine):
    raw = html.unescape(str(raw or '')).strip()
    parts = urlsplit(urljoin(ENGINES[engine], raw))
    query = parse_qs(parts.query)
    host = (parts.hostname or '').lower()
    if host_is(host, ('google.com',)) and parts.path == '/url':
        raw = (query.get('q') or query.get('url') or [''])[0]
    elif host_is(host, ('duckduckgo.com',)) and query.get('uddg'):
        raw = query['uddg'][0]
    elif host_is(host, ('bing.com',)) and query.get('u'):
        encoded = query['u'][0]
        if encoded.startswith('a1'):
            try:
                payload = encoded[2:]
                raw = base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)).decode('utf-8')
            except (ValueError, UnicodeError):
                return ''
        else:
            raw = encoded
    elif raw.startswith('//'):
        raw = 'https:'+raw
    return public_url(raw)


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None
        self.bing_result = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'li':
            self.bing_result = 'b_algo' in attrs.get('class','').split()
        if tag == 'a':
            self.current = {'href': attrs.get('href',''), 'class': attrs.get('class',''),
                            'bing': self.bing_result, 'h3': False, 'text': ''}
        elif tag == 'h3' and self.current is not None:
            self.current['h3'] = True

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append(self.current)
            self.current = None
        if tag == 'li':
            self.bing_result = False

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data


def parse_results(page, engine):
    if engine not in ENGINES:
        raise ValueError('Unknown search engine')
    parser = Anchors(); parser.feed(page or '')
    urls = []
    for a in parser.links:
        candidate = ((engine == 'duckduckgo' and 'result__a' in a['class'].split()) or
                     (engine == 'bing' and a['bing']) or
                     (engine == 'google' and (a['h3'] or a['href'].startswith('/url?'))))
        if candidate:
            url = unwrap_result(a['href'], engine)
            if url and url not in urls:
                urls.append(url)
    if urls:
        return urls[:25]
    low = (page or '').lower()
    if any(marker in low for marker in ('anomaly-modal', 'g-recaptcha', '/sorry/', 'cf-chl-', 'verify you are human', 'unusual traffic')):
        raise UnverifiedSearch(engine+': challenge or access restriction')
    empty = {'google': ('did not match any documents', 'no results found'),
             'duckduckgo': ('no-results__message', 'no results found'),
             'bing': ('class="b_no"', "class='b_no'", 'there are no results for')}[engine]
    if any(marker in low for marker in empty):
        return []
    raise UnverifiedSearch(engine+': result markup not verified')


def discover_urls(query, fetcher):
    failures = []
    verified_empty = False
    for engine, base in ENGINES.items():
        try:
            page = fetcher(base+quote(query), timeout=12, attempts=1)
            urls = parse_results(page, engine)
            if urls:
                return urls
            verified_empty = True
        except Exception as exc:
            failures.append(engine+': '+str(exc)[:200])
    if verified_empty:
        if failures:
            print('SEARCH_FALLBACK_WARNINGS', '; '.join(failures), file=sys.stderr)
        return []
    raise UnverifiedSearch('NO_VERIFIED_SEARCH_ENGINE: '+'; '.join(failures))


def resolve_catalogue_card(entry, fetcher, is_card, parse_deadline):
    """Resolve an observed catalogue anchor, not a fabricated procurement URL.

    At most two GETs. Require exact procurement ID and title on the primary
    card plus a labelled future deadline. Otherwise return None (unverified).
    """
    origin = str(entry.get('link') or '')
    parts = urlsplit(origin)
    if parts.scheme != 'https' or parts.hostname != 'gentender.ru' or parts.path != '/search':
        return None
    rid = str(entry.get('id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{5,80}', rid):
        return None
    if (parse_qs(parts.query).get('q') or [''])[0] != rid:
        return None
    listing = fetcher(origin, timeout=12)
    parser = Anchors(); parser.feed(listing)
    candidates = []
    for a in parser.links:
        target = public_url(urljoin(origin, a['href']))
        host = urlsplit(target).hostname or ''
        if not target or not host_is(host, PRIMARY_TENDER_HOSTS):
            continue
        decoded = unquote(target)
        if not re.search(r'(?<![A-Za-z0-9])'+re.escape(rid)+r'(?![A-Za-z0-9])', decoded):
            continue
        if is_card(dict(entry, link=target)) and target not in candidates:
            candidates.append(target)
    if len(candidates) != 1:
        return None
    target = candidates[0]
    body = fetcher(target, timeout=12)
    text = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', body))).strip()
    if rid not in text or any(x in text.lower() for x in ('captcha', 'access denied', 'cf-chl-')):
        return None
    norm = lambda s: re.sub(r'\W+', ' ', s.lower().replace('\u0451', '\u0435')).strip()
    if norm(entry.get('title','')) not in norm(text) or len(norm(entry.get('title',''))) < 12:
        return None
    match = re.search(r'(?:\u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u0435\s+\u043f\u043e\u0434\u0430\u0447\u0438\s+\u0437\u0430\u044f\u0432\u043e\u043a|\u043f\u0440\u0438[\u0451\u0435]\u043c\s+\u0437\u0430\u044f\u0432\u043e\u043a\s+\u0434\u043e|\u0434\u0430\u0442\u0430\s+\u0438\s+\u0432\u0440\u0435\u043c\u044f\s+\u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f\s+\u043f\u043e\u0434\u0430\u0447\u0438\s+\u0437\u0430\u044f\u0432\u043e\u043a)\s*[:\-]?\s*(\d{2}\.\d{2}\.20\d{2}(?:\s+\d{2}:\d{2})?)', text, re.I)
    if not match:
        return None
    deadline = parse_deadline(match.group(1))
    if deadline is None or deadline <= datetime.now(ZoneInfo('Europe/Moscow')):
        return None
    return dict(entry, link=target, deadline=match.group(1), source='GenTender / verified primary card',
                verification={'id_confirmed':True, 'title_confirmed':True, 'deadline_confirmed':True})
