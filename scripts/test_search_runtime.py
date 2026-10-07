import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import search_reliability as reliability
import search_runtime as runtime
import internet_leads_monitor as internet
import full_cycle_orchestrator as coordinator


class RuntimeTests(unittest.TestCase):
    def test_context_restores_bindings(self):
        original = internet.discovery_result_urls
        record = reliability.record_lead_result
        ack = reliability.acknowledged
        with runtime.configured_worker('internet_leads_monitor'):
            self.assertIsNot(internet.discovery_result_urls, original)
            self.assertIsNot(reliability.record_lead_result, record)
        self.assertIs(internet.discovery_result_urls, original)
        self.assertIs(reliability.record_lead_result, record)
        self.assertIs(reliability.acknowledged, ack)

    def test_bad_worker_never_imported(self):
        for args in (['os.py'], ['../tender_monitor.py'], [], ['a.py', 'b.py']):
            with self.assertRaises(ValueError):
                runtime.main(args)

    def test_discovery_circuit_bounds_requests(self):
        fetch = Mock(side_effect=TimeoutError('offline'))
        session = runtime.DiscoverySession(fetch)
        for i in range(25):
            with self.assertRaises(runtime.UnverifiedSearch):
                session.search(str(i))
        self.assertEqual(fetch.call_count, 6)

    def test_discovery_verified_zero(self):
        fetch = Mock(return_value='no results found')
        self.assertEqual(runtime.DiscoverySession(fetch).search('x'), [])

    def test_discovery_budget_prevents_io(self):
        fetch = Mock()
        with self.assertRaises(runtime.UnverifiedSearch):
            runtime.DiscoverySession(fetch, budget=0).search('x')
        fetch.assert_not_called()

    def test_budget_exhaustion_after_valid_zero(self):
        fetch = Mock(return_value='no results found')
        session = runtime.DiscoverySession(fetch, budget=2)
        with patch('search_runtime.time.monotonic', side_effect=[0, 3]):
            self.assertEqual(session.search('x'), [])
        self.assertEqual(fetch.call_count, 1)

    def test_archived_record_not_retry_backlog(self):
        result = runtime.audit_delivery([['A', '', 'k', 'IGNORED']], {'11'})
        self.assertEqual(result['suppressed'], 1)
        self.assertEqual(result['confirmed'], 0)
        self.assertEqual(result['pending'], 0)

    def test_service_row_not_lead(self):
        result = runtime.audit_delivery([['CRM_ACTION_12', '', '', '']], {'11'})
        self.assertEqual(result['service_rows'], 1)
        self.assertEqual(result['checked'], 0)

    def test_routes_without_sent_are_not_complete(self):
        routes = json.dumps([{'chatId': '11', 'messageId': '42'}])
        self.assertFalse(runtime.audit_delivery([['A', routes, 'k', 'PENDING']], {'11'})['ok'])
        self.assertTrue(runtime.audit_delivery([['A', routes, 'k', 'SENT']], {'11'})['ok'])

    def test_missing_recipients_stop_all_workers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(coordinator, 'STATE_FILE', root/'state.json'), \
                 patch.object(coordinator, 'HISTORY_FILE', root/'history.json'), \
                 patch.object(coordinator, 'RECEIPTS', root/'receipts.json'), \
                 patch.object(coordinator, 'sheet_rows', return_value=[]), \
                 patch.object(coordinator.subprocess, 'run') as execute, \
                 patch.object(coordinator.Path, 'write_text'), \
                 patch.dict(os.environ, {'ECOFLOT_FORCE': '0', 'ECOFLOT_CYCLE_KEY': '2026-10-07 18:00'}):
                # Patching Path.write_text does not affect atomic_json.
                self.assertEqual(coordinator.main(), 1)
                execute.assert_not_called()
                self.assertEqual(reliability.load_json(root/'state.json')['status'], 'SEARCH_FAILED')

    def test_specific_b2b_number_is_not_catalogue(self):
        with runtime.configured_worker('tender_monitor') as tender:
            entry = {'id':'0848300046026000544','link':'https://www.b2b-center.ru/search/number/l0848300046026000544-1/'}
            self.assertTrue(tender.valid_tender_card_link(entry))

    def test_catalogue_resolution_is_bounded(self):
        with runtime.configured_worker('tender_monitor') as tender, patch.object(tender, 'fetch', return_value='<html>Login</html>') as fetch:
            for i in range(20):
                rid = str(1000000000000000000+i)
                entry = {'id':rid, 'link':'https://gentender.ru/search?q='+rid, 'title':'Concrete tender title'}
                self.assertFalse(tender.valid_tender_card_link(entry))
            self.assertEqual(fetch.call_count, 12)

    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_server_guards_node(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/server_guards.test.js'], cwd=root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
