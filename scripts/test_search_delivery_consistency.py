import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import search_reliability as r
import full_cycle_orchestrator as coordinator
from delivery_consistency import confirmed_routes, mark_confirmed_receipts, update_totals_after_reconciliation, slot_delivery_summary
from scheduled_cycle_runner import refreshed_state

class DeliveryConsistencyTests(unittest.TestCase):
    def rows(self, status='SENT'):
        return [['A', json.dumps([{'chatId':'11','messageId':'101'},{'chatId':'22','messageId':'102'}]), 'key', status]]

    def test_all_recipients_required(self):
        self.assertEqual(set(confirmed_routes(self.rows(), {'11','22'})), {'A'})
        self.assertEqual(confirmed_routes(self.rows(), {'11','22','33'}), {})

    def test_no_recipients_cannot_confirm(self):
        self.assertEqual(confirmed_routes(self.rows(), set()), {})

    def test_not_sent_cannot_confirm(self):
        for status in ('PENDING','FAILED','IGNORED',''):
            self.assertEqual(confirmed_routes(self.rows(status), {'11','22'}), {})

    def test_invalid_message_id_cannot_confirm(self):
        rows = [['A', '[{"chatId":"11","messageId":"0"}]', 'key', 'SENT']]
        self.assertEqual(confirmed_routes(rows, {'11'}), {})

    def test_mark_preserves_identity_and_attempt(self):
        item = {'run_id':'old.1','cycleKey':'2026-10-14 08:00','first_seen_at':'original','status':'PENDING_VERIFICATION'}
        ledger = {'A':copy.deepcopy(item)}
        self.assertEqual(mark_confirmed_receipts(ledger, self.rows(), {'11','22'}, 'verified'), 1)
        self.assertEqual(ledger['A']['run_id'], 'old.1')
        self.assertEqual(ledger['A']['first_seen_at'], 'original')
        self.assertEqual(ledger['A']['status'], 'DELIVERED')
        self.assertEqual(len(ledger['A']['verified_routes']), 2)
        self.assertEqual(mark_confirmed_receipts(ledger, self.rows(), {'11','22'}, 'later'), 0)

    def test_conflicts_and_unaccepted_not_marked(self):
        for item in ({'status':'IDENTITY_CONFLICT'}, {'status':'SUPPRESSED'}, {'accepted':False}):
            ledger={'A':dict(item)}
            self.assertEqual(mark_confirmed_receipts(ledger, self.rows(), {'11','22'}), 0)
            self.assertEqual(ledger['A'], item)

    def test_service_rows_not_deliveries(self):
        rows=self.rows()
        rows[0][0]='CRM-BULK-ACTION-1'
        self.assertEqual(confirmed_routes(rows, {'11','22'}), {})

    def test_counters_updated_without_changing_source_errors(self):
        totals={'new':3,'accepted':3,'sent':0,'delivery_pending':3,'errors':42}
        update_totals_after_reconciliation(totals, {'confirmed':3,'pending':0})
        self.assertEqual((totals['sent'],totals['delivery_pending'],totals['errors']), (3,0,42))

    def test_unknown_delivery_not_zero(self):
        totals={'sent':1,'delivery_pending':2}
        update_totals_after_reconciliation(totals, {'error':'read failed'})
        self.assertEqual(totals, {'sent':1,'delivery_pending':2})

    def test_missing_ledger_is_pending(self):
        totals={}
        update_totals_after_reconciliation(totals, {'confirmed':0,'pending':0}, 2)
        self.assertEqual(totals['delivery_pending'], 2)

    def test_entire_slot_keeps_first_attempt(self):
        receipts={'A':{'cycleKey':'slot','run_id':'first'},'B':{'cycleKey':'slot','run_id':'second'},'C':{'cycleKey':'other'}}
        def audit(rows, expected, ids):
            return {'confirmed':len(ids),'pending':0,'missing_records':0,'ok':bool(expected)}
        result=slot_delivery_summary('slot', receipts, [], {'11'}, audit)
        self.assertEqual((result['new'],result['accepted'],result['confirmed']), (2,2,2))

    def test_reconciled_delivery_does_not_hide_partial_search(self):
        previous={'cycleKey':'slot','run_id':'second','status':'SEARCH_PARTIAL','totals':{'new':1,'accepted':1,'sent':0,'delivery_pending':1,'errors':5}}
        receipts={'A':{'cycleKey':'slot','run_id':'first'},'B':{'cycleKey':'slot','run_id':'second'}}
        def audit(rows, expected, ids=None):
            return {'confirmed':len(ids or []),'pending':0,'missing_records':0,'ok':True}
        result=refreshed_state(previous, [['A'],['B']], {'11'}, receipts, audit)
        self.assertEqual(result['status'], 'SEARCH_PARTIAL')
        self.assertEqual(result['totals']['sent'], 1)
        self.assertEqual(result['slot_delivery']['confirmed'], 2)
        self.assertEqual(previous['totals']['sent'], 0)

    def test_no_unverified_recipients_no_summary_post(self):
        state={'expected_chats':[],'totals':{}}
        with patch.dict(os.environ, {'ECOFLOT_NOTIFY_SUMMARY':'1'}), patch('internet_leads_monitor.send_structured_cycle_report') as send:
            coordinator.send_cycle_notice(state)
            send.assert_not_called()

    def test_user_approved_contact_exceptions_preserved(self):
        import internet_leads_monitor as internet
        self.assertIn('profi.ru', internet.CONTACT_GATED_ALLOWED_DOMAINS)
        self.assertIn('vezetvsem.ru', internet.CONTACT_GATED_ALLOWED_DOMAINS)

if __name__ == '__main__':
    unittest.main()
