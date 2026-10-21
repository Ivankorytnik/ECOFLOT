import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from source_markup import DOM, absolute_link
from social_depth import parse_public_page, read_history, scoped_contacts
from card_acquisition import Acquisition, known_card
from tender_acquisition import TenderAcquisition, procurement_id
import internet_leads_monitor as internet

NOW=datetime(2026,10,17,13,0,tzinfo=timezone.utc)
TITLE='\u0412\u044b\u0432\u043e\u0437 \u0433\u0440\u0443\u043d\u0442\u0430'
MOSCOW='\u0433. \u041c\u043e\u0441\u043a\u0432\u0430, \u0443\u043b. \u041b\u0435\u0441\u043d\u0430\u044f 1'


def post(mid,day=16,body='hello',channel='sample_source'):
    return ('<div class="tgme_widget_message" data-post="'+channel+'/'+str(mid)+'">'
            '<div class="tgme_widget_message_text">'+body+'</div>'
            '<a class="tgme_widget_message_date"><time datetime="2026-10-'+f'{day:02d}'+'T10:00:00+00:00"></time></a></div>')


def more(before):
    return '<a class="tme_messages_more" href="/s/sample_source?before='+str(before)+'">Older</a>'


def b2b_page(rid='1234567',title=TITLE,address=MOSCOW,deadline='20.10.2099 12:00'):
    return ('<h1>Procurement '+rid+'</h1><h2>'+title+'</h2>'
            '<table><tr id="trade_info_date_end"><td>Deadline:</td><td>'+deadline+'</td></tr>'
            '<tr id="trade_info_address"><td>Address:</td><td>'+address+'</td></tr></table>')


class PublicMarkupTests(unittest.TestCase):
    def test_card_text_excludes_footers_and_scripts(self):
        root=DOM('<div>Order<footer>support 89991234567</footer><script>bad()</script></div>').root
        self.assertEqual(root.clean(),'Order')

    def test_hidden_contact_not_recovered(self):
        root=DOM('<div>Order<span style="display:none"><a href="tel:+79991234567">hidden</a></span></div>').root
        self.assertEqual(scoped_contacts(root)['phone'],'')

    def test_same_host_link_guard(self):
        self.assertEqual(absolute_link('https://example.com/a','https://evil.example/b',True),'')
        self.assertEqual(absolute_link('https://example.com/a','/order/1',True),'https://example.com/order/1')

    def test_credential_link_guard(self):
        self.assertEqual(absolute_link('https://example.com','https://u:p@example.com/order/1'),'')


class PublicHistoryTests(unittest.TestCase):
    def test_reads_second_observed_page(self):
        pages={'https://t.me/s/sample_source':post(100)+more(100),
               'https://t.me/s/sample_source?before=100':post(99,14)+post(50,1)}
        calls=[];report={}
        def read(url,**kw):calls.append(url);return pages[url]
        result=read_history('sample_source',read,now=NOW,report=report)
        self.assertEqual([p['id'] for p in result],['100','99'])
        self.assertEqual(report['pages'],2)
        self.assertEqual(len(calls),2)

    def test_old_page_reaches_boundary(self):
        report={};read=Mock(return_value=post(2,1)+more(2))
        self.assertEqual(read_history('sample_source',read,now=NOW,report=report),[])
        self.assertTrue(report['complete']);self.assertEqual(report['stop_reason'],'date_boundary')
        read.assert_called_once()

    def test_old_pinned_post_does_not_stop_history(self):
        read=Mock(side_effect=[post(1,1)+post(100,16)+more(100),post(90,13)])
        report={};result=read_history('sample_source',read,now=NOW,report=report)
        self.assertEqual([p['id'] for p in result],['100','90'])

    def test_page_limit_is_not_full_coverage(self):
        report={};read_history('sample_source',Mock(return_value=post(100)+more(100)),now=NOW,max_pages=1,report=report)
        self.assertFalse(report['complete']);self.assertEqual(report['stop_reason'],'page_limit')

    def test_time_limit_performs_no_get(self):
        read=Mock();report={};read_history('sample_source',read,now=NOW,max_seconds=0,report=report)
        read.assert_not_called();self.assertFalse(report['complete'])

    def test_repeated_page_not_clean_success(self):
        report={};read_history('sample_source',Mock(return_value=post(100)+more(100)),now=NOW,report=report)
        self.assertEqual(report['stop_reason'],'pagination_stalled');self.assertFalse(report['complete'])

    def test_foreign_channel_posts_ignored(self):
        result,_=parse_public_page(post(100,channel='another_source'),'sample_source')
        self.assertEqual(result,[])

    def test_unknown_date_is_incomplete(self):
        page=post(100).replace('datetime="2026-10-16T10:00:00+00:00"','')
        report={};self.assertEqual(read_history('sample_source',Mock(return_value=page),now=NOW,report=report),[])
        self.assertFalse(report['complete']);self.assertEqual(report['missing_dates'],1)

    def test_future_post_is_not_current(self):
        result=read_history('sample_source',Mock(return_value=post(100,20)),now=NOW)
        self.assertEqual(result,[])

    def test_access_error_not_zero_success(self):
        report={};read_history('sample_source',Mock(side_effect=RuntimeError('403')),now=NOW,report=report)
        self.assertEqual(report['stop_reason'],'access_or_parse_error');self.assertFalse(report['complete'])

    def test_contact_after_1800_chars_preserved(self):
        body=DOM('<p>'+'x'*2100+'<a href="tel:+79991234567">Call</a></p>').root
        self.assertEqual(scoped_contacts(body)['phone'],'+79991234567')

    def test_email_anchor_preserved(self):
        body=DOM('<p><a href="mailto:order@example.org">Write to customer</a></p>').root
        self.assertEqual(scoped_contacts(body)['contact_url'],'mailto:order@example.org')

    def test_own_channel_promotion_not_contact(self):
        body=DOM('<p>Subscribe <a href="https://t.me/sample_source">@sample_source</a></p>').root
        result=scoped_contacts(body,'sample_source')
        self.assertFalse(result['phone'] or result['contact_url'])

    def test_late_labelled_telegram_contact_preserved(self):
        body=DOM('<div>'+'x'*2000+'<br>Contact: <a href="https://t.me/real_customer">Write</a></div>').root
        self.assertEqual(scoped_contacts(body,'sample_source')['contact_url'],'https://t.me/real_customer')

    def test_uuid_not_phone(self):
        body=DOM('<div>https://example.org/4ffac1ac-2a94-437f-8837-4947415ca367</div>').root
        self.assertEqual(scoped_contacts(body)['phone'],'')


class IndividualCardTests(unittest.TestCase):
    def test_known_card_is_not_listing(self):
        self.assertTrue(known_card('https://exkavator.ru/exchange/item/278456_order.html'))
        self.assertFalse(known_card('https://exkavator.ru/exchange/rent/main.html'))
        self.assertFalse(known_card('https://exkavator.ru.evil.example/exchange/item/278456_order.html'))

    def test_footer_phone_not_customer(self):
        a=Acquisition(Mock())
        result=a.contact_from_card('<h1>'+TITLE+'</h1><div class="order-description">Work</div><footer>+79991234567</footer>',
                                   'https://www.napodrabotku.ru/order/95000000',TITLE)
        self.assertFalse(result.get('phone'))

    def test_customer_contact_scope_read(self):
        a=Acquisition(Mock())
        result=a.contact_from_card('<div class="buyer-contact"><a href="tel:+79991234567">Call</a></div>',
                                   'https://exkavator.ru/exchange/item/278456_order.html','')
        self.assertEqual(result['phone'],'+79991234567')

    def test_ndp_observed_response_same_order_only(self):
        response=Mock(return_value='https://profi.ru/backoffice/n.php?o=95000000')
        a=Acquisition(Mock(),redirect_reader=response)
        html='<a class="order-page__go-to" href="https://www.napodrabotku.ru/away/123456">Respond</a>'
        result=a.contact_from_card(html,'https://www.napodrabotku.ru/order/95000000','')
        self.assertEqual(result['canonical_order_url'],'https://profi.ru/backoffice/n.php?o=95000000')
        response.assert_called_once()

    def test_ndp_login_or_other_order_is_not_accepted(self):
        for url in ('https://profi.ru/registration/','https://profi.ru/backoffice/n.php?o=95011111'):
            a=Acquisition(Mock(),redirect_reader=Mock(return_value=url))
            html='<a class="order-page__go-to" href="/away/123456">Respond</a>'
            result=a.contact_from_card(html,'https://www.napodrabotku.ru/order/95000000','')
            self.assertNotIn('canonical_order_url',result)

    def test_rentag_qa_not_real_order(self):
        a=Acquisition(Mock())
        self.assertEqual(a.parse_rentag('<article class="application-card">TEST QA real work not required</article>','https://rentag.ru/arenda-spectehniki/zayavki'),[])
        self.assertEqual(a.report['outcomes']['test_order'],1)

    def test_budget_does_not_make_unverified_contact(self):
        read=Mock();a=Acquisition(read,limit=0)
        item={'url':'https://www.napodrabotku.ru/order/95000000','title':TITLE,'description':'Work'}
        a.enrich(item);read.assert_not_called();self.assertTrue(a.unchecked)

    def test_approved_profi_exception_preserved(self):
        read=Mock();a=Acquisition(read)
        item={'url':'https://profi.ru/backoffice/n.php?o=95000000','title':TITLE}
        a.enrich(item);read.assert_not_called();self.assertTrue(internet.ensure_public_contact(item)[0])


class ProcurementAcquisitionTests(unittest.TestCase):
    url='https://www.b2b-center.ru/market/view.html?id=1234567'

    def test_specific_id_not_spare_part_number(self):
        self.assertEqual(procurement_id(self.url),'1234567')
        self.assertEqual(procurement_id('https://www.b2b-center.ru/market/parts-9999999999/tender-1234567/'),'1234567')

    def test_menu_and_unknown_host_are_not_procurements(self):
        for url in ('https://www.b2b-center.ru/search/moskva/samosvaly/','https://evil.example/market/view.html?id=1234567',
                    'https://www.b2b-center.ru/market/view.html?id=x','https://u:p@www.b2b-center.ru/market/view.html?id=1234567'):
            self.assertEqual(procurement_id(url),'')

    def test_gentender_new_observed_slug_extracted(self):
        page='<li class="t-card"><a class="t-title" href="/zakupka/0373100108926000020-order">'+TITLE+'</a><span class="t-region">'+MOSCOW+'</span></li>'
        a=TenderAcquisition(Mock());result=a.extract_gentender(page,'Moscow')
        self.assertEqual(len(result),1);self.assertEqual(result[0]['id'],'0373100108926000020')
        self.assertTrue(result[0]['acquisition_pending']);self.assertEqual(result[0]['deadline'],'')

    def test_b2b_menu_never_fetched(self):
        fetch=Mock();a=TenderAcquisition(fetch)
        self.assertEqual(a.extract_direct('<nav><a href="/search/regions/">'+TITLE+'</a></nav>','B2B',self.url,MOSCOW),[])
        fetch.assert_not_called()

    def test_true_primary_card_has_evidence(self):
        fetch=Mock(return_value=b2b_page());a=TenderAcquisition(fetch)
        result=a.resolve(self.url)
        self.assertEqual(result['id'],'1234567');self.assertEqual(result['region'],MOSCOW)
        self.assertTrue(result['verification']['deadline_confirmed'])

    def test_wrong_card_identity_rejected(self):
        a=TenderAcquisition(Mock(return_value=b2b_page(rid='1234568')))
        self.assertIsNone(a.resolve(self.url));self.assertEqual(a.report['outcomes']['identity_mismatch'],1)

    def test_customer_moscow_cannot_override_outside_work(self):
        page=b2b_page(address='\u0412\u043e\u0440\u043e\u043d\u0435\u0436\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c')+'<footer>'+MOSCOW+'</footer>'
        a=TenderAcquisition(Mock(return_value=page));self.assertIsNone(a.resolve(self.url))

    def test_parts_not_services(self):
        a=TenderAcquisition(Mock(return_value=b2b_page(title='\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0437\u0430\u043f\u0447\u0430\u0441\u0442\u0435\u0439 \u0434\u043b\u044f \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b\u043e\u0432')))
        self.assertIsNone(a.resolve(self.url))

    def test_expired_unknown_or_yearless_deadline_rejected(self):
        for deadline in ('01.01.2020 12:00','','20 October'):
            a=TenderAcquisition(Mock(return_value=b2b_page(deadline=deadline)))
            self.assertIsNone(a.resolve(self.url))

    def test_known_id_skips_network(self):
        fetch=Mock();a=TenderAcquisition(fetch,known_ids={'TENDER-1234567'})
        self.assertIsNone(a.resolve(self.url));fetch.assert_not_called()

    def test_same_primary_url_is_cached(self):
        fetch=Mock(return_value=b2b_page());a=TenderAcquisition(fetch)
        self.assertEqual(a.resolve(self.url),a.resolve(self.url));fetch.assert_called_once()

    def test_tender_host_cooldown_preserves_other_sources(self):
        def read(url, **kw):
            if 'zakupki.gov.ru' in url:
                raise TimeoutError('primary portal unavailable')
            return b2b_page()
        fetch=Mock(side_effect=read)
        a=TenderAcquisition(fetch,limit=20,budget=180)
        failures=['https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber='+str(1234567890123456700+i) for i in range(7)]
        for url in failures:
            self.assertIsNone(a.resolve(url))
        calls=[call.args[0] for call in fetch.call_args_list]
        self.assertEqual(sum('zakupki.gov.ru' in url for url in calls),2)
        self.assertIsNotNone(a.resolve(self.url))
        self.assertEqual(a.report['outcomes'].get('host_cooldown'),5)
        self.assertTrue(any('source temporarily paused' in x for x in a.unchecked))

    def test_limits_stay_unchecked(self):
        a=TenderAcquisition(Mock(),limit=0);self.assertIsNone(a.resolve(self.url));self.assertTrue(a.unchecked)

    def test_adapter_restores_original_extractors(self):
        import search_runtime as runtime
        import tender_monitor as tender
        original=tender.extract_cards
        with runtime.configured_worker('tender_monitor'):
            self.assertNotEqual(tender.extract_cards,original)
        self.assertIs(tender.extract_cards,original)


if __name__=='__main__':unittest.main()
