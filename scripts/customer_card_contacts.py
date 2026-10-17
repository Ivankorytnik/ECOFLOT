"""Identify one public customer card before inspecting its visible contacts."""
import re
from urllib.parse import urlsplit
from social_depth import scoped_contacts
from source_markup import absolute_link


def vsem_contacts(root, url):
    expected = urlsplit(url).path.rstrip('/')
    canonical = next((n.attrs.get('href', '') for n in root.find_all('link')
                      if n.attrs.get('rel') == 'canonical'), '')
    linked = urlsplit(absolute_link(url, canonical)) if canonical else None
    card = root.find(cls='request-block')
    if (not card or not linked or (linked.hostname or '').removeprefix('www.') != 'vsem-podryad.ru'
            or linked.path.rstrip('/') != expected):
        return {'reason': 'card_identity_unverified'}
    contact = card.find(cls='contract-card-contact-person')
    if contact is None:
        return {'reason': 'customer_contact_section_missing'}
    status = contact.clean().lower().replace('\u0451', '\u0435')
    if re.search(r'\u0437\u0430\u043a\u0430\u0437\u0447\u0438\u043a\s+\u0443\u0436\u0435\s+\u043d\u0430\u0448\u0435\u043b\s+\u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b|\u0437\u0430\u044f\u0432\u043a\u0430\s+\u0437\u0430\u043a\u0440\u044b\u0442\u0430', status):
        return {'reason': 'customer_order_closed'}
    banners = [n.clean().lower() for n in root.find_all(cls='show-contacts-banner') if n.visible()]
    if any('\u0443\u0432\u0438\u0434\u0435\u0442\u044c \u043a\u043e\u043d\u0442\u0430\u043a\u0442\u044b' in s and ('\u0432\u043e\u0439\u0434\u0438\u0442\u0435' in s or '\u0437\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440' in s) for s in banners):
        return {'reason': 'contact_requires_access'}
    if any(mark in contact.text() for mark in ('\u2591', '\u2588', '***')):
        return {'reason': 'contact_requires_access'}
    result = scoped_contacts(contact)
    return result if result.get('phone') or result.get('contact_url') else {'reason': 'no_public_contact'}
