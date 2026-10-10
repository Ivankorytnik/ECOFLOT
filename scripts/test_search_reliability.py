import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import search_reliability as r
import internet_leads_monitor as internet
import tender_monitor as tender
import full_cycle_orchestrator as cycle


class SafetyContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'ECOFLOT_CYCLE_KEY': '2026-10-07 14:00', 'ECOFLOT_RUN_ID': 'test.1', 'ECOFLOT_EXPECTED_CHATS': '11,22'})
        self.env.start()
        self.receipts = patch.object(r, 'RECEIPTS', self.root/'receipts.json')
        self.receipts.start()
        for key in r.STATS:
            r.STATS[key] = 0

    def tearDown(self):
        self.receipts.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_before_eight_previous_day(self):
        self.assertEqual(r.scheduled_cycle(datetime(2026,10,1,7,59,tzinfo=r.MSK)), '2026-09-30 18:00')

    def test_slots(self):
        for hour, expected in [(8,8),(13,8),(14,14),(17,14),(18,18),(23,18)]:
            with self.subTest(hour=hour):
                self.assertEqual(r.scheduled_cycle(datetime(2026,10,7,hour,tzinfo=r.MSK)), f'2026-10-07 {expected:02d}:00')

    def test_health_is_not_write(self):
        self.assertFalse(r.acknowledged({'ok':True,'service':'ECOFLOT bridge','version':'2026-09-multiuser-v4'}, 'x'))
        with self.assertRaises(RuntimeError):
            r.record_lead_result('x', {'ok':True,'service':'ECOFLOT bridge'}, 'test')
        self.assertFalse((self.root/'receipts.json').exists())

    def test_duplicate_is_not_delivery(self):
        self.assertFalse(internet.telegram_delivery_confirmed({'ok':True,'duplicate':True}))
        r.record_lead_result('x', {'ok':True,'duplicate':True}, 'test')
        self.assertEqual(r.STATS['created'],0)
        self.assertEqual(r.STATS['delivery_pending'],1)

    def test_count_is_not_receipt(self):
        self.assertFalse(r.delivery_confirmed({'ok':True,'telegramSent':3}))

    def test_partial_routes_not_complete(self):
        self.assertFalse(r.delivery_confirmed({'ok':True,'routes':[{'chatId':'11','messageId':'1'}]}))

    def test_all_recipient_routes(self):
        self.assertTrue(r.delivery_confirmed({'ok':True,'routes':[{'chatId':'11','messageId':'1'},{'chatId':'22','messageId':'2'}]}))

    def test_invalid_combined_chat_rejected(self):
        self.assertEqual(r.routes_from([{'chatId':'11,22','messageId':'1'}]), [])

    def test_wrong_id_rejected(self):
        self.assertFalse(r.acknowledged({'ok':True,'requestId':'wrong'}, 'x'))

    def test_corrupt_state_fails_closed(self):
        path = self.root/'bad.json'
        path.write_text('{broken')
        with patch.object(internet,'STATE_PATH',path):
            with self.assertRaises(ValueError):
                internet.load_state()

    def test_atomic_roundtrip(self):
        path = self.root/'state.json'
        r.atomic_json(path, {'sent':{'x':'date'}})
        self.assertEqual(r.load_json(path)['sent'], {'x':'date'})
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_fresh_state_required(self):
        path = self.root/'state.json'
        r.atomic_json(path, {'last_run':{'cycleKey':'2026-10-07 08:00','run_id':'old','sent':99}})
        values = r.aggregate([path], '2026-10-07 14:00', 'test.1')
        self.assertFalse(values['state_found'])
        self.assertEqual(values['sent'],0)

    def test_all_expected_states_required(self):
        path = self.root/'state.json'
        r.atomic_json(path, {'last_run':{'cycleKey':'2026-10-07 14:00','run_id':'test.1','new':2}})
        values = r.aggregate([path,self.root/'missing.json'], '2026-10-07 14:00', 'test.1')
        self.assertEqual(values['status'],'error')

    def test_source_errors_are_partial(self):
        path = self.root/'state.json'
        r.atomic_json(path, {'last_run':{'cycleKey':'2026-10-07 14:00','run_id':'test.1','errors':4}})
        self.assertEqual(r.aggregate([path], '2026-10-07 14:00','test.1')['status'],'partial')

    def test_unverified_source_not_success(self):
        path = self.root/'state.json'
        r.atomic_json(path, {'last_run':{'cycleKey':'2026-10-07 14:00','run_id':'test.1','unverified_sources':['MAX']}})
        self.assertEqual(r.aggregate([path], '2026-10-07 14:00','test.1')['status'],'partial')

    def test_remaining_candidates_not_duplicates(self):
        path = self.root/'state.json'
        r.atomic_json(path, {'last_run':{'cycleKey':'2026-10-07 14:00','run_id':'test.1','candidates':99,'sent':2}})
        self.assertEqual(r.aggregate([path], '2026-10-07 14:00','test.1')['duplicates'],0)

    def test_ordinary_contact_placeholder_rejected(self):
        item = {'phone':'-', 'url':'https://example.com/request/12'}
        self.assertFalse(internet.ensure_public_contact(item)[0])

    def test_distinct_orders_same_phone_not_collapsed(self):
        self.assertEqual(internet.contact_dedupe_keys({'phone':'+79999999999'}), [])

    def test_profi_listing_not_treated_as_direct_card(self):
        item = {'phone':'-', 'url':'https://profi.ru/rabota/remont/test/', 'request_id':'WEB-PROFI-'+'a'*20, 'source':'Profi', 'description':'A specific customer demand with individual requirements', 'location':'Moscow', 'date':'\u0441\u0435\u0433\u043e\u0434\u043d\u044f'}
        self.assertFalse(internet.ensure_public_contact(item)[0])
        self.assertTrue(internet.is_listing_url_for_dedupe(item))

    def test_generic_profi_category_not_allowed(self):
        self.assertFalse(internet.ensure_public_contact({'url':'https://profi.ru/rabota/remont/test/'})[0])

    def test_profi_individual_response_route_allowed(self):
        url='https://profi.ru/backoffice/n.php?o=12345678'
        self.assertTrue(internet.is_verified_order_route(url))
        item={'url':url,'source':'Профи.ру','phone':'-'}
        self.assertTrue(internet.ensure_public_contact(item)[0])
        self.assertFalse(internet.is_listing_url_for_dedupe(item))

    def test_spectehinfo_individual_request_route_allowed(self):
        url='https://mosobl.spectehinfo.ru/zayavki/arenda/samosvaly/b264943'
        self.assertTrue(internet.is_verified_order_route(url))
        item={'url':url,'source':'СПЕЦТЕХНИКА-ИНФО','phone':'-'}
        self.assertTrue(internet.ensure_public_contact(item)[0])
        self.assertFalse(internet.is_listing_url_for_dedupe(item))

    def test_spectehinfo_listing_is_not_direct_route(self):
        self.assertFalse(internet.is_verified_order_route('https://mosobl.spectehinfo.ru/arenda/samosvaly/po_oblasti'))

    def test_unknown_date_rejected(self):
        self.assertFalse(internet.is_recent('current'))

    def test_future_date_rejected(self):
        self.assertFalse(internet.is_recent((datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y-%m-%d')))

    def test_catalog_tender_link_rejected(self):
        self.assertFalse(tender.valid_tender_card_link({'link':'https://gentender.ru/search?q=32616443194'}))

    def test_specific_eis_card_allowed(self):
        self.assertTrue(tender.valid_tender_card_link({'link':'https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0373200300226000008'}))

    def test_parts_not_service(self):
        self.assertFalse(r.tender_service_demand('\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0410\u041a\u041f\u041f \u0434\u043b\u044f \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b\u0430'))
        self.assertFalse(r.tender_service_demand('\u0417\u0430\u043a\u0443\u043f\u043a\u0430 \u0437\u0430\u043f\u0447\u0430\u0441\u0442\u0435\u0439 \u0434\u043b\u044f \u043f\u043e\u0433\u0440\u0443\u0437\u0447\u0438\u043a\u0430'))

    def test_snow_service_allowed(self):
        self.assertTrue(r.tender_service_demand('\u041f\u043e\u0433\u0440\u0443\u0437\u043a\u0430 \u0438 \u0432\u044b\u0432\u043e\u0437 \u0441\u043d\u0435\u0433\u0430'))

    def test_deadline_parsing(self):
        now=datetime(2026,10,7,16,tzinfo=r.MSK)
        self.assertGreater(r.parse_deadline('14.10.2026 10:00',now), now)
        self.assertLessEqual(r.parse_deadline('07.10.2026',now), now)
        self.assertLess(r.parse_deadline('06.10.2026',now), now)
        self.assertIsNone(r.parse_deadline('active',now))

    def test_sheet_error_does_not_look_empty(self):
        with self.assertRaises(RuntimeError):
            r.sheet_rows('id','sheet','A',lambda _: '{"status":"error","errors":[]}')

    def test_blocked_recipient_excluded(self):
        self.assertEqual(r.active_chats([['11','approved'],['11','blocked'],['22','approved']]), {'22'})

    def test_backlog_reconciles_real_routes(self):
        rows=[['a',json.dumps([{'chatId':'11','messageId':'1'},{'chatId':'22','messageId':'2'}]),'key','SENT'],['b','[]','key2','SENT']]
        result=r.audit_delivery(rows,{'11','22'},{'a','b','c'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['confirmed'],1)
        self.assertEqual(result['pending'],2)
        self.assertEqual(result['missing_records'],1)

    def test_partial_slot_is_warning_not_crash(self):
        self.assertEqual(cycle.exit_code('SEARCH_PARTIAL'),0)
        self.assertEqual(cycle.exit_code('COMPLETE'),0)
        self.assertEqual(cycle.exit_code('DELIVERY_PENDING'),1)
        self.assertEqual(cycle.exit_code('SEARCH_FAILED'),1)

if __name__ == '__main__':
    unittest.main()
