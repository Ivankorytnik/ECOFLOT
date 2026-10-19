import json
import unittest
from unittest.mock import patch
import search_reporting as r

class ReportingTests(unittest.TestCase):
    def state(self):
        return {'cycleKey':'2026-10-17 14:00','status':'SEARCH_PARTIAL','expected_chats':['11','22'],
                'contours': {name: {'status':'ok','new':0,'duplicates':0,'errors':0,
                                    'unchecked_sources':[],'error_details':[]} for name in r.LOCAL_NAMES}}
    def counts(self):
        return {n:{'new':0,'sent':0,'excluded':0,'unknown':0} for n in r.NAMES}
    def queue(self, chat='11', status='SENT', mid='5', text='summary', attempts=1):
        p={'chatId':chat,'text':text,'_ef5':{'receipt':{'chatId':chat,'messageId':mid}}}
        return ['text_one','2026-10-17 14:00|FULL CYCLE|hash|'+chat,json.dumps(p),attempts,'',status]
    def test_native_mode_and_server_names(self):
        payloads=r.build_payloads(self.state(),self.counts())
        self.assertEqual([p['searchName'] for p in payloads],list(r.NAMES))
        self.assertTrue(all(p['mode']=='search_complete' for p in payloads))
        self.assertFalse(any('report' in p for p in payloads))
    def test_partial_never_masked(self):
        s=self.state(); s['contours']['Internet Leads']['unchecked_sources']=['blocked']
        self.assertEqual(r.build_payloads(s,self.counts())[0]['status'],'partial')
        s['contours']['Internet Leads']['status']='error'
        self.assertEqual(r.build_payloads(s,self.counts())[0]['status'],'error')
    def test_technical_diagnostics_never_reach_telegram(self):
        state=self.state()
        state['contours']['Internet Leads'].update(
            status='partial', errors=2,
            unchecked_sources=['https://nerudonline.ru/rabota/samosvaly: listing markup not verified'],
            error_details=['NO_VERIFIED_SEARCH_ENGINE: google: circuit open'])
        payload=r.build_payloads(state,self.counts())[0]
        self.assertEqual(payload['status'],'partial')
        self.assertEqual(payload['errors'],2)
        self.assertEqual(payload['unchecked_sources'],[])
        self.assertEqual(payload['error'],'')
        self.assertNotIn('nerudonline',json.dumps(payload))
        self.assertNotIn('NO_VERIFIED_SEARCH_ENGINE',json.dumps(payload))
        self.assertIn('nerudonline',state['contours']['Internet Leads']['unchecked_sources'][0])

    def test_pending_lead_never_clean_success(self):
        counts=self.counts();counts['Internet Leads']['new']=1
        self.assertEqual(r.build_payloads(self.state(),counts)[0]['status'],'partial')
    def test_invalid_cycle_rejected(self):
        for bad in ('','2026-10-17 15:37','today','2026-10-17 14:00\n'):
            s=self.state();s['cycleKey']=bad
            with self.assertRaises(ValueError):r.build_payloads(s,self.counts())
    def test_missing_contour_rejected(self):
        s=self.state(); del s['contours']['Tender Watch']
        with self.assertRaises(ValueError):r.build_payloads(s,self.counts())
    def test_started_contour_rejected(self):
        s=self.state();s['contours']['Tender Watch']['status']='started'
        with self.assertRaises(ValueError):r.build_payloads(s,self.counts())
    def test_queue_ack_is_not_delivery(self):
        d=r.confirm_outbox([self.queue(status='PENDING')],'2026-10-17 14:00',{'11'},'summary')
        self.assertFalse(d['ok']);self.assertEqual(d['pending'],1)
    def test_corrupt_queue_metadata_is_ignored_not_a_global_failure(self):
        rows=[]
        for raw in ('null', '[]', '{"chatId":"11","text":"summary","_ef5":null}',
                    '{"chatId":"11","text":"summary","_ef5":"bad"}'):
            rows.append(['text_one','2026-10-17 14:00|FULL CYCLE|hash|11',raw,1,'','SENT'])
        rows.append(self.queue())
        self.assertTrue(r.confirm_outbox(rows,'2026-10-17 14:00',{'11'},'summary')['ok'])

    def test_requires_all_recipients(self):
        d=r.confirm_outbox([self.queue()],'2026-10-17 14:00',{'11','22'},'summary')
        self.assertFalse(d['ok']);self.assertEqual(d['confirmed'],1)
        d=r.confirm_outbox([self.queue(),self.queue(chat='22')],'2026-10-17 14:00',{'11','22'},'summary')
        self.assertTrue(d['ok'])
    def test_wrong_text_or_zero_message_id_not_delivery(self):
        for row in (self.queue(text='old summary'), self.queue(mid='0'),self.queue(attempts=0)):
            self.assertFalse(r.confirm_outbox([row],'2026-10-17 14:00',{'11'},'summary')['ok'])
    def test_no_recipients_not_delivered(self):
        self.assertFalse(r.confirm_outbox([], '2026-10-17 14:00', set(), 'summary')['ok'])
    def test_wrong_cycle_not_delivered(self):
        self.assertFalse(r.confirm_outbox([self.queue()], '2026-10-17 08:00', {'11'}, 'summary')['ok'])
    def test_rollup_excludes_rejected_and_keeps_first_attempt(self):
        receipts={k:{'cycleKey':'slot','source':'Profi','run_id':str(i)} for i,k in enumerate(['WEB-A','WEB-B','WEB-C'])}
        receipts['WEB-D']={'cycleKey':'slot','duplicate':True}
        rows=[['WEB-A','[{"chatId":"11","messageId":"1"}]','a','SENT',80,'New'],
              ['WEB-B','[]','b','SENT',0,'Refused'],['WEB-C','[]','c','PENDING',80,'New']]
        result=r.qualified_rollup('slot',receipts,rows,{'11'})['Internet Leads']
        self.assertEqual(result,{'new':2,'sent':1,'excluded':1,'unknown':0})
    def test_unknown_missing_record_not_zero_success(self):
        result=r.qualified_rollup('slot',{'WEB-A':{'cycleKey':'slot'}},[],{'11'})
        self.assertEqual(result['Internet Leads']['unknown'],1)
        self.assertEqual(r.build_payloads(self.state(),result)[0]['status'],'partial')
    def test_health_response_is_not_ack(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"ok":true,"service":"ECOFLOT bridge"}'
        with self.assertRaises(RuntimeError):
            r.post_report(r.build_payloads(self.state(),self.counts())[0],opener=lambda *a,**k:Response())
    def test_unverified_recipients_make_no_network_call(self):
        state=self.state();state['expected_chats']=[]
        def fail(*a,**k):raise AssertionError('Unexpected IO')
        r.publish_cycle(state,read=fail,post=fail,wait=0)
        self.assertTrue(state['cycle_notice'].startswith('not-sent'))
    def test_summary_is_exact_native_order(self):
        p=r.build_payloads(self.state(),self.counts())
        self.assertEqual(r.summary_text(p),'ECOFLOT 2026-10-17 14:00 - ok\nInternet Leads: ok / 0\nTelegram/MAX: ok / 0\nTender Watch: ok / 0\nObject Leads: ok / 0')
    def test_complete_requires_report_delivery(self):
        state=self.state();state['status']='COMPLETE'
        def read(_,tab,cols):
            return [['11','approved'],['22','approved']] if tab==r.USERS else []
        with patch.object(r,'load_json',return_value={'items':{}}),patch.dict('os.environ',{'ECOFLOT_NOTIFY_SUMMARY':'1'}):
            r.publish_cycle(state,read=read,post=lambda p:{},wait=0)
        self.assertEqual(state['status'],'DELIVERY_PENDING')
        self.assertNotEqual(state['cycle_notice'],'sent')

if __name__=='__main__': unittest.main()
