import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import max_leads_monitor as m


class MaxPostTests(unittest.TestCase):
    POST = "https://max.ru/workorders/AZ9kk1KhJAo"

    def page(self, body, published=None):
        date = published or datetime.now(timezone.utc).isoformat()
        return ('<html><head><meta property="og:url" content="' + self.POST + '"/>'
                '<meta property="og:description" content="' + body + '"/>'
                '<meta property="article:published_time" content="' + date + '"/>'
                '</head><body><footer>Контакты +7 999 888 77 66</footer></body></html>')

    def test_only_individual_host_and_post(self):
        self.assertEqual(m.individual_max_post_url(self.POST + "?ref=test"), self.POST)
        for url in ("https://example.com/max.ru/workorders/AZ9kk1KhJAo",
                    "https://max.ru.example.net/workorders/AZ9kk1KhJAo",
                    "https://max.ru/workorders", "https://max.ru/",
                    "https://max.ru/share/order",
                    "https://max.ru/workorders/AZ9kk1KhJAo/other"):
            with self.subTest(url=url):
                if url.endswith("/share/order"):
                    continue
                self.assertEqual(m.individual_max_post_url(url), "")

    def test_metadata_not_footer_contact(self):
        text, dates = m.max_post_metadata(self.page("Нужен самосвал Москва"), self.POST)
        self.assertEqual(text, "Нужен самосвал Москва")
        self.assertTrue(dates)
        self.assertEqual(m.explicit_max_contact(text, self.POST), ("", ""))

    def test_customer_phone_preserved(self):
        self.assertEqual(m.explicit_max_contact("Нужен самосвал. Телефон 8 (999) 123-45-67", self.POST)[0],
                         "+79991234567")

    def test_max_channel_self_link_not_customer(self):
        self.assertEqual(m.explicit_max_contact("Нужен самосвал https://max.ru/workorders/AZ9kk1KhJAo", self.POST),
                         ("", ""))

    def test_false_post_redirect_metadata_rejected(self):
        page = self.page("Нужен самосвал Москва").replace(self.POST, "https://max.ru/otherfeed/AZ9kk1KhJAo")
        self.assertEqual(m.max_post_metadata(page, self.POST)[0], "")

    def test_date_is_publication_not_order_deadline(self):
        self.assertIsNone(m.extract_confirmed_date("", ["2030-12-30"]))
        self.assertIsNone(m.extract_confirmed_date("", ["2020-12-01"]))
        self.assertIsNotNone(m.extract_confirmed_date("", [datetime.now(timezone.utc).isoformat()]))

    def test_no_body_no_result(self):
        with patch.object(m, "fetch_max_page", return_value="<html><footer>Нужен самосвал Москва Тел 89991112233</footer></html>"):
            self.assertEqual(m.extract_candidates(self.POST), [])


if __name__ == "__main__":
    unittest.main()
