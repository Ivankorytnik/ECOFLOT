import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from primary_source_recovery import collect_propokupki, parse_samosval_orders, is_samosval_order_route

class PrimarySourceRecoveryTests(unittest.TestCase):
    def test_order_card_is_collected_once(self):
        day = datetime.now(timezone.utc).strftime('%d.%m.%Y')
        url = 'https://propokupki.ru/moskovskaya_oblast/uslugi_dlya_biznesa/order.html'
        def fetch(link, **kw):
            if link == url:
                return '<h1>Требуются самосвалы</h1><p>' + day + '</p><p>Московская область. Требуются самосвалы +79230000001</p>'
            return '<a href="' + url + '">Требуются самосвалы</a>'
        m = SimpleNamespace(
            PROPOKUPKI_SOURCES=[('МО','https://propokupki.ru/moskovskaya_oblast/uslugi_dlya_biznesa/')],
            fetch=fetch, normalize=str.lower, clean=lambda x: __import__('re').sub('<[^>]*>','',x),
            _host_matches=lambda u,d: 'propokupki.ru' in u, relevant=lambda t,x: True,
            matched_geo=lambda x: 'Московская область' if 'Московская область' in x else '',
            lines_from_html=lambda x: __import__('re').sub('<[^>]*>',' ',x).splitlines(),
            extract_public_contact=lambda x: ('+79230000001','') if '+79230000001' in x else ('',''),
            extract_volume=lambda x: '', priority_for=lambda x:'HIGH', RECENT_DAYS=7)
        leads, errors = collect_propokupki(m)
        self.assertEqual([], errors)
        self.assertEqual(1, len(leads))
        self.assertEqual(url, leads[0]['url'])
        self.assertTrue(leads[0]['contact_evidence_required'])

class SamosvalRecoveryTests(unittest.TestCase):
    def test_individual_route(self):
        self.assertTrue(is_samosval_order_route('https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=657221'))
        self.assertFalse(is_samosval_order_route('https://samosval.info/katalog-transporta/kartochka-transportnoy-kompanii.php?ID=111076'))
        self.assertFalse(is_samosval_order_route('https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/'))

    def test_neighbour_orders_do_not_share_data(self):
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo('Europe/Moscow'))
        future = (today + timedelta(days=3)).strftime('%d.%m.%Y %H:%M')
        day = today.strftime('%d.%m.%Y')
        page = ('<p>ID: 657221</p><p>Дата публикации: '+day+'</p><p>Объявление актуально до: '+future+
                '</p><p>Требуются самосвалы, перевозка песка, Московская область.</p><p>Контакты заказчика: скрыты</p>'
                '<h2>Работа для самосвалов</h2><p>ID: 657222</p><p>Дата публикации: '+day+
                '</p><p>Объявление актуально до: '+future+
                '</p><p>Нужен самосвал, вывоз грунта, Москва.</p>')
        import internet_leads_monitor as m
        original = m.lines_from_html
        m.lines_from_html = lambda value: __import__('re').sub(r'<[^>]*>', '\\n', value).splitlines()
        try:
            results = parse_samosval_orders(m, page, 'https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/moskovskaya-oblast/')
        finally:
            m.lines_from_html = original
        self.assertEqual(2, len(results))
        self.assertNotEqual(results[0]['url'], results[1]['url'])

if __name__ == '__main__':
    unittest.main()
