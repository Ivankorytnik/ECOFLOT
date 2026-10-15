"""Apply narrowly scoped ECOFLOT fixes. No network or writes outside repository."""
from pathlib import Path

MARKER = '# ECOFLOT delivery repair 2026-10-15'

def replace_once(text, old, new, name):
    if text.count(old) != 1:
        raise RuntimeError('Unexpected source, refusing to overwrite: ' + name)
    return text.replace(old, new, 1)

def main():
    edits = {}
    path = Path('scripts/full_cycle_orchestrator.py')
    text = path.read_text('utf-8')
    if MARKER not in text:
        text = replace_once(text, 'from search_runtime import audit_delivery\n',
            'from search_runtime import audit_delivery\n' + MARKER + '\n'
            'from delivery_consistency import (mark_confirmed_receipts,\n'
            '    update_totals_after_reconciliation, slot_delivery_summary)\n', str(path))
        anchor = "        state['delivery']['mode'] = 'read-only-sheet-reconciliation'\n"
        replacement = anchor + '''        ledger = load_json(RECEIPTS, {'items': {}})
        if mark_confirmed_receipts(ledger['items'], rows, expected):
            atomic_json(RECEIPTS, ledger)
        missing = max(0, int(state['totals'].get('accepted', 0)) - len(current_ids))
        if missing:
            state['delivery'].update(ok=False, missing_receipts=missing)
        update_totals_after_reconciliation(state['totals'], state['delivery'], missing)
        state['slot_delivery'] = slot_delivery_summary(cycle, ledger['items'], rows, expected, audit_delivery)
'''
        text = replace_once(text, anchor, replacement, str(path))
        text = replace_once(text,
            "    if os.environ.get('ECOFLOT_NOTIFY_SUMMARY', '1') == '0':\n",
            "    if not state.get('expected_chats'):\n"
            "        state['cycle_notice'] = 'not-sent:no-verified-recipients'\n"
            "        return\n"
            "    if os.environ.get('ECOFLOT_NOTIFY_SUMMARY', '1') == '0':\n", str(path))
        anchor = "    if status == 'SEARCH_PARTIAL':\n"
        replacement = '''    slot = state.get('slot_delivery', {})
    if slot:
        message += ('\\nДоставлено в Telegram: ' + str(slot.get('confirmed', 0)) + '/' + str(slot.get('accepted', 0))
                    + '; ожидает: ' + str(slot.get('pending', 0))
                    + '\\nНовых за все попытки цикла: ' + str(slot.get('new', 0)))
''' + anchor
        text = replace_once(text, anchor, replacement, str(path))
        edits[path] = text

    path = Path('scripts/scheduled_cycle_runner.py')
    text = path.read_text('utf-8')
    if MARKER not in text:
        text = replace_once(text, 'from server_protocol import receipt_target\n',
            'from server_protocol import receipt_target\n' + MARKER + '\n'
            'from delivery_consistency import (mark_confirmed_receipts,\n'
            '    update_totals_after_reconciliation, slot_delivery_summary)\n', str(path))
        anchor = "    state['totals']['pending_after_reconciliation'] = delivery.get('pending', 0) + missing_receipts\n"
        text = replace_once(text, anchor, anchor + '''    update_totals_after_reconciliation(state['totals'], delivery, missing_receipts)
    state['slot_delivery'] = slot_delivery_summary(state.get('cycleKey', ''), receipts, rows, expected, audit)
''', str(path))
        anchor = "        state = refreshed_state(previous, rows, expected, receipts, coordinator.audit_delivery)\n"
        text = replace_once(text, anchor, '''        if mark_confirmed_receipts(receipts, rows, expected):
            coordinator.atomic_json(coordinator.RECEIPTS, {'items': receipts})
''' + anchor, str(path))
        anchor = '\n\ndef main():\n'
        addition = '''

def reconcile_all_history(coordinator, history):
    """Only reads Sheets and repairs local receipt/history files, never sends."""
    expected = coordinator.active_chats(coordinator.sheet_rows(
        coordinator.SHEET_ID, 'Пользователи бота', 'A,E'))
    if not expected:
        raise RuntimeError('NO_VERIFIED_RECIPIENTS')
    rows = coordinator.sheet_rows(coordinator.SHEET_ID, 'Заявки', 'L,M,U,V')
    ledger = coordinator.load_json(coordinator.RECEIPTS, {'items': {}})
    changed = mark_confirmed_receipts(ledger['items'], rows, expected)
    if changed:
        coordinator.atomic_json(coordinator.RECEIPTS, ledger)
    for key, previous in list(history.get('cycles', {}).items()):
        if previous.get('status') in coordinator.TERMINAL:
            history['cycles'][key] = refreshed_state(
                previous, rows, expected, ledger['items'], coordinator.audit_delivery)
    coordinator.atomic_json(coordinator.HISTORY_FILE, history)
    latest = coordinator.load_json(coordinator.STATE_FILE)
    if latest.get('cycleKey') in history.get('cycles', {}):
        coordinator.atomic_json(coordinator.STATE_FILE, history['cycles'][latest['cycleKey']])
    print('RECEIPT_LEDGER_REPAIRED', changed, 'SEARCH_STATUS_PRESERVED')
    return 0
'''
        text = replace_once(text, anchor, addition + anchor, str(path))
        anchor = "    history = coordinator.load_json(coordinator.HISTORY_FILE, {'cycles': {}})\n"
        text = replace_once(text, anchor, anchor + '''    if '--reconcile-all' in sys.argv[1:]:
        return reconcile_all_history(coordinator, history)
''', str(path))
        anchor = "    expression = os.environ.get('ECOFLOT_SCHEDULE', '').strip()\n"
        text = replace_once(text, anchor, anchor + '''    if (os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('ECOFLOT_FALLBACK') != '1'
            and not expression and not os.environ.get('ECOFLOT_CYCLE_KEY', '').strip()):
        os.environ['ECOFLOT_FORCE'] = '1'
''', str(path))
        edits[path] = text

    for path, text in edits.items():
        path.write_text(text, encoding='utf-8')
    print('Patched', len(edits), 'files; source/contact policy and Apps Script unchanged.')

if __name__ == '__main__':
    main()
