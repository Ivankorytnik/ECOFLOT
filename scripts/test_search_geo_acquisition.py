import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import internet_leads_monitor as m

class GeographyAcquisitionTests(unittest.TestCase):
    def test_short_msk_cannot_match_outside_city(self):
        for text in ('\u041e\u043c\u0441\u043a','\u0422\u043e\u043c\u0441\u043a','\u041e\u043c\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c', '\u0422\u043e\u043c\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c'):
            with self.subTest(text=text):
                self.assertFalse(m.geo_allowed(text))
                self.assertEqual(m.matched_geo(text),'')

    def test_foreign_moscow_district_rejected(self):
        self.assertFalse(m.geo_allowed('\u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433, \u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u0438\u0439 \u0440\u0430\u0439\u043e\u043d'))
        self.assertFalse(m.geo_allowed('\u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u0438\u0439 \u0440\u0430\u0439\u043e\u043d'))

    def test_substrings_not_locations(self):
        for text in ('\u043a\u043b\u0438\u043d\u0438\u043a\u0430', '\u043c\u0430\u0433\u0438\u0441\u0442\u0440\u0430\u043b\u044c', '\u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0441\u043a\u0438\u0439'):
            self.assertEqual(m.matched_geo(text),'')

    def test_allowed_geography_preserved(self):
        for text in ('\u041c\u043e\u0441\u043a\u0432\u0430','\u041c\u0421\u041a','\u041a\u043b\u0438\u043d','\u0414\u0443\u0431\u043d\u0430','\u0420\u0430\u043c\u0435\u043d\u0441\u043a\u0438\u0439','\u041e\u0434\u0438\u043d\u0446\u043e\u0432\u043e','\u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c','\u041a\u0430\u043b\u0443\u0436\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c','\u041a\u0430\u043b\u0443\u0433\u0430','\u041e\u0431\u043d\u0438\u043d\u0441\u043a','\u0433. \u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u0438\u0439'):
            with self.subTest(text=text): self.assertTrue(m.geo_allowed(text))

    def test_inflected_and_abbreviated_allowed_regions(self):
        for text in ('\u0432 \u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u043e\u0439 \u043e\u0431\u043b\u0430\u0441\u0442\u0438','\u041a\u0430\u043b\u0443\u0436\u0441\u043a\u0430\u044f \u043e\u0431\u043b.','\u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u0430\u044f \u043e\u0431\u043b.'):
            with self.subTest(text=text): self.assertTrue(m.geo_allowed(text))

    def test_explicit_outside_region_wins(self):
        for text in ('\u041a\u0440\u0430\u0441\u043d\u043e\u0430\u0440\u043c\u0435\u0439\u0441\u043a, \u0421\u0430\u0440\u0430\u0442\u043e\u0432\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c','\u0414\u0437\u0435\u0440\u0436\u0438\u043d\u0441\u043a, \u041d\u0438\u0436\u0435\u0433\u043e\u0440\u043e\u0434\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c','\u041a\u043b\u0438\u043d, \u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f \u043e\u0431\u043b.'):
            self.assertFalse(m.geo_allowed(text))

    def test_location_not_overridden_by_title(self):
        self.assertFalse(m.geo_allowed('\u041e\u043c\u0441\u043a', '\u041c\u043e\u0441\u043a\u0432\u0430', '\u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c'))
        self.assertTrue(m.geo_allowed('\u041c\u043e\u0441\u043a\u0432\u0430', '\u041e\u0444\u0438\u0441 \u0432 \u041e\u043c\u0441\u043a\u0435'))

    def test_unknown_address_rejected(self):
        self.assertFalse(m.geo_allowed(''))
        self.assertFalse(m.geo_allowed('\u0420\u043e\u0441\u0441\u0438\u044f'))

    def test_removed_discovery_is_excluded(self):
        for status in (404,410):
            with patch.object(m,'fetch',side_effect=HTTPError('https://example.com/order/1',status,'removed',{},None)):
                self.assertIsNone(m.parse_discovery_candidate('https://example.com/order/1'))

    def test_access_denial_remains_error(self):
        for status in (401,403,429,500,503):
            with patch.object(m,'fetch',side_effect=HTTPError('https://example.com/order/1',status,'blocked',{},None)):
                with self.assertRaises(HTTPError):m.parse_discovery_candidate('https://example.com/order/1')

    def test_timeout_remains_error(self):
        with patch.object(m,'fetch',side_effect=TimeoutError('no access')):
            with self.assertRaises(TimeoutError):m.parse_discovery_candidate('https://example.com/order/1')

if __name__=='__main__':unittest.main()
