import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote
import source_repair as s
import search_reliability as r
import tender_monitor as t

class SourceRepairTests(unittest.TestCase):
    def setUp(self):
        from search_runtime import configured_worker
        self.context = configured_worker('tender_monitor')
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def test_duckduckgo_attribute_order(self):
        url='https://example.com/order/12345'
        page='<a href="//duckduckgo.com/l/?uddg='+quote(url,safe='')+'" class="result__a">Order</a>'
        self.assertEqual(s.parse_results(page,'duckduckgo'),[url])
    def test_google_url_parameter(self):
        self.assertEqual(s.parse_results('<a href="/url?url=https%3A%2F%2Fexample.com%2Forder%2F12345">Order</a>','google'),['https://example.com/order/12345'])
    def test_google_modern_direct_h3(self):
        self.assertEqual(s.parse_results('<a href="https://example.com/order/12345"><h3>Order</h3></a>','google'),['https://example.com/order/12345'])
    def test_bing_encoded_redirect(self):
        url='https://example.com/order/12345'
        encoded=base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')
        page='<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1'+encoded+'">Order</a></h2></li>'
        self.assertEqual(s.parse_results(page,'bing'),[url])
    def test_no_navigation_urls(self):
        with self.assertRaises(s.UnverifiedSearch):s.parse_results('<a href="https://example.com/privacy">Privacy</a>','google')
    def test_captcha_not_empty(self):
        for engine in s.ENGINES:
            with self.assertRaises(s.UnverifiedSearch):s.parse_results('<form class="g-recaptcha">Verify you are human</form>',engine)
    def test_unknown_markup_not_empty(self):
        with self.assertRaises(s.UnverifiedSearch):s.parse_results('<html>Login</html>','duckduckgo')
    def test_verified_empty(self):
        self.assertEqual(s.parse_results('<div class="no-results__message">No results found</div>','duckduckgo'),[])
    def test_private_url_rejected(self):
        for url in ('http://127.0.0.1/order/12345','http://169.254.169.254/','file:///etc/passwd','https://user:pass@example.com/','https://example.com:8443/'):
            self.assertEqual(s.public_url(url),'')
    def test_excluded_sources_rejected(self):
        for domain in ('dozzr.ru','www.perevozka24.ru','ecoflot.pro'):
            self.assertEqual(s.public_url('https://'+domain+'/order/12345'),'')
    def test_failures_do_not_become_zero(self):
        fetch=Mock(side_effect=TimeoutError('timeout'))
        with self.assertRaises(s.UnverifiedSearch):s.discover_urls('test',fetch)
        self.assertEqual(fetch.call_count,3)
    def test_fallback_works_without_retry_storm(self):
        fetch=Mock(side_effect=[TimeoutError('timeout'),'<a class="result__a" href="https://example.com/order/12345">Order</a>'])
        self.assertEqual(s.discover_urls('test',fetch),['https://example.com/order/12345'])
        self.assertEqual(fetch.call_count,2)
    def test_result_limit(self):
        page=''.join('<a class="result__a" href="https://example.com/order/'+str(i)+'">Order</a>' for i in range(60))
        self.assertEqual(len(s.parse_results(page,'duckduckgo')),25)
    def test_shared_catalogue_cannot_pass_as_card(self):
        self.assertFalse(t.valid_tender_card_link({'link':'https://gentender.ru/search?q=1234567890123456789'}))
    def test_resolver_never_constructs_primary_url(self):
        fetch=Mock(return_value='<a href="/login">Login</a>')
        entry={'id':'1234567890123456789','link':'https://gentender.ru/search?q=1234567890123456789','title':'A concrete tender title'}
        self.assertIsNone(s.resolve_catalogue_card(entry,fetch,t.valid_tender_card_link,r.parse_deadline))
        self.assertEqual(fetch.call_count,1)
    def test_resolver_checks_title_and_deadline(self):
        rid='1234567890123456789';url='https://zakupki.gov.ru/notice?regNumber='+rid
        entry={'id':rid,'link':'https://gentender.ru/search?q='+rid,'title':'A concrete tender title'}
        fetch=Mock(side_effect=['<a href="'+url+'">Card</a>',rid+' Another title'])
        self.assertIsNone(s.resolve_catalogue_card(entry,fetch,t.valid_tender_card_link,r.parse_deadline))
        self.assertEqual(fetch.call_count,2)
    def test_resolver_verified_primary_card(self):
        rid='1234567890123456789';url='https://zakupki.gov.ru/notice?regNumber='+rid
        entry={'id':rid,'link':'https://gentender.ru/search?q='+rid,'title':'A concrete tender title'}
        from datetime import datetime, timedelta
        deadline=(datetime.now(r.MSK)+timedelta(days=3)).strftime('%d.%m.%Y %H:%M')
        text=rid+' A concrete tender title '+ '\u041e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u0435 \u043f\u043e\u0434\u0430\u0447\u0438 \u0437\u0430\u044f\u0432\u043e\u043a: '+deadline
        fetch=Mock(side_effect=['<a href="'+url+'">Card</a>',text])
        result=s.resolve_catalogue_card(entry,fetch,t.valid_tender_card_link,r.parse_deadline)
        self.assertEqual(result['link'],url)
        self.assertEqual(result['deadline'],deadline)
    def test_runtime_catalogue_fallback_to_verified_public_card(self):
        rid='1234567890123456789'
        entry={'id':rid,'link':'https://gentender.ru/search?q='+rid,'title':'A concrete tender title'}
        from datetime import datetime, timedelta
        deadline=(datetime.now(r.MSK)+timedelta(days=3)).strftime('%d.%m.%Y %H:%M')
        mirror_text=rid+' A concrete tender title Заявки до '+deadline
        with patch.object(t,'fetch',side_effect=['<html>No primary link</html>',mirror_text]) as fetch:
            self.assertTrue(t.valid_tender_card_link(entry))
            self.assertEqual(fetch.call_count,2)
        self.assertEqual(entry['link'],'https://poisktenderov.ru/item/'+rid+'/')
        self.assertEqual(entry['deadline'],deadline)

    def test_snow_haul_not_excluded(self):
        self.assertTrue(t.relevant({'title':'\u041f\u043e\u0433\u0440\u0443\u0437\u043a\u0430 \u0438 \u0432\u044b\u0432\u043e\u0437 \u0441\u043d\u0435\u0433\u0430 \u0441 \u0442\u0435\u0440\u0440\u0438\u0442\u043e\u0440\u0438\u0438'}))
    def test_equipment_sale_not_snow_service(self):
        self.assertFalse(t.relevant({'title':'\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b\u043e\u0432 \u0434\u043b\u044f \u0432\u044b\u0432\u043e\u0437\u0430 \u0441\u043d\u0435\u0433\u0430'}))
    def test_filtered_response_is_not_saved(self):
        self.assertFalse(r.acknowledged({'ok':True,'filtered':True,'saved':True},'x'))
    def test_duplicate_requires_request_identity(self):
        for response in ({'ok':True,'duplicate':True}, {'ok':True,'duplicate':True,'duplicateRow':142}, {'ok':True,'duplicate':True,'requestId':'x','duplicateReason':'link'}):
            self.assertFalse(r.acknowledged(response,'x'))
    def test_confirmed_id_duplicate_acknowledged(self):
        self.assertTrue(r.acknowledged({'ok':True,'duplicate':True,'requestId':'x','duplicateReason':'request_id'},'x'))
    def test_identity_conflict_evidence_not_processed(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(r,'RECEIPTS',Path(temp)/'r.json'), patch.dict(r.STATS,dict.fromkeys(r.STATS,0)):
            with self.assertRaises(RuntimeError):r.record_lead_result('x',{'ok':True,'duplicate':True,'duplicateReason':'link','duplicateRow':142},'test')
            item=r.load_json(r.RECEIPTS)['items']['x']
            self.assertEqual(item['status'],'IDENTITY_CONFLICT')
            self.assertFalse(item['accepted'])
            self.assertEqual(r.STATS['accepted'],0)
            self.assertEqual(item['reported_row'],142)

if __name__ == '__main__':unittest.main()
