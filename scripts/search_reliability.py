#!/usr/bin/env python3
"""Shared safety contracts for ECOFLOT searches; no network calls at import time."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MSK = ZoneInfo('Europe/Moscow')
RECEIPTS = Path('search_delivery_receipts.json')
STATS = {'accepted': 0, 'created': 0, 'server_duplicates': 0, 'delivery_confirmed': 0, 'delivery_pending': 0}


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return {} if default is None else default
    value = json.loads(path.read_text('utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected JSON object; refusing to reset deduplication state')
    return value


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_id():
    return os.environ.get('ECOFLOT_RUN_ID') or '.'.join([
        os.environ.get('GITHUB_RUN_ID', 'local'), os.environ.get('GITHUB_RUN_ATTEMPT', '1')])


def scheduled_cycle(now=None):
    now = (now or datetime.now(MSK)).astimezone(MSK)
    for hour in (18, 14, 8):
        if now.hour >= hour:
            return now.strftime('%Y-%m-%d') + f' {hour:02d}:00'
    return (now - timedelta(days=1)).strftime('%Y-%m-%d') + ' 18:00'


def int_value(value):
    if isinstance(value, bool):
        return int(value)
    try:
        return max(0, int(value or 0))
    except (ValueError, TypeError):
        return 0


def routes_from(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        value = value.get('routes', [])
    if not isinstance(value, list):
        return []
    result = []
    for route in value:
        if not isinstance(route, dict):
            continue
        chat = str(route.get('chatId', route.get('chat_id', ''))).strip()
        msg = str(route.get('messageId', route.get('message_id', ''))).strip()
        if re.fullmatch(r'-?\d+', chat) and re.fullmatch(r'[1-9]\d*', msg):
            result.append({'chatId': chat, 'messageId': msg})
    return result


def delivery_confirmed(response, expected=None):
    """A duplicate or ok=true is NOT a Telegram receipt. Require all intended chats."""
    if not isinstance(response, dict) or response.get('ok') is not True:
        return False
    expected = set(expected if expected is not None else
                   filter(None, os.environ.get('ECOFLOT_EXPECTED_CHATS', '').split(',')))
    if not expected:
        return False
    routes = []
    for key in ('telegramRoute', 'telegramRoutes', 'routes'):
        routes.extend(routes_from(response.get(key)))
    tg = response.get('telegram')
    if isinstance(tg, dict):
        routes.extend(routes_from(tg))
    return expected.issubset({r['chatId'] for r in routes})


def acknowledged(response, request_id):
    """Reject generic doGet/health responses after a redirect or wrong API route."""
    if not isinstance(response, dict) or response.get('ok') is not True:
        return False
    returned_id = str(response.get('requestId') or response.get('request_id') or '')
    if returned_id and returned_id != str(request_id):
        return False
    return bool(response.get('duplicate') is True or returned_id or response.get('callbackKey') or
                int_value(response.get('row')) or int_value(response.get('rowNumber')) or
                response.get('saved') is True or response.get('created') is True)


def record_lead_result(request_id, response, source):
    if not acknowledged(response, request_id):
        # Do not mark the request as processed. The server may not have received it.
        raise RuntimeError('WRITE_NOT_CONFIRMED: webhook returned no lead acknowledgement; '
                           f'fields={sorted(response) if isinstance(response, dict) else []}')
    confirmed = delivery_confirmed(response)
    duplicate = response.get('duplicate') is True
    STATS['accepted'] += 1
    STATS['created'] += int(not duplicate)
    STATS['server_duplicates'] += int(duplicate)
    STATS['delivery_confirmed' if confirmed else 'delivery_pending'] += 1
    ledger = load_json(RECEIPTS, {'items': {}})
    items = ledger.setdefault('items', {})
    prior = items.get(str(request_id), {})
    items[str(request_id)] = {
        'requestId': str(request_id), 'cycleKey': os.environ.get('ECOFLOT_CYCLE_KEY', ''),
        'run_id': run_id(), 'source': str(source), 'duplicate': duplicate,
        'accepted_at': datetime.now(timezone.utc).isoformat(),
        'status': 'DELIVERED' if confirmed else 'PENDING_VERIFICATION',
        'first_seen_at': prior.get('first_seen_at') or datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(RECEIPTS, ledger)
    return response


def finish_metrics(state):
    last = state.get('last_run')
    if isinstance(last, dict) and last.get('cycleKey', '') == os.environ.get('ECOFLOT_CYCLE_KEY', ''):
        last['run_id'] = run_id()
        last['search_mode'] = os.environ.get('ECOFLOT_SEARCH_MODE', 'Standard')
        last['accepted'] = STATS['accepted']
        last['new'] = STATS['created']
        last['duplicates_server'] = STATS['server_duplicates']
        last['sent'] = STATS['delivery_confirmed']
        last['delivery_pending'] = STATS['delivery_pending']
        last['metrics_version'] = 2
    return state


def aggregate(paths, cycle, expected_run):
    totals = {'new': 0, 'duplicates': 0, 'accepted': 0, 'sent': 0, 'delivery_pending': 0,
              'errors': 0, 'unchecked_sources': [], 'missing_states': [], 'error_details': []}
    for path in paths:
        try:
            last = load_json(path).get('last_run', {})
        except (ValueError, OSError) as exc:
            totals['missing_states'].append(str(path))
            totals['error_details'].append(str(exc))
            continue
        if last.get('cycleKey') != cycle or last.get('run_id') != expected_run:
            totals['missing_states'].append(str(path))
            continue
        for key in ('new', 'accepted', 'sent', 'delivery_pending', 'errors'):
            totals[key] += int_value(last.get(key))
        totals['duplicates'] += int_value(last.get('duplicates_local')) + int_value(last.get('duplicates_server'))
        totals['error_details'].extend(last.get('error_details') or [])
        unchecked = last.get('unchecked_sources') or last.get('unverified_sources') or []
        totals['unchecked_sources'].extend([unchecked] if isinstance(unchecked, str) else unchecked)
    totals['unchecked_sources'] = sorted(set(totals['unchecked_sources']))
    totals['state_found'] = not totals['missing_states']
    totals['status'] = ('error' if totals['missing_states'] else
                        'partial' if totals['errors'] or totals['unchecked_sources'] else 'ok')
    return totals


def parse_deadline(text, now=None):
    """Date-only deadlines today are not proven open. No invented year rollover."""
    now = (now or datetime.now(MSK)).astimezone(MSK)
    value = str(text or '').lower()
    match = re.search(r'(?<!\d)(\d{1,2})[./](\d{1,2})[./](20\d{2})(?:\s+(\d{1,2}):(\d{2}))?', value)
    if match:
        d, m, y, h, minute = match.groups()
    else:
        match = re.search(r'(?<!\d)(\d{1,2})\s+('
                          r'\u044f\u043d\u0432\u0430\u0440\u044f|\u0444\u0435\u0432\u0440\u0430\u043b\u044f|\u043c\u0430\u0440\u0442\u0430|\u0430\u043f\u0440\u0435\u043b\u044f|\u043c\u0430\u044f|\u0438\u044e\u043d\u044f|\u0438\u044e\u043b\u044f|\u0430\u0432\u0433\u0443\u0441\u0442\u0430|\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f|\u043e\u043a\u0442\u044f\u0431\u0440\u044f|\u043d\u043e\u044f\u0431\u0440\u044f|\u0434\u0435\u043a\u0430\u0431\u0440\u044f'
                          r')(?:\s+(20\d{2}))?(?:\s+(\d{1,2}):(\d{2}))?', value)
        if not match:
            return None
        d, month, y, h, minute = match.groups()
        months = '\u044f\u043d\u0432\u0430\u0440\u044f \u0444\u0435\u0432\u0440\u0430\u043b\u044f \u043c\u0430\u0440\u0442\u0430 \u0430\u043f\u0440\u0435\u043b\u044f \u043c\u0430\u044f \u0438\u044e\u043d\u044f \u0438\u044e\u043b\u044f \u0430\u0432\u0433\u0443\u0441\u0442\u0430 \u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f \u043e\u043a\u0442\u044f\u0431\u0440\u044f \u043d\u043e\u044f\u0431\u0440\u044f \u0434\u0435\u043a\u0430\u0431\u0440\u044f'.split()
        m, y = months.index(month) + 1, y or now.year
    try:
        return datetime(int(y), int(m), int(d), int(h or 0), int(minute or 0), tzinfo=MSK)
    except (ValueError, TypeError):
        return None


def tender_service_demand(title):
    text = str(title or '').lower().replace('\u0451', '\u0435')
    banned = ('\u0437\u0430\u043f\u0447\u0430\u0441\u0442', '\u0437\u0430\u043f\u0430\u0441\u043d\u044b\u0435 \u0447\u0430\u0441\u0442', '\u0430\u043a\u043f\u043f', '\u0440\u0435\u043c\u043e\u043d\u0442 \u043a\u043f\u043f',
              '\u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435', '\u043a\u043e\u043c\u043f\u043b\u0435\u043a\u0442\u0443\u044e\u0449', '\u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b',
              '\u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u044d\u043a\u0441\u043a\u0430\u0432\u0430\u0442\u043e\u0440', '\u043f\u043e\u043a\u0443\u043f\u043a\u0430 \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b', '\u043f\u0440\u0438\u043e\u0431\u0440\u0435\u0442\u0435\u043d\u0438\u0435 \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b')
    if any(word in text for word in banned):
        return False
    services = ('\u0432\u044b\u0432\u043e\u0437', '\u0442\u0440\u0430\u043d\u0441\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432', '\u043f\u0435\u0440\u0435\u0432\u043e\u0437', '\u0430\u0440\u0435\u043d\u0434', '\u0437\u0435\u043c\u043b\u044f\u043d', '\u043a\u043e\u0442\u043b\u043e\u0432\u0430\u043d',
                '\u0434\u0435\u043c\u043e\u043d\u0442\u0430\u0436', '\u0441\u043d\u043e\u0441', '\u0440\u0430\u0441\u0447\u0438\u0441\u0442', '\u043f\u043e\u0433\u0440\u0443\u0437\u043a', '\u0443\u0431\u043e\u0440\u043a', '\u043e\u0431\u0440\u0430\u0449\u0435\u043d\u0438\u044e \u0441 \u043e\u0442\u0445\u043e\u0434',
                '\u0443\u0442\u0438\u043b\u0438\u0437\u0430\u0446', '\u043e\u0431\u0435\u0437\u0432\u0440\u0435\u0436', '\u0431\u043b\u0430\u0433\u043e\u0443\u0441\u0442\u0440\u043e\u0439')
    if any(word in text for word in services):
        return True
    return '\u043f\u0440\u0435\u0434\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d' in text and any(word in text for word in
        ('\u0441\u043f\u0435\u0446\u0442\u0435\u0445', '\u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b', '\u044d\u043a\u0441\u043a\u0430\u0432\u0430\u0442\u043e\u0440', '\u043f\u043e\u0433\u0440\u0443\u0437\u0447\u0438\u043a'))


def sheet_rows(sheet_id, sheet_name, columns, fetcher=None):
    import urllib.parse
    import urllib.request
    query = urllib.parse.urlencode({'sheet': sheet_name, 'headers': '1', 'tqx': 'out:json', 'tq': 'select '+columns})
    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?{query}'
    if fetcher is None:
        def fetcher(address):
            with urllib.request.urlopen(address, timeout=30) as response:
                return response.read().decode('utf-8')
    raw = fetcher(url)
    match = re.search(r'google\.visualization\.Query\.setResponse\((.*)\);?\s*$', raw, re.S)
    data = json.loads(match.group(1) if match else raw)
    if data.get('status') != 'ok' or not isinstance(data.get('table'), dict):
        raise RuntimeError('SHEET_READ_NOT_CONFIRMED')
    rows = []
    for row in data['table'].get('rows', []):
        cells = []
        for cell in row.get('c') or []:
            value = (cell or {}).get('v')
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            cells.append(str(value) if value is not None else '')
        rows.append(cells)
    return rows


def active_chats(rows):
    approved, blocked = set(), set()
    for row in rows:
        if len(row) < 2:
            continue
        chat, status = row[:2]
        if not re.fullmatch(r'-?\d+', chat):
            continue
        if status.lower().replace('\u0451', '\u0435') in ('\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d', 'approved'):
            approved.add(chat)
        else:
            blocked.add(chat)
    return approved - blocked


def audit_delivery(rows, expected, request_ids=None):
    """Read-only reconciliation. Never enqueue or replay an ambiguous send."""
    result = {'checked': 0, 'confirmed': 0, 'pending': 0, 'missing_records': 0, 'duplicate_routes': 0}
    found = set()
    for row in rows:
        row = row + [''] * max(0, 4-len(row))
        rid, route_value, callback_key, status = row[:4]
        if not rid or (request_ids is not None and rid not in request_ids):
            continue
        found.add(rid)
        result['checked'] += 1
        routes = routes_from(route_value)
        chats = [x['chatId'] for x in routes]
        result['duplicate_routes'] += len(chats) - len(set(chats))
        verified = bool(expected) and set(expected).issubset(chats)
        result['confirmed' if verified else 'pending'] += 1
    if request_ids is not None:
        result['missing_records'] = len(set(request_ids)-found)
        result['pending'] += result['missing_records']
    result['ok'] = bool(expected) and result['pending'] == 0
    return result
