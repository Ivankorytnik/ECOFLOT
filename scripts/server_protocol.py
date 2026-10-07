"""Versioned server identity acknowledgements, never inferred Telegram delivery."""
from __future__ import annotations
import re

VERSION = '2026-10-07-server-v5.1'
REASONS = ('specific_link', 'procurement_id')


def verified_alias(response, requested_id):
    if not isinstance(response, dict):
        return None
    rid = str(requested_id)
    canonical = str(response.get('canonicalRequestId') or '').strip()
    row = response.get('duplicateRow')
    if not (type(row) is int and row >= 2):
        return None
    valid = (
        response.get('version') == VERSION and response.get('ok') is True
        and response.get('saved') is True and response.get('created') is False
        and response.get('duplicate') is True and response.get('filtered') is not True
        and response.get('requestId') == rid and response.get('requestedRequestId') == rid
        and response.get('duplicateReason') in REASONS
        and str(response.get('callbackKey') or '').strip()
        and canonical and len(canonical) <= 200
        and not re.search(r'[\r\n\x00]', canonical)
        and not re.match(r'^(TEST[-_]|CRM_ACTION_|CRM-BULK-ACTION)', canonical, re.I)
    )
    return canonical if valid else None


def receipt_target(request_id, item):
    canonical = str(item.get('canonicalRequestId') or '').strip()
    valid = (item.get('identity_confirmed') is True
             and item.get('protocol_version') == VERSION
             and item.get('identity_reason') in REASONS
             and item.get('status') != 'IDENTITY_CONFLICT'
             and canonical and len(canonical) <= 200
             and not re.search(r'[\r\n\x00]', canonical)
             and not re.match(r'^(TEST[-_]|CRM_ACTION_|CRM-BULK-ACTION)', canonical, re.I))
    return canonical if valid else str(request_id)


def remember_alias(request_id, response, reliability):
    canonical = verified_alias(response, request_id)
    if not canonical or canonical == str(request_id):
        return
    ledger = reliability.load_json(reliability.RECEIPTS, {'items': {}})
    item = ledger.get('items', {}).get(str(request_id))
    if not isinstance(item, dict) or item.get('run_id') != reliability.run_id():
        raise RuntimeError('ALIAS_ACK_MISSING_CURRENT_RECEIPT')
    item.update(canonicalRequestId=canonical, identity_confirmed=True,
                identity_reason=response['duplicateReason'], protocol_version=VERSION)
    reliability.atomic_json(reliability.RECEIPTS, ledger)


def canonical_request_ids(request_ids, reliability):
    if request_ids is None:
        return None
    items = reliability.load_json(reliability.RECEIPTS, {'items': {}}).get('items', {})
    return {receipt_target(rid, items.get(str(rid), {})) for rid in request_ids}
