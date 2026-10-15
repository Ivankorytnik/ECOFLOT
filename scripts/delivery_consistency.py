"""Read-only reconciliation of actual Telegram receipts. Never sends messages."""
from __future__ import annotations
from datetime import datetime, timezone
import re
from search_reliability import routes_from
from server_protocol import receipt_target

SERVICE = re.compile(r'^(CRM_ACTION_|CRM-BULK-ACTION|TEST[-_])', re.I)

def confirmed_routes(rows, expected_chats):
    expected = {str(value) for value in expected_chats}
    if not expected:
        return {}
    confirmed = {}
    for row in rows:
        rid, value, _, status = (list(row) + [''] * 4)[:4]
        rid = str(rid or '')
        if not rid or SERVICE.match(rid) or str(status).strip().upper() != 'SENT':
            continue
        routes = routes_from(value)
        if expected.issubset({route['chatId'] for route in routes}):
            confirmed[rid] = routes
    return confirmed

def mark_confirmed_receipts(receipts, rows, expected_chats, at=None):
    """Persist only positive evidence. Missing/ambiguous records stay unresolved."""
    confirmed = confirmed_routes(rows, expected_chats)
    stamp = at or datetime.now(timezone.utc).isoformat()
    changed = 0
    for rid, item in receipts.items():
        if not isinstance(item, dict) or SERVICE.match(str(rid)):
            continue
        if item.get('accepted') is False or item.get('status') in ('IDENTITY_CONFLICT', 'SUPPRESSED'):
            continue
        target = receipt_target(rid, item)
        if target not in confirmed:
            continue
        routes = confirmed[target]
        if item.get('status') != 'DELIVERED' or item.get('verified_routes') != routes:
            item.update(status='DELIVERED', verified_at=stamp, verified_routes=routes,
                        verified_expected_chats=sorted(str(c) for c in expected_chats),
                        evidence='sheet:SENT+telegram-message-ids')
            changed += 1
    return changed

def update_totals_after_reconciliation(totals, delivery, missing_receipts=0):
    """Keep latest-attempt totals separate from the whole logical slot."""
    if delivery.get('error'):
        return totals
    confirmed = max(0, int(delivery.get('confirmed', 0) or 0))
    pending = max(0, int(delivery.get('pending', 0) or 0)) + max(0, int(missing_receipts or 0))
    totals.update(sent=confirmed, delivery_pending=pending,
                  confirmed_after_reconciliation=confirmed,
                  pending_after_reconciliation=pending)
    return totals

def slot_delivery_summary(cycle_key, receipts, rows, expected, audit):
    """Count distinct accepted IDs from ALL attempts, not just the last retry."""
    items = {rid: item for rid, item in receipts.items()
             if isinstance(item, dict) and item.get('cycleKey') == cycle_key
             and item.get('accepted') is not False
             and item.get('status') not in ('IDENTITY_CONFLICT', 'SUPPRESSED')
             and not SERVICE.match(str(rid))}
    delivery = audit(rows, expected, set(items))
    return dict(accepted=len(items), new=sum(item.get('duplicate') is not True for item in items.values()),
                confirmed=delivery.get('confirmed', 0), pending=delivery.get('pending', 0),
                missing_records=delivery.get('missing_records', 0), ok=delivery.get('ok', False),
                scope='all-attempts-in-logical-slot')
