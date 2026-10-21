import unittest
from social_leads_monitor import cross_source_duplicate, already_known_before_contact
from order_identity import (item_order_key, known_order_keys, order_key_from_url,
                            order_urls_in_text, primary_order_link)

CARD='https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=657269'

class CrossSourceDedupeTests(unittest.TestCase):
    def test_early_dedupe_skips_known_message_before_network(self):
        item={'request_id':'SOCIAL-TG-samosvalinfo-10057', 'url':'https://t.me/samosvalinfo/10057', 'card_links':[]}
        self.assertTrue(already_known_before_contact(item, {}, {item['request_id']}, set(), set(), True))
        self.assertTrue(already_known_before_contact(item, {item['request_id']: 'old'}, set(), set(), set(), False))
        self.assertFalse(already_known_before_contact(item, {}, set(), set(), set(), False))

    def test_early_dedupe_skips_source_order_but_not_unrelated_card(self):
        item={'request_id':'SOCIAL-TG-samosvalinfo-10057', 'url':'https://t.me/samosvalinfo/10057', 'card_links':[CARD]}
        self.assertTrue(already_known_before_contact(item, {}, set(), {CARD}, known_order_keys({CARD}), False))
        self.assertFalse(already_known_before_contact(item, {}, set(), {'https://example.com/other'}, set(), False))


    def test_same_order_in_telegram_and_web(self):
        item={'url':'https://t.me/samosvalinfo/10057','card_links':[CARD]}
        self.assertTrue(cross_source_duplicate(item,{CARD}))
    def test_another_order_kept(self):
        item={'url':'https://t.me/samosvalinfo/10057','card_links':[CARD]}
        self.assertFalse(cross_source_duplicate(item,{'https://example.com/another'}))
    def test_generic_links_never_trigger_dedupe(self):
        item={'card_links':['https://samosval.info/katalog-transporta/kartochka-transportnoy-kompanii.php?ID=111076']}
        self.assertFalse(cross_source_duplicate(item,set(item['card_links'])))
    def test_missing_card_link_kept(self):
        self.assertFalse(cross_source_duplicate({'url':'https://t.me/test/33'}, {CARD}))

    def test_observed_plain_text_card_matches_original_order(self):
        item={'source':'Telegram / Samosval.Info','url':'https://t.me/samosvalinfo/10057',
              'description':'Нужны самосвалы. Подробнее: '+CARD}
        self.assertTrue(cross_source_duplicate(item,{CARD}))
        self.assertEqual(primary_order_link(item),CARD)

    def test_profi_same_order_different_title(self):
        first='https://profi.ru/backoffice/n.php?o=95227492'
        second='https://www.profi.ru/backoffice/n.php?o=95227492&utm_source=profile'
        self.assertEqual(order_key_from_url(first),order_key_from_url(second))
        self.assertEqual(item_order_key({'url':second}), 'profi:95227492')
        self.assertIn('profi:95227492', known_order_keys({first}))
        self.assertNotEqual(item_order_key({'url':first}),
                            item_order_key({'url':'https://profi.ru/backoffice/n.php?o=95250396'}))

    def test_two_independent_orders_in_one_post_are_ambiguous(self):
        other=CARD.replace('657269','657164')
        item={'source':'Telegram / Samosval.Info','url':'https://t.me/samosvalinfo/10058',
              'description':CARD+' '+other}
        self.assertEqual(item_order_key(item),'')
        self.assertFalse(cross_source_duplicate(item,{CARD}))
        self.assertEqual(primary_order_link(item),'')

    def test_no_fuzzy_title_or_generic_supplier_profile_merge(self):
        profile='https://samosval.info/katalog-transporta/kartochka-transportnoy-kompanii.php?ID=111076'
        self.assertEqual(order_key_from_url(profile),'')
        self.assertFalse(cross_source_duplicate({'source':'Telegram / Samosval.Info',
            'url':'https://t.me/samosvalinfo/10058','description':profile}, {CARD}))
        self.assertEqual(order_key_from_url('https://samosval.info.evil.example'+CARD.split('.info')[1]),'')
        self.assertEqual(order_urls_in_text('Просто текст: ID:657269'),[])

if __name__=='__main__': unittest.main()
