#!/usr/bin/env python3
"""Explicit scheduled-worker adapters; no source rewriting or workflow changes.

Keep the existing collectors intact. Bind the corrected contracts for the
lifetime of ONE worker process; restore all bindings after tests or completion.
"""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import html
import importlib
import os
import re
import sys
import time
from urllib.parse import urlsplit
import search_reliability as r
from source_repair import ENGINES, UnverifiedSearch, host_is, resolve_catalogue_card
from urllib.parse import quote
from search_topic import parse_results
from server_protocol import verified_alias, remember_alias, canonical_request_ids

WORKERS = frozenset(('internet_leads_monitor', 'social_leads_monitor',
                     'max_leads_monitor', 'tender_monitor', 'object_leads_monitor'))


def strict_acknowledged(response, request_id):
    if not isinstance(response, dict) or response.get('ok') is not True or response.get('filtered') is True:
        return False
    returned = str(response.get('requestId') or response.get('request_id') or '')
    if returned and returned != str(request_id):
        return False
    if response.get('duplicate') is True:
        return bool(verified_alias(response, request_id)) or (
            returned == str(request_id) and response.get('duplicateReason') in (None, 'request_id'))
    return bool(returned or response.get('callbackKey') or r.int_value(response.get('row')) or
                r.int_value(response.get('rowNumber')) or response.get('saved') is True or
                response.get('created') is True)


def record_identity_conflict(request_id, response, source):
    ledger = r.load_json(r.RECEIPTS, {'items': {}})
    items = ledger.setdefault('items', {})
    previous = items.get(str(request_id), {})
    items[str(request_id)] = {
        'requestId': str(request_id), 'run_id': r.run_id(),
        'cycleKey': os.environ.get('ECOFLOT_CYCLE_KEY', ''),
        'source': str(source), 'duplicate': True, 'accepted': False,
        'status': 'IDENTITY_CONFLICT',
        'reported_row': r.int_value(response.get('duplicateRow')),
        'reported_reason': str(response.get('duplicateReason') or '')[:80],
        'reported_request_id': str(response.get('requestId') or response.get('request_id') or '')[:200],
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'first_seen_at': previous.get('first_seen_at') or datetime.now(timezone.utc).isoformat(),
    }
    r.atomic_json(r.RECEIPTS, ledger)


class DiscoverySession:
    """Per-worker circuit breaker: unavailable engines do not consume every query."""
    def __init__(self, fetcher, budget=120, failure_limit=2):
        self.fetcher = fetcher
        self.budget = budget
        self.spent = 0.0
        self.failure_limit = failure_limit
        self.failures = dict.fromkeys(ENGINES, 0)
        self.warnings = set()

    def search(self, query):
        errors = []
        empty_verified = False
        for engine, base in ENGINES.items():
            if self.failures[engine] >= self.failure_limit:
                errors.append(engine + ': circuit open')
                continue
            if self.spent >= self.budget:
                errors.append('discovery time budget exhausted')
                break
            started = time.monotonic()
            try:
                timeout = max(1, min(12, self.budget - self.spent))
                page = self.fetcher(base + quote(query), timeout=timeout, attempts=1)
                urls = parse_results(page, engine, query)
                self.failures[engine] = 0
                if urls:
                    return urls
                empty_verified = True
            except Exception as exc:
                self.failures[engine] += 1
                message = engine + ': ' + str(exc)[:180]
                errors.append(message)
                self.warnings.add(message)
            finally:
                self.spent += max(0, time.monotonic() - started)
        if empty_verified:
            return []
        raise UnverifiedSearch('NO_VERIFIED_SEARCH_ENGINE: ' + '; '.join(errors))


@contextmanager
def binding(obj, key, value):
    old = getattr(obj, key)
    setattr(obj, key, value)
    try:
        yield
    finally:
        setattr(obj, key, old)


@contextmanager
def configured_worker(name):
    if name not in WORKERS:
        raise ValueError('Unknown ECOFLOT worker')
    original_record = r.record_lead_result
    def record(request_id, response, source):
        if isinstance(response, dict) and response.get('ok') is True and response.get('duplicate') is True:
            if not strict_acknowledged(response, request_id):
                record_identity_conflict(request_id, response, source)
                raise RuntimeError('DUPLICATE_IDENTITY_UNVERIFIED: retained for review, not processed')
        result = original_record(request_id, response, source)
        remember_alias(request_id, response, r)
        return result
    # Import before binding so no import-time aliases outlive this context.
    internet = importlib.import_module('internet_leads_monitor')
    module = importlib.import_module(name)
    session = DiscoverySession(lambda *a, **k: internet.fetch(*a, **k))
    unchecked = set()
    with ExitStack() as stack:
        stack.enter_context(binding(r, 'acknowledged', strict_acknowledged))
        stack.enter_context(binding(r, 'record_lead_result', record))
        for current in {internet, module}:
            if hasattr(current, 'record_lead_result'):
                stack.enter_context(binding(current, 'record_lead_result', record))
            if hasattr(current, 'discovery_result_urls'):
                stack.enter_context(binding(current, 'discovery_result_urls', session.search))
        if name == 'tender_monitor':
            original_relevant = module.relevant
            original_card = module.valid_tender_card_link
            original_ids = module.load_sheet_request_ids
            known_ids = set()
            resolved = {}
            attempted = set()
            stack.enter_context(binding(module, 'EXCLUDE', tuple(x for x in module.EXCLUDE if x != '\u0441\u043d\u0435\u0433')))
            def relevant(entry):
                title = str(entry.get('title') or '').lower().replace('\u0451', '\u0435')
                if not r.tender_service_demand(title):
                    return False
                if any(term in title for term in module.EXCLUDE):
                    return False
                return original_relevant(entry) or ('\u0441\u043d\u0435\u0433' in title and any(
                    term in title for term in ('\u0432\u044b\u0432\u043e\u0437', '\u043f\u043e\u0433\u0440\u0443\u0437', '\u0443\u0431\u043e\u0440'))) or (
                    '\u0430\u0440\u0435\u043d\u0434' in title and any(term in title for term in (
                    '\u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b', '\u0441\u043f\u0435\u0446\u0442\u0435\u0445', '\u044d\u043a\u0441\u043a\u0430\u0432\u0430\u0442\u043e\u0440', '\u043f\u043e\u0433\u0440\u0443\u0437\u0447\u0438\u043a')))
            def load_ids():
                ids, ok = original_ids()
                if not ok:
                    raise RuntimeError('SHEET_DEDUPE_UNAVAILABLE')
                known_ids.update(ids)
                return ids, ok
            def card(entry):
                if original_card(entry):
                    return True
                rid = module.request_id_for(entry)
                link = str(entry.get('link') or '')
                parts = urlsplit(link)
                match = re.fullmatch(r'/search/number/l(\d{19})-\d+/?', parts.path)
                if parts.scheme == 'https' and parts.hostname in ('b2b-center.ru', 'www.b2b-center.ru') and match:
                    return module.canonical_tender_id(entry) == match.group(1)
                if parts.hostname != 'gentender.ru' or parts.path != '/search' or rid in known_ids:
                    return False
                if rid not in attempted:
                    if len(attempted) >= 12:
                        unchecked.add('GenTender: primary-card resolution budget reached')
                        return False
                    attempted.add(rid)
                    try:
                        resolved[rid] = resolve_catalogue_card(entry, module.fetch, original_card, r.parse_deadline)
                    except Exception as exc:
                        unchecked.add('GenTender/' + rid + ': ' + str(exc)[:160])
                    if not resolved.get(rid):
                        try:
                            canonical = module.canonical_tender_id(entry)
                            if re.fullmatch(r'\\d{19}', canonical):
                                mirror = 'https://poisktenderov.ru/item/' + canonical + '/'
                                page = module.fetch(mirror, timeout=12)
                                text = re.sub(r'\\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', page))).strip()
                                norm = lambda value: re.sub(r'\\W+', ' ', str(value or '').lower().replace('\\u0451', '\\u0435')).strip()
                                deadline_match = re.search(
                                    r'(?:\\u0417\\u0430\\u044f\\u0432\\u043a\\u0438\\s+\\u0434\\u043e|'
                                    r'\\u041e\\u043a\\u043e\\u043d\\u0447\\u0430\\u043d\\u0438\\u0435\\s+\\u043f\\u043e\\u0434\\u0430\\u0447\\u0438(?:\\s+\\u0437\\u0430\\u044f\\u0432\\u043e\\u043a)?)'
                                    r'\\s*[:\\-]?\\s*(\\d{2}\\.\\d{2}\\.20\\d{2}(?:\\s+\\d{2}:\\d{2})?)',
                                    text, re.I)
                                deadline = r.parse_deadline(deadline_match.group(1)) if deadline_match else None
                                title = norm(entry.get('title'))
                                if (canonical in text and title and title in norm(text) and deadline is not None
                                        and deadline > datetime.now(r.MSK)):
                                    resolved[rid] = dict(
                                        entry,
                                        link=mirror,
                                        deadline=deadline_match.group(1),
                                        source='PoiskTenderov verified card / EIS procurement number',
                                        verification={
                                            'id_confirmed': True,
                                            'title_confirmed': True,
                                            'deadline_confirmed': True,
                                            'resolver': 'poisktenderov.ru',
                                        },
                                    )
                        except Exception as exc:
                            unchecked.add('GenTender/' + rid + ': public-card resolver ' + str(exc)[:160])
                    if not resolved.get(rid):
                        unchecked.add('GenTender/' + rid + ': primary card not verified')
                if resolved.get(rid):
                    entry.update(resolved[rid])
                    return True
                return False
            allowed = ('fabrikant.ru','roseltorg.ru','rts-tender.ru','sberbank-ast.ru','etpgpb.ru')
            def discover_tenders(query):
                return [url for url in session.search(query) if host_is(urlsplit(url).hostname or '', allowed)]
            stack.enter_context(binding(module, 'relevant', relevant))
            stack.enter_context(binding(module, 'load_sheet_request_ids', load_ids))
            stack.enter_context(binding(module, 'valid_tender_card_link', card))
            stack.enter_context(binding(module, 'tender_discovery_urls', discover_tenders))
        original_save = module.save_state
        def save(state):
            last = state.get('last_run', {})
            if last.get('run_id') == r.run_id():
                last['runtime_version'] = '2026-10-07.2'
                last['unchecked_sources'] = sorted(set(last.get('unchecked_sources') or []) | unchecked | session.warnings)
                last['discovery_seconds'] = round(session.spent, 2)
            return original_save(state)
        stack.enter_context(binding(module, 'save_state', save))
        yield module


def audit_delivery(rows, expected, request_ids=None):
    """Suppressed expired records are not deliveries and not live retry backlog."""
    result = dict(checked=0, confirmed=0, pending=0, missing_records=0, duplicate_routes=0, suppressed=0, service_rows=0)
    request_ids = canonical_request_ids(request_ids, r)
    found = set()
    for row in rows:
        rid, value, key, status = (list(row) + [''] * 4)[:4]
        if not rid or (request_ids is not None and rid not in request_ids):
            continue
        if re.match(r'^(CRM_ACTION_|CRM-BULK-ACTION|TEST[-_])', rid, re.I):
            result['service_rows'] += 1
            continue
        found.add(rid)
        if status.upper() in ('IGNORED', 'CANCELLED', 'EXPIRED'):
            result['suppressed'] += 1
            continue
        result['checked'] += 1
        chats = [x['chatId'] for x in r.routes_from(value)]
        result['duplicate_routes'] += len(chats) - len(set(chats))
        verified = bool(expected) and set(expected).issubset(chats) and status.upper() == 'SENT'
        result['confirmed' if verified else 'pending'] += 1
    if request_ids is not None:
        result['missing_records'] = len(set(request_ids) - found)
        result['pending'] += result['missing_records']
    result['ok'] = bool(expected) and result['pending'] == 0
    return result


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].endswith('.py') or args[0][:-3] not in WORKERS:
        raise ValueError('Expected one allowlisted collector filename')
    with configured_worker(args[0][:-3]) as module:
        return module.main()


if __name__ == '__main__':
    raise SystemExit(main())
