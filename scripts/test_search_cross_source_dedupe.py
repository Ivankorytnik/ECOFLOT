import unittest
from social_leads_monitor import cross_source_duplicate

CARD='https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=657269'

class CrossSourceDedupeTests(unittest.TestCase):
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

if __name__=='__main__': unittest.main()
