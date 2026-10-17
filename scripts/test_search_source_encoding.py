import io
import unittest
from email.message import Message
from unittest.mock import patch
from source_encoding import decode_public_text, decode_response
from card_acquisition import Acquisition
import internet_leads_monitor as internet

TEXT = '\u041a\u043e\u043d\u0442\u0430\u043a\u0442\u044b \u0437\u0430\u043a\u0430\u0437\u0447\u0438\u043a\u0430'

class SourceEncodingTests(unittest.TestCase):
    def test_utf8_without_declaration(self):
        self.assertEqual(decode_public_text(TEXT.encode()), TEXT)
    def test_cp1251_http_header(self):
        self.assertEqual(decode_public_text(TEXT.encode('cp1251'), 'text/html; charset=windows-1251'), TEXT)
    def test_cp1251_meta(self):
        page='<head><meta http-equiv="Content-Type" content="text/html; charset=windows-1251" /></head>'+TEXT
        self.assertIn(TEXT, decode_public_text(page.encode('cp1251')))
    def test_header_takes_precedence_over_meta(self):
        page='<meta charset=windows-1251>'+TEXT
        self.assertIn(TEXT, decode_public_text(page.encode(), 'text/html; charset=UTF-8'))
    def test_bom_takes_precedence(self):
        self.assertEqual(decode_public_text(TEXT.encode('utf-8-sig'), 'text/html; charset=windows-1251'), TEXT)
    def test_unsupported_encoding_fails(self):
        with self.assertRaises(ValueError):decode_public_text(b'hello','text/html; charset=utf-7')
    def test_invalid_utf8_is_not_silently_replaced(self):
        with self.assertRaises(UnicodeDecodeError):decode_public_text(TEXT.encode('cp1251'))
    def test_body_mention_is_not_encoding_declaration(self):
        page='<head></head><body>charset=windows-1251 '+TEXT+'</body>'
        self.assertIn(TEXT,decode_public_text(page.encode()))
    def test_encoded_gate_not_missing_contacts(self):
        page='<meta charset=windows-1251><div class="news-detail">ID 657164 '+TEXT+': \u0421\u0435\u0439\u0447\u0430\u0441 \u0412\u0430\u043c \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b \u043a\u043e\u043d\u0442\u0430\u043a\u0442\u044b</div>'
        result=Acquisition(None).contact_from_card(decode_public_text(page.encode('cp1251')),'https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=657164','')
        self.assertEqual(result['reason'],'contact_requires_access')
    def test_real_fetch_uses_header(self):
        response=io.BytesIO(TEXT.encode('cp1251'));response.headers=Message();response.headers['Content-Type']='text/html; charset=windows-1251'
        with patch('urllib.request.urlopen',return_value=response):
            self.assertEqual(internet.fetch('https://example.com',attempts=1),TEXT)

if __name__=='__main__':unittest.main()
