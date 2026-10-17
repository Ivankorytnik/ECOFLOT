import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from card_acquisition import Acquisition, known_card
from social_depth import parse_public_page
from source_markup import DOM
from tender_acquisition import TenderAcquisition
from tender_intake import prioritize
from test_search_acquisition_depth import b2b_page, post
import tender_monitor

CARD='https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=657164'
LABEL='\u041a\u043e\u043d\u0442\u0430\u043a\u0442\u044b \u0437\u0430\u043a\u0430\u0437\u0447\u0438\u043a\u0430'
TITLE='\u0412\u044b\u0432\u043e\u0437 \u0433\u0440\u0443\u043d\u0442\u0430'
B2B='https://www.b2b-center.ru/market/earthworks/tender-1234567/'

class AcquisitionFollowupTests(unittest.TestCase):
    def test_observed_detail_query_is_card(self):
        self.assertTrue(known_card(CARD))
    def test_listing_and_ambiguous_identity_are_not_cards(self):
        for url in (CARD.split('?')[0], CARD+'&ID=657165',CARD.replace('657164','x'),CARD.replace('samosval.info','samosval.info.evil.example')):
            self.assertFalse(known_card(url),url)
    def test_only_customer_section_is_contact(self):
        page='<div class="news-detail">ID 657164 Coordinates 56.123795, 36.995529 '+LABEL+': <a href="tel:+79991234567">Call</a></div><footer>+79990000000</footer>'
        result=Acquisition(Mock()).contact_from_card(page,CARD,'')
        self.assertEqual(result['phone'],'+79991234567')
    def test_other_card_cannot_supply_contact(self):
        page='<div class="news-detail">ID 657165 '+LABEL+' +79991234567</div>'
        self.assertEqual(Acquisition(Mock()).contact_from_card(page,CARD,'')['reason'],'card_identity_unverified')
    def test_explicit_gate_not_replaced_with_footer_phone(self):
        page='<div class="news-detail">ID 657164 '+LABEL+': \u0421\u0435\u0439\u0447\u0430\u0441 \u0412\u0430\u043c \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b \u043a\u043e\u043d\u0442\u0430\u043a\u0442\u044b. +79991234567</div><footer>+79990000000</footer>'
        acq=Acquisition(Mock());r=acq.contact_from_card(page,CARD,'')
        self.assertEqual(r['reason'],'contact_requires_access');self.assertNotIn('phone',r);self.assertTrue(acq.unchecked)
    def test_hidden_customer_phone_is_not_extracted(self):
        page='<div class="news-detail">ID 657164 '+LABEL+' <span hidden>+79991234567</span></div>'
        self.assertEqual(Acquisition(Mock()).contact_from_card(page,CARD,'')['reason'],'no_public_contact')
    def test_related_ads_are_not_contacts(self):
        page='<div class="news-detail">ID 657164 '+LABEL+': not provided. \u0421\u043c. \u0442\u0430\u043a\u0436\u0435 +79991234567</div>'
        self.assertEqual(Acquisition(Mock()).contact_from_card(page,CARD,'')['reason'],'no_public_contact')
    def test_link_preview_is_preserved_without_author_link(self):
        page=post(10).replace('</time></a></div>','</time></a><a class="tgme_widget_message_link_preview" href="'+CARD+'">Preview</a><a href="https://t.me/source_author">Author</a></div>')
        found,_=parse_public_page(page,'sample_source')
        self.assertEqual(found[0]['links'],[CARD])
    def test_body_link_and_preview_deduped(self):
        page=post(10,body='<a href="'+CARD+'">Order</a>').replace('</time></a></div>','</time></a><a class="tgme_widget_message_link_preview" href="'+CARD+'">Preview</a></div>')
        self.assertEqual(parse_public_page(page,'sample_source')[0][0]['links'],[CARD])
    def test_hidden_preview_not_followed(self):
        page=post(10).replace('</time></a></div>','</time></a><a hidden class="tgme_widget_message_link_preview" href="'+CARD+'">Preview</a></div>')
        self.assertEqual(parse_public_page(page,'sample_source')[0][0]['links'],[])
    def test_direct_discovery_does_not_consume_verification_budget(self):
        fetch=Mock(return_value=b2b_page());acq=TenderAcquisition(fetch,defer_resolution=True)
        rows=acq.extract_direct('<a href="'+B2B+'">'+TITLE+'</a>','B2B',B2B,'')
        fetch.assert_not_called();self.assertEqual(len(rows),1);self.assertTrue(rows[0]['acquisition_pending'])
        self.assertEqual(acq.report['sources'][B2B]['verified_cards'],0)
        self.assertTrue(acq.verify_entry(rows[0]));fetch.assert_called_once();self.assertFalse(rows[0]['acquisition_pending'])
    def test_no_menu_candidate(self):
        fetch=Mock();acq=TenderAcquisition(fetch,defer_resolution=True)
        self.assertEqual(acq.extract_direct('<a href="/market/">Regions</a>','B2B',B2B,''),[]);fetch.assert_not_called()
    def test_budget_limit_does_not_cache_permanent_failure(self):
        fetch=Mock(return_value=b2b_page());acq=TenderAcquisition(fetch,limit=0)
        self.assertIsNone(acq.resolve(B2B));self.assertNotIn(B2B,acq.verified)
        acq.limit=1;self.assertIsNotNone(acq.resolve(B2B));self.assertEqual(fetch.call_count,1)
    def test_known_tender_never_refetched(self):
        fetch=Mock();acq=TenderAcquisition(fetch,{'TENDER-1234567'},defer_resolution=True)
        entry=acq.defer(B2B);self.assertFalse(acq.verify_entry(entry));fetch.assert_not_called()
    def test_round_robin_prevents_source_starvation(self):
        items=[({'id':str(i),'title':TITLE,'intake_source':'A'},str(i)) for i in range(10)]
        items.append(({'id':'b','title':TITLE,'intake_source':'B'},'b'))
        self.assertEqual(prioritize(items)[1][1],'b');self.assertEqual(len(prioritize(items)),11)
    def test_strong_work_first_within_source(self):
        items=[({'id':'1','title':'Unknown','intake_source':'A'},'1'),({'id':'2','title':TITLE,'intake_source':'A'},'2')]
        self.assertEqual(prioritize(items)[0][1],'2')
    def test_final_screen_uses_resolved_deadline(self):
        e={'id':'1234567','title':TITLE,'link':B2B,'deadline':'','acquisition_pending':True}
        def verify(entry):
            entry.update(deadline='20.10.2099 12:00',region='\u041c\u043e\u0441\u043a\u0432\u0430',acquisition_pending=False)
            return True
        values=dict(SOURCES=[('test','https://example.com')],DIRECT_SOURCES=[],TELEGRAM_TENDER_SOURCES=[],TENDER_WEB_DISCOVERY_QUERIES=[],KNOWN_ALREADY_SENT=set())
        with patch.multiple(tender_monitor,**values),patch.object(tender_monitor,'load_state',return_value={'sent':{},'last_run':{'metrics_version':2}}),patch.object(tender_monitor,'load_sheet_request_ids',return_value=(set(),True)),patch.object(tender_monitor,'fetch',return_value='test'),patch.object(tender_monitor,'extract_cards',return_value=[e]),patch.object(tender_monitor,'relevant',return_value=True),patch.object(tender_monitor,'valid_tender_card_link',side_effect=verify) as check,patch.object(tender_monitor,'send_webhook') as send,patch.object(tender_monitor,'save_state'),patch.object(tender_monitor,'finish_metrics'),patch.dict('os.environ',{'SUPPRESS_NO_RESULTS':'1'}):
            tender_monitor.main();send.assert_called_once();check.assert_called_once()

if __name__=='__main__':unittest.main()
