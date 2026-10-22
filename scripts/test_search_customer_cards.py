import unittest
from source_markup import DOM
from customer_card_contacts import vsem_contacts
from card_acquisition import Acquisition

URL='https://vsem-podryad.ru/request/ac9e0b9a-cb46-4fcd-b4ff-c4b37a11ae1e/'
CLOSED='\u0417\u0430\u043a\u0430\u0437\u0447\u0438\u043a \u0443\u0436\u0435 \u043d\u0430\u0448\u0435\u043b \u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u0435\u0439'
BANNER='\u0417\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440\u0443\u0439\u0442\u0435\u0441\u044c \u0438\u043b\u0438 \u0432\u043e\u0439\u0434\u0438\u0442\u0435 \u0432 \u043f\u0440\u043e\u0444\u0438\u043b\u044c, \u0447\u0442\u043e\u0431\u044b \u0443\u0432\u0438\u0434\u0435\u0442\u044c \u043a\u043e\u043d\u0442\u0430\u043a\u0442\u044b \u0437\u0430\u043a\u0430\u0437\u0447\u0438\u043a\u0430'

def page(contact='',banner=''):
 return '<link rel="canonical" href="'+URL+'"><div class="request-block"><div class="contract-card-contact-person">'+contact+'</div></div>'+('<div class="show-contacts-banner">'+banner+'</div>' if banner else '')+'<footer>+79990000000</footer>'

class CustomerCardsTests(unittest.TestCase):
 def test_closed_card(self):self.assertEqual(vsem_contacts(DOM(page(CLOSED)).root,URL)['reason'],'customer_order_closed')
 def test_gated_card_never_returns_hidden_phone(self):
  r=vsem_contacts(DOM(page('+79991234567',BANNER)).root,URL);self.assertEqual(r['reason'],'contact_requires_access');self.assertNotIn('phone',r)
 def test_masked_contact_not_recovered(self):self.assertEqual(vsem_contacts(DOM(page('7915\u2591\u2591\u2591\u2591\u2591\u2591\u2591')).root,URL)['reason'],'contact_requires_access')
 def test_public_scoped_contact(self):self.assertEqual(vsem_contacts(DOM(page('<a href="tel:+79991234567">Call</a>')).root,URL)['phone'],'+79991234567')
 def test_wrong_card_rejected(self):self.assertEqual(vsem_contacts(DOM(page('+79991234567')).root,URL.replace('ac9e','bc9e'))['reason'],'card_identity_unverified')
 def test_footer_not_customer(self):self.assertEqual(vsem_contacts(DOM(page()).root,URL)['reason'],'no_public_contact')
 def test_adapter_records_access_requirement(self):
  acq=Acquisition(None);result=acq.contact_from_card(page('7915\u2591\u2591',BANNER),URL,'');self.assertEqual(result['reason'],'contact_requires_access');self.assertTrue(acq.unchecked)

if __name__=='__main__':unittest.main()
