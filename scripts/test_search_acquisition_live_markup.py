import unittest
from unittest.mock import Mock
from source_markup import DOM
from social_depth import scoped_contacts
from card_acquisition import Acquisition


class LiveMarkupTests(unittest.TestCase):
    def test_bare_class_and_style_do_not_crash(self):
        root = DOM('<div class style>Real order</div>').root
        self.assertEqual(root.clean(), 'Real order')
        self.assertEqual(list(root.find_all(cls='missing')), [])

    def test_bare_hidden_still_hides_phone(self):
        root = DOM('<div hidden><a href="tel:+79991234567">Call</a></div>').root
        self.assertEqual(scoped_contacts(root)['phone'], '')

    def test_empty_attributes_do_not_hide_public_tel(self):
        root = DOM('<div class style><a class href="tel:+79991234567">Call</a></div>').root
        self.assertEqual(scoped_contacts(root)['phone'], '+79991234567')

    def test_rentag_empty_class_is_not_contact_or_crash(self):
        acq = Acquisition(Mock())
        page = '<article class="application-card"><div class>Order requires guest navigation</div></article>'
        self.assertEqual(acq.parse_rentag(page, 'https://rentag.ru/arenda-spectehniki/zayavki'), [])
        self.assertEqual(acq.report['outcomes']['interactive_or_gated_card'], 1)
        self.assertTrue(acq.unchecked)


if __name__ == '__main__':
    unittest.main()
