"""ECOFLOT v5.1 native reporting. No lead replay or queue mutation."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from search_reliability import sheet_rows, load_json, atomic_json, RECEIPTS, routes_from
from search_recipients import active_chats
from server_protocol import receipt_target

SHEET_ID = '1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws'
LEADS = 'Заявки'
USERS = 'Пользователи бота'
QUEUE = 'Очередь Telegram'
NAMES = ('Internet Leads', 'Telegram/MAX', 'Tender Watch', 'Object Leads')
LOCAL_NAMES = ('Internet Leads', 'Telegram/MAX/VK', 'Tender Watch', 'Object Leads')
CYCLE = re.compile(r'20\d{2}-\d{2}-\d{2} (?:08|14|18):00(?: EXTRA [A-Za-z0-9._-]+)?')


def number(value):
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def contour_for(rid, source):
    value = (str(rid) + ' ' + str(source)).lower()
    if any(t in value for t in ('tender', 'тендер')):
        return 'Tender Watch'
    if any(t in value for t in ('object', 'объект')):
        return 'Object Leads'
    if any(t in value for t in ('social', 'telegram', 'max-', 'max.ru', 'vk-')):
        return 'Telegram/MAX'
    if str(rid).upper().startswith(('WEB-', 'INTERNET-')):
        return 'Internet Leads'
    return None


def qualified_rollup(cycle, receipts, rows, expected):
    """Count identities across all attempts; rejected rows are not new leads."""
    indexed = {}
    for row in rows:
        r = list(row) + [''] * 6
        rid = str(r[0] or '')
        if rid:
            if rid in indexed:
                raise RuntimeError('DUPLICATE_CRM_REQUEST_ID')
            indexed[rid] = r
    result = {name: {'new': 0, 'sent': 0, 'excluded': 0, 'unknown': 0} for name in NAMES}
    counted = set()
    for rid, item in receipts.items():
        if not isinstance(item, dict) or item.get('accepted') is False:
            continue
        created_cycle = item.get('creation_cycleKey', item.get('cycleKey'))
        if created_cycle != cycle or (not item.get('creation_cycleKey') and item.get('duplicate') is True):
            continue
        if item.get('status') in ('IDENTITY_CONFLICT', 'SUPPRESSED'):
            continue
        name = contour_for(rid, item.get('source', ''))
        if not name:
            raise RuntimeError('UNMAPPED_RECEIPT_SOURCE')
        target = receipt_target(rid, item)
        if target in counted:
            continue
        counted.add(target)
        row = indexed.get(target)
        if row is None:
            result[name]['unknown'] += 1
            continue
        # Request ID, routes, callback, Telegram status, score, business status.
        score = row[4]
        if score is None or score == '':
            result[name]['unknown'] += 1
            continue
        if number(score) < 60 or str(row[3]).upper() in ('IGNORED', 'EXPIRED', 'CANCELLED'):
            result[name]['excluded'] += 1
            continue
        result[name]['new'] += 1
        ids = {route['chatId'] for route in routes_from(row[1])}
        if expected and expected.issubset(ids) and str(row[3]).upper() == 'SENT':
            result[name]['sent'] += 1
    return result


def build_payloads(state, rollup):
    cycle = str(state.get('cycleKey', ''))
    if not CYCLE.fullmatch(cycle):
        raise ValueError('EXPLICIT_VALID_CYCLE_REQUIRED')
    contours = state.get('contours', {})
    if set(LOCAL_NAMES) - set(contours):
        raise ValueError('ALL_FOUR_CONTOURS_REQUIRED')
    output = []
    for local, name in zip(LOCAL_NAMES, NAMES):
        c, count = contours[local], rollup[name]
        if c.get('status') not in ('ok', 'partial', 'error'):
            raise ValueError('UNFINISHED_CONTOUR')
        unchecked = sorted(set(str(x) for x in c.get('unchecked_sources', []) if x))
        errors = number(c.get('errors'))
        # Source diagnostics are internal audit data, NOT a Telegram message.
        # Forwarding URLs or raw parser/network errors generates unrelated site
        # previews in Telegram and clutters the approved-recipient feed.
        # The complete details remain in full_cycle_state.json and Actions logs.
        needs_attention = bool(count['unknown'] or count['new'] > count['sent'])
        status = 'error' if c.get('status') == 'error' else (
            'partial' if c.get('status') != 'ok' or errors or unchecked or needs_attention else 'ok')
        output.append({'mode': 'search_complete', 'cycleKey': cycle, 'searchName': name,
                       'status': status, 'newCount': count['new'],
                       'duplicates': number(c.get('duplicates')), 'errors': errors,
                       'unchecked_sources': [], 'error': ''})
    return output


def summary_text(payloads):
    status = 'error' if any(p['status'] == 'error' for p in payloads) else (
        'partial' if any(p['status'] != 'ok' for p in payloads) else 'ok')
    return '\n'.join(['ECOFLOT ' + payloads[0]['cycleKey'] + ' - ' + status] + [
        p['searchName'] + ': ' + p['status'] + ' / ' + str(p['newCount']) for p in payloads])


def confirm_outbox(rows, cycle, expected, summary):
    """HTTP 200, queued=true, an old summary or a send count is not delivery."""
    expected = set(str(x) for x in expected)
    found = set()
    routes = {}
    for row in rows:
        kind, key, raw, attempts, error, status = (list(row) + [''] * 6)[:6]
        if kind != 'text_one' or status != 'SENT' or number(attempts) < 1:
            continue
        key = str(key or '')
        if not key.startswith(cycle + '|FULL CYCLE|'):
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        chat = str(payload.get('chatId', ''))
        if chat not in expected or not key.endswith('|' + chat) or payload.get('text') != summary:
            continue
        metadata = payload.get('_ef5')
        if not isinstance(metadata, dict):
            continue
        valid = routes_from([metadata.get('receipt')])
        for receipt in valid:
            if receipt['chatId'] == chat:
                found.add(chat)
                routes[chat] = receipt
    return {'ok': bool(expected) and expected.issubset(found), 'expected': len(expected),
            'confirmed': len(found), 'pending': len(expected - found),
            'routes': [routes[c] for c in sorted(routes)]}


def post_report(payload, *, opener=urllib.request.urlopen):
    from internet_leads_monitor import WEBHOOK
    request = urllib.request.Request(WEBHOOK,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), method='POST',
        headers={'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'ECOFLOT-Report-Protocol/5.1'})
    with opener(request, timeout=40) as response:
        result = json.loads(response.read().decode('utf-8'))
    if (not isinstance(result, dict) or result.get('ok') is not True
            or result.get('recorded') is not True or result.get('cycleKey') != payload['cycleKey']
            or result.get('status') != payload['status']):
        raise RuntimeError('SEARCH_REPORT_NOT_ACKNOWLEDGED')
    return result


def publish_cycle(state, *, read=sheet_rows, post=post_report, wait=None):
    if not state.get('expected_chats'):
        state['cycle_notice'] = 'not-sent:no-verified-recipients'
        return
    if os.environ.get('ECOFLOT_NOTIFY_SUMMARY', '1') == '0':
        return
    try:
        expected = active_chats(read(SHEET_ID, USERS, 'A,E'))
        if not expected:
            raise RuntimeError('NO_VERIFIED_RECIPIENTS')
        receipts = load_json(RECEIPTS, {'items': {}})['items']
        rows = read(SHEET_ID, LEADS, 'L,M,U,V,O,J')
        rollup = qualified_rollup(state['cycleKey'], receipts, rows, expected)
        payloads = build_payloads(state, rollup)
        signature = hashlib.sha256(json.dumps(payloads, sort_keys=True).encode()).hexdigest()
        state['qualified_slot_totals'] = rollup
        if state.get('report_payload_sha256') != signature or not state.get('report_recorded'):
            for payload in payloads:
                post(payload)
            state['report_recorded'] = True
            state['report_payload_sha256'] = signature
        text = summary_text(payloads)
        limit = max(0, min(480, int(wait if wait is not None else os.environ.get('ECOFLOT_REPORT_WAIT_SECONDS', '360'))))
        deadline = time.monotonic() + limit
        while True:
            queue = read(SHEET_ID, QUEUE, 'B,C,D,E,F,G')
            evidence = confirm_outbox(queue, state['cycleKey'], expected, text)
            state['report_delivery'] = evidence
            if evidence['ok'] or time.monotonic() >= deadline:
                break
            time.sleep(min(20, max(0, deadline - time.monotonic())))
        state['cycle_notice'] = 'sent' if evidence['ok'] else 'queued'
        if state.get('status') == 'COMPLETE' and not evidence['ok']:
            state['status'] = 'DELIVERY_PENDING'
        state['report_checked_at'] = datetime.now(timezone.utc).isoformat()
        print('REPORT_DELIVERY', json.dumps({k: v for k, v in evidence.items() if k != 'routes'}), flush=True)
    except Exception as exc:
        state['cycle_notice'] = 'error: ' + str(exc)
        if state.get('status') == 'COMPLETE':
            state['status'] = 'DELIVERY_PENDING'
        print('REPORT_PROTOCOL_ERROR', str(exc), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cycle', required=True)
    args = parser.parse_args()
    history = load_json(Path('search_cycle_history.json'), {'cycles': {}})
    if args.cycle not in history['cycles']:
        raise RuntimeError('NO_VERIFIED_CYCLE_TO_REPORT')
    state = copy.deepcopy(history['cycles'][args.cycle])
    publish_cycle(state)
    history['cycles'][args.cycle] = state
    atomic_json(Path('search_cycle_history.json'), history)
    current = load_json(Path('full_cycle_state.json'))
    if current.get('cycleKey') == args.cycle:
        atomic_json(Path('full_cycle_state.json'), state)
    return 0 if state.get('cycle_notice') == 'sent' else 1


if __name__ == '__main__':
    raise SystemExit(main())
