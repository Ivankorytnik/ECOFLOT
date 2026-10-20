import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from primary_source_recovery import collect_propokupki

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

if __name__ == '__main__':
    unittest.main()
