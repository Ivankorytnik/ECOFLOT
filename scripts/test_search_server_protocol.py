import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import search_reliability as r
from search_runtime import strict_acknowledged, audit_delivery, configured_worker
from server_protocol import verified_alias, remember_alias, canonical_request_ids, receipt_target
from scheduled_cycle_runner import refreshed_state


class ServerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.receipts = Path(self.tmp.name) / 'receipts.json'
        self.patches = [patch.object(r, 'RECEIPTS', self.receipts),
                        patch.dict(os.environ, {'ECOFLOT_RUN_ID': 'protocol.test'})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def response(self, **changes):
        data = dict(version='2026-10-07-server-v5.1', ok=True, saved=True, created=False,
                    duplicate=True, requestId='WEB-INCOMING', requestedRequestId='WEB-INCOMING',
                    canonicalRequestId='WEB-CANONICAL', duplicateReason='specific_link',
                    duplicateRow=42, callbackKey='v5_callback', routes=[], telegramSent=False,
                    telegramQueued=True)
        data.update(changes)
        return data

    def store(self):
        r.atomic_json(self.receipts, {'items': {'WEB-INCOMING': {'run_id': 'protocol.test',
                      'duplicate': True, 'status': 'PENDING_VERIFICATION'}}})
        remember_alias('WEB-INCOMING', self.response(), r)

    def test_alias_acknowledged_but_not_delivered(self):
        self.assertTrue(strict_acknowledged(self.response(), 'WEB-INCOMING'))
        self.assertFalse(r.delivery_confirmed(self.response(), {'11', '22'}))

    def test_legacy_link_without_identity_rejected(self):
        self.assertFalse(strict_acknowledged(dict(ok=True, duplicate=True,
                         duplicateReason='link', duplicateRow=42), 'WEB-INCOMING'))

    def test_legacy_exact_id_still_accepted(self):
        self.assertTrue(strict_acknowledged(dict(ok=True, duplicate=True,
                        requestId='A', duplicateReason='request_id'), 'A'))

    def test_missing_each_contract_field_rejected(self):
        for field in ('version', 'saved', 'created', 'requestId', 'requestedRequestId',
                      'duplicateReason', 'duplicateRow', 'callbackKey', 'canonicalRequestId'):
            data = self.response()
            del data[field]
            with self.subTest(field=field):
                self.assertIsNone(verified_alias(data, 'WEB-INCOMING'))

    def test_wrong_id_rejected(self):
        self.assertFalse(strict_acknowledged(self.response(requestId='OTHER'), 'WEB-INCOMING'))

    def test_filtered_response_not_saved(self):
        self.assertFalse(strict_acknowledged(self.response(filtered=True), 'WEB-INCOMING'))

    def test_bad_rows_rejected(self):
        for row in (None, True, 0, 1, '42', 42.5):
            self.assertIsNone(verified_alias(self.response(duplicateRow=row), 'WEB-INCOMING'))

    def test_phone_fuzzy_category_not_identity(self):
        for reason in ('phone', 'object_text', 'link'):
            self.assertIsNone(verified_alias(self.response(duplicateReason=reason), 'WEB-INCOMING'))

    def test_alias_mapping_stored_without_fake_delivery(self):
        self.store()
        self.assertEqual(canonical_request_ids({'WEB-INCOMING'}, r), {'WEB-CANONICAL'})
        self.assertEqual(r.load_json(self.receipts)['items']['WEB-INCOMING']['status'], 'PENDING_VERIFICATION')

    def test_missing_current_receipt_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'CURRENT_RECEIPT'):
            remember_alias('WEB-INCOMING', self.response(), r)

    def test_conflict_not_upgraded(self):
        self.store()
        item = r.load_json(self.receipts)['items']['WEB-INCOMING']
        item['status'] = 'IDENTITY_CONFLICT'
        self.assertEqual(receipt_target('WEB-INCOMING', item), 'WEB-INCOMING')

    def test_delivery_resolves_alias_requires_all_routes(self):
        self.store()
        rows = [['WEB-CANONICAL', json.dumps([{'chatId': '11', 'messageId': '100'}]), 'cb', 'SENT']]
        self.assertTrue(audit_delivery(rows, {'11'}, {'WEB-INCOMING'})['ok'])
        self.assertFalse(audit_delivery(rows, {'11', '22'}, {'WEB-INCOMING'})['ok'])

    def test_untrusted_mapping_cannot_hide_missing(self):
        r.atomic_json(self.receipts, {'items': {'WEB-INCOMING': {'canonicalRequestId': 'WEB-CANONICAL'}}})
        self.assertEqual(audit_delivery([['WEB-CANONICAL', '[]', 'cb', 'SENT']], {'11'},
                                       {'WEB-INCOMING'})['missing_records'], 1)

    def test_worker_records_versioned_alias(self):
        with configured_worker('internet_leads_monitor') as module:
            module.record_lead_result('WEB-INCOMING', self.response(), 'Internet Leads')
        self.assertEqual(r.load_json(self.receipts)['items']['WEB-INCOMING']['canonicalRequestId'], 'WEB-CANONICAL')

    def test_late_reconciliation_no_false_unresolved_alias(self):
        self.store()
        state = dict(run_id='protocol.test', status='DELIVERY_PENDING', totals={'accepted': 1})
        rows = [['WEB-CANONICAL', json.dumps([{'chatId': '11', 'messageId': '100'}]), 'cb', 'SENT']]
        result = refreshed_state(state, rows, {'11'}, r.load_json(self.receipts)['items'], audit_delivery)
        self.assertEqual(result['delivery']['unresolved_duplicate_references'], 0)
        self.assertEqual(result['status'], 'COMPLETE')

    def test_no_service_record_alias(self):
        for value in ('TEST-1', 'CRM_ACTION_X', 'A\nB'):
            self.assertIsNone(verified_alias(self.response(canonicalRequestId=value), 'WEB-INCOMING'))


if __name__ == '__main__':
    unittest.main()
