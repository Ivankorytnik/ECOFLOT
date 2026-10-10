#!/usr/bin/env python3
"""One coordinator, durable slot ledger and evidence-based completion."""
import copy
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from search_reliability import (MSK, load_json, atomic_json, run_id, scheduled_cycle,
    aggregate, sheet_rows, RECEIPTS)
from search_runtime import audit_delivery
from search_recipients import active_chats

STATE_FILE = Path('full_cycle_state.json')
HISTORY_FILE = Path('search_cycle_history.json')
SHEET_ID = '1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws'
CONTOURS = [
    ('Internet Leads', ['internet_leads_monitor.py'], ['internet_leads_state.json'], 720),
    ('Telegram/MAX/VK', ['social_leads_monitor.py', 'max_leads_monitor.py'],
     ['social_public_leads_state.json', 'max_public_leads_state.json'], 360),
    ('Tender Watch', ['tender_monitor.py'], ['tender_state.json'], 720),
    ('Object Leads', ['object_leads_monitor.py'], ['object_leads_state.json'], 360),
]
TERMINAL = {'COMPLETE', 'SEARCH_PARTIAL', 'SEARCH_FAILED', 'DELIVERY_PENDING'}


def cycle_key(now=None):
    return scheduled_cycle(now)


def exit_code(status):
    # SEARCH_PARTIAL is a completed search with explicit coverage warnings, not a
    # crashed workflow. Keep hard failures red, and keep unconfirmed delivery red.
    return 1 if status in ('SEARCH_FAILED', 'DELIVERY_PENDING') else 0


def reconcile_delivery(expected, current_ids):
    """Wait briefly for the Apps Script -> Google Sheets delivery write to settle."""
    wait_seconds = max(0, int(os.environ.get('ECOFLOT_DELIVERY_WAIT_SECONDS', '210')))
    interval = max(5, int(os.environ.get('ECOFLOT_DELIVERY_POLL_SECONDS', '30')))
    deadline = time.monotonic() + wait_seconds
    attempts = 0
    while True:
        rows = sheet_rows(SHEET_ID, '\u0417\u0430\u044f\u0432\u043a\u0438', 'L,M,U,V')
        delivery = audit_delivery(rows, expected, current_ids)
        attempts += 1
        delivery['reconcile_attempts'] = attempts
        if delivery.get('ok') or not current_ids or time.monotonic() >= deadline:
            return rows, delivery
        remaining = max(0, int(deadline - time.monotonic()))
        print('DELIVERY_WAIT', json.dumps({
            'attempt': attempts,
            'pending': delivery.get('pending', 0),
            'remaining_seconds': remaining,
        }), flush=True)
        time.sleep(min(interval, max(1, remaining)))


def send_cycle_notice(state):
    """Send one concise Telegram summary so a completed search is never silent."""
    if os.environ.get('ECOFLOT_NOTIFY_SUMMARY', '1') == '0':
        return
    totals = state.get('totals', {})
    unchecked = totals.get('unchecked_sources', []) or []
    status = state.get('status', 'UNKNOWN')
    icon = '✅' if status == 'COMPLETE' else '⚠️'
    message = (
        f"{icon} ECOFLOT: поиск завершён\n"
        f"Цикл: {state.get('cycleKey', '-')}\n"
        f"Режим: {state.get('search_mode', '-')}\n"
        f"Статус: {status}\n"
        f"Новых заявок: {totals.get('new', 0)}\n"
        f"Принято: {totals.get('accepted', 0)}\n"
        f"Ошибок источников: {totals.get('errors', 0)}\n"
        f"Недоступных групп/поисков: {len(unchecked)}"
    )
    if status == 'SEARCH_PARTIAL':
        message += "\nЧасть источников не отработала полностью."
    try:
        from internet_leads_monitor import send_notify_only
        send_notify_only(message, user_agent='ECOFLOT-Cycle-Summary/1.0', attempts=2)
        state['cycle_notice'] = 'sent'
    except Exception as exc:
        state['cycle_notice'] = 'error: ' + str(exc)
        print('CYCLE_NOTICE_ERROR', str(exc), flush=True)


def main():
    cycle = os.environ.get('ECOFLOT_CYCLE_KEY', '').strip() or cycle_key()
    extra = os.environ.get('ECOFLOT_FORCE') == '1'
    if extra:
        cycle += ' EXTRA ' + run_id()
    history = load_json(HISTORY_FILE, {'cycles': {}})
    previous = history['cycles'].get(cycle)
    retry_failed = previous and previous.get('status') == 'SEARCH_FAILED' and previous.get('attempts', 1) < 2
    retry_partial = (previous and previous.get('status') == 'SEARCH_PARTIAL'
                     and os.environ.get('ECOFLOT_RETRY_PARTIAL') == '1'
                     and previous.get('attempts', 1) < 2)
    if previous and previous.get('status') in TERMINAL and not retry_failed and not retry_partial:
        print('CYCLE_ALREADY_RECORDED', cycle, previous['status'], flush=True)
        # Repeated cron wake-ups do not repeat POSTs or pretend a failed slot passed.
        return exit_code(previous['status'])
    state = {'attempts': (previous or {}).get('attempts', 0) + 1, 'schema_version': 2, 'cycleKey': cycle, 'run_id': run_id(),
             'started_at': datetime.now(MSK).isoformat(), 'status': 'STARTED', 'contours': {}}
    if retry_partial:
        state['retrying_partial_from'] = previous.get('run_id')
    atomic_json(STATE_FILE, state)
    env = os.environ.copy()
    mode = 'Deep' if ' 08:00' in cycle else 'Standard'
    env.update(ECOFLOT_CYCLE_KEY=cycle, ECOFLOT_RUN_ID=run_id(),
               ECOFLOT_SEARCH_MODE=mode, SUPPRESS_NO_RESULTS='1', ECOFLOT_ORCHESTRATED='1')
    state['search_mode'] = mode
    state['preflight_errors'] = []
    expected = set()
    try:
        expected = active_chats(sheet_rows(SHEET_ID, '\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438 \u0431\u043e\u0442\u0430', 'A,E'))
        if not expected:
            raise RuntimeError('NO_VERIFIED_RECIPIENTS')
        env['ECOFLOT_EXPECTED_CHATS'] = ','.join(sorted(expected))
        os.environ['ECOFLOT_EXPECTED_CHATS'] = env['ECOFLOT_EXPECTED_CHATS']
    except Exception as exc:
        state['preflight_errors'].append(str(exc))
    state['expected_recipient_count'] = len(expected)
    state['expected_chats'] = sorted(expected)
    for name, scripts, state_paths, timeout in CONTOURS:
        print('START_CONTOUR', name, cycle, flush=True)
        codes = []
        previous_contour = (previous or {}).get('contours', {}).get(name, {})
        if retry_partial and previous_contour.get('status') == 'ok':
            result = copy.deepcopy(previous_contour)
            result['reused_from_previous_attempt'] = True
            state['contours'][name] = result
            atomic_json(STATE_FILE, state)
            print('REUSE_CONTOUR', name, 'previous attempt already complete', flush=True)
            continue
        if state['preflight_errors']:
            result = {key: 0 for key in ('new', 'duplicates', 'accepted', 'sent', 'delivery_pending')}
            result.update(status='error', errors=1, unchecked_sources=[name + ': preflight failed'],
                          error_details=list(state['preflight_errors']), exit_codes=[], state_found=False)
            state['contours'][name] = result
            atomic_json(STATE_FILE, state)
            continue
        for script in scripts:
            try:
                result = subprocess.run(['python3', '-u', 'scripts/search_runtime.py', script], env=env, timeout=timeout)
                codes.append(result.returncode)
            except (subprocess.TimeoutExpired, OSError) as exc:
                print('CONTOUR_ERROR', script, str(exc), flush=True)
                codes.append(124)
        result = aggregate(state_paths, cycle, run_id())
        result['exit_codes'] = codes
        if any(codes):
            result['status'] = 'error'
        if name == 'Telegram/MAX/VK':
            result['unchecked_sources'].append('VK: no primary-post collector configured')
            if result['status'] == 'ok':
                result['status'] = 'partial'
        state['contours'][name] = result
        atomic_json(STATE_FILE, state)
        print('END_CONTOUR', name, json.dumps(result, ensure_ascii=False), flush=True)
    state['search_finished_at'] = datetime.now(MSK).isoformat()
    state['totals'] = {key: sum(x.get(key, 0) for x in state['contours'].values())
                       for key in ('new', 'duplicates', 'accepted', 'sent', 'delivery_pending', 'errors')}
    state['totals']['unchecked_sources'] = sorted({s for x in state['contours'].values()
                                                  for s in x.get('unchecked_sources', [])})
    receipts = load_json(RECEIPTS, {'items': {}}).get('items', {})
    current_ids = {rid for rid, item in receipts.items() if item.get('run_id') == run_id()}
    try:
        rows, state['delivery'] = reconcile_delivery(expected, current_ids)
        state['backlog'] = audit_delivery(rows, expected)
        state['delivery']['mode'] = 'read-only-sheet-reconciliation'
    except Exception as exc:
        state['delivery'] = {'ok': False, 'error': str(exc), 'pending': len(current_ids)}
    statuses = {x['status'] for x in state['contours'].values()}
    state['status'] = ('SEARCH_FAILED' if 'error' in statuses or state['preflight_errors'] else
                       'SEARCH_PARTIAL' if 'partial' in statuses else
                       'DELIVERY_PENDING' if not state['delivery']['ok'] else 'COMPLETE')
    state['finished_at'] = datetime.now(MSK).isoformat()
    send_cycle_notice(state)
    atomic_json(STATE_FILE, state)
    history['cycles'][cycle] = state
    history['cycles'] = dict(list(history['cycles'].items())[-120:])
    atomic_json(HISTORY_FILE, history)
    summary = '# ECOFLOT '+cycle+'\n\nStatus: **'+state['status']+'**\n\n'
    summary += '| Contour | Status | New | Duplicates | Errors |\n|---|---|---:|---:|---:|\n'
    for name, values in state['contours'].items():
        summary += f"| {name} | {values['status']} | {values['new']} | {values['duplicates']} | {values['errors']} |\n"
    summary += '\nDelivery: `'+json.dumps(state['delivery'])+'`\n'
    summary += '\nUnverified sources: '+ '; '.join(state['totals']['unchecked_sources'])+'\n'
    Path('search_cycle_report.md').write_text(summary, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(summary)
    print('FULL_CYCLE_STATE', json.dumps(state, ensure_ascii=False), flush=True)
    return exit_code(state['status'])


if __name__ == '__main__':
    raise SystemExit(main())
