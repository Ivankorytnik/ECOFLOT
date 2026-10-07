import unittest
import search_topic as s


class TopicTests(unittest.TestCase):
    def test_unrelated_bing_leadership_is_not_a_lead_source(self):
        page='<li class="b_algo"><a href="https://www.sands.com/company/leadership/patrick-dumont/">CEO</a></li>'
        with self.assertRaises(s.UnverifiedSearch):
            s.parse_results(page, 'bing', '\u043d\u0443\u0436\u0435\u043d \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b \u041c\u043e\u0441\u043a\u0432\u0430')

    def test_max_query_cannot_claim_other_sites_as_max(self):
        page='<li class="b_algo"><a href="https://example.com/samosval/12345">Order</a></li>'
        with self.assertRaises(s.UnverifiedSearch):
            s.parse_results(page, 'bing', 'site:max.ru \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b')

    def test_relevant_title_accepted_with_opaque_url(self):
        page='<a href="https://max.ru/channel/ABC123" class="result__a">\u0422\u0440\u0435\u0431\u0443\u044e\u0442\u0441\u044f \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b\u044b</a>'
        self.assertEqual(s.parse_results(page,'duckduckgo','site:max.ru \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b'), ['https://max.ru/channel/ABC123'])

    def test_relevant_transliterated_url_accepted(self):
        self.assertTrue(s.result_matches_query('https://example.com/samosval-12345','Order','\u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b'))

    def test_host_suffix_attack_rejected(self):
        self.assertFalse(s.result_matches_query('https://max.ru.example.com/samosval','x','site:max.ru \u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b'))

    def test_excluded_as_unverified_not_clean_zero(self):
        page='<a href="https://example.com/corporate-news" class="result__a">News</a>'
        with self.assertRaisesRegex(s.UnverifiedSearch, 'do not match'):
            s.parse_results(page, 'duckduckgo', '\u0432\u044b\u0432\u043e\u0437 \u0433\u0440\u0443\u043d\u0442\u0430')


if __name__ == '__main__': unittest.main()
