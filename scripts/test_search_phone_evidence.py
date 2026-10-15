import unittest
from internet_leads_monitor import extract_public_contact

class PhoneEvidenceTests(unittest.TestCase):
    def test_uuid_in_actual_post_url_is_not_a_phone(self):
        text = 'Предоставим мусоровоз. https://vsem-podryad.ru/request/4ffac1ac-2a94-437f-8837-4947415ca367/?from=tg_post'
        self.assertEqual(extract_public_contact(text)[0], '')

    def test_plain_uuid_is_not_a_phone(self):
        self.assertEqual(extract_public_contact('ID 4ffac1ac-2a94-437f-8837-4947415ca367')[0], '')

    def test_real_explicit_phone_is_preserved(self):
        self.assertEqual(extract_public_contact('Телефон: 8 (999) 123-45-67')[0], '+79991234567')

    def test_url_number_does_not_hide_real_phone(self):
        text = 'https://example.com/88374947415 Телефон +7 999 123 45 67'
        self.assertEqual(extract_public_contact(text)[0], '+79991234567')

    def test_contact_route_preserved_without_inventing_phone(self):
        phone, contact = extract_public_contact('Пишите https://wa.me/79991234567')
        self.assertEqual(phone, '')
        self.assertEqual(contact, 'https://wa.me/79991234567')

if __name__ == '__main__':
    unittest.main()
