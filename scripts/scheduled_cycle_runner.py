#!/usr/bin/env python3
"""Bind cron wake-ups to their slot; refresh receipts without replaying searches."""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from server_protocol import receipt_target

MSK = ZoneInfo('Europe/Moscow')
SLOTS = {'0,12,32 5 * * *': 8, '0,12,32 11 * * *': 14, '0,12,32 15 * * *': 18}


def scheduled_slot(expression, now=None):
    """A delayed 08:00 cron remains 08:00, even when started after 14:00."""
    if expression not in SLOTS:
        raise ValueError('Unsupported scheduled expression; refusing an ambiguous cycle key')
    now = now or datetime.now(MSK)
    if now.tzinfo is None:
        raise ValueError('An aware timestamp is required')
    now = now.astimezone(MSK)
    slot = now.replace(hour=SLOTS[expression], minute=0, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    return slot.strftime('%Y-%m-%d %H:%M')


def refreshed_state(previous, rows, expected, receipts, audit, now=None):
    """Pure reconciliation: no POSTs, no inferred delivery from duplicate flags."""
    state = copy.deepcopy(previous)
    items = {rid: item for rid, item in receipts.items()
             if item.get('run_id') == state.get('run_id')}
    ids = set(items)
    delivery = audit(rows, expected, ids)
    found_ids = {str(row[0]) for row in rows if row}
    unresolved_duplicates = {rid for rid, item in items.items()
                             if item.get('duplicate') is True and receipt_target(rid, item) not in found_ids}
    delivery['unresolved_duplicate_references'] = len(unresolved_duplicates)
    delivery['pending_new_or_known_records'] = max(
        0, delivery.get('pending', 0) - len(unresolved_duplicates))
    expected_receipts = int(state.get('totals', {}).get('accepted', 0) or 0)
    missing_receipts = max(0, expected_receipts - len(items))
    delivery['missing_receipts'] = missing_receipts
    if missing_receipts:
        delivery['ok'] = False
    delivery['mode'] = 'read-only-sheet-reconciliation'
    state['delivery'] = delivery
    state['backlog'] = audit(rows, expected)
    state['delivery_reconciled_at'] = (now or datetime.now(MSK)).isoformat()
    state.setdefault('totals', {})['confirmed_after_reconciliation'] = delivery.get('confirmed', 0)
    state['totals']['pending_after_reconciliation'] = delivery.get('pending', 0) + missing_receipts
    if state.get('status') in ('COMPLETE', 'DELIVERY_PENDING'):
        state['status'] = 'COMPLETE' if delivery.get('ok') else 'DELIVERY_PENDING'
    return state


def refresh_previous(coordinator, previous, history):
    try:
        expected = coordinator.active_chats(coordinator.sheet_rows(
            coordinator.SHEET_ID, '\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438 \u0431\u043e\u0442\u0430', 'A,E'))
        if not expected:
            raise RuntimeError('NO_VERIFIED_RECIPIENTS')
        rows = coordinator.sheet_rows(coordinator.SHEET_ID, '\u0417\u0430\u044f\u0432\u043a\u0438', 'L,M,U,V')
        receipts = coordinator.load_json(coordinator.RECEIPTS, {'items': {}})['items']
        state = refreshed_state(previous, rows, expected, receipts, coordinator.audit_delivery)
    except Exception as exc:
        state = copy.deepcopy(previous)
        state['delivery'] = {'ok': False, 'error': str(exc), 'mode': 'read-only-sheet-reconciliation'}
        state['delivery_reconciled_at'] = datetime.now(MSK).isoformat()
        if state.get('status') == 'COMPLETE':
            state['status'] = 'DELIVERY_PENDING'
    history.setdefault('cycles', {})[state['cycleKey']] = state
    coordinator.atomic_json(coordinator.HISTORY_FILE, history)
    latest = coordinator.load_json(coordinator.STATE_FILE)
    if latest.get('cycleKey') == state['cycleKey']:
        coordinator.atomic_json(coordinator.STATE_FILE, state)
        report = '# ECOFLOT ' + state['cycleKey'] + '\n\n'
        report += 'Status: **' + state['status'] + '**\n\n'
        report += 'Delivery rechecked without rerunning searches or sending cards.\n\n'
        report += 'Delivery: `' + json.dumps(state['delivery']) + '`\n\n'
        report += 'Source errors and unverified sources remain in full_cycle_state.json.\n'
        Path('search_cycle_report.md').write_text(report, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('## Receipt reconciliation\n\nNo search or sends replayed.\n\n`'
                         + json.dumps(state['delivery']) + '`\n')
    print('DELIVERY_RECONCILED', json.dumps(state, ensure_ascii=False), flush=True)
    return coordinator.exit_code(state['status'])


def main():
    import full_cycle_orchestrator as coordinator
    history = coordinator.load_json(coordinator.HISTORY_FILE, {'cycles': {}})
    if '--reconcile-only' in sys.argv[1:]:
        previous = coordinator.load_json(coordinator.STATE_FILE)
        if not previous.get('cycleKey') or previous.get('status') not in coordinator.TERMINAL:
            raise RuntimeError('No completed cycle available for read-only reconciliation')
        return refresh_previous(coordinator, previous, history)
    expression = os.environ.get('ECOFLOT_SCHEDULE', '').strip()
    if expression:
        os.environ['ECOFLOT_CYCLE_KEY'] = scheduled_slot(expression)
    cycle = os.environ.get('ECOFLOT_CYCLE_KEY', '').strip() or coordinator.cycle_key()
    previous = history.get('cycles', {}).get(cycle)
    if os.environ.get('ECOFLOT_FORCE') != '1' and previous:
        retry_failed = previous.get('status') == 'SEARCH_FAILED' and previous.get('attempts', 1) < 2
        if previous.get('status') in coordinator.TERMINAL and not retry_failed:
            return refresh_previous(coordinator, previous, history)
    return coordinator.main()


if __name__ == '__main__':
    raise SystemExit(main())
