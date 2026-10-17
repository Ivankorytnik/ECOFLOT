"""Card-scoped acquisition and contact enrichment. GET only; no hidden contacts.

A source listing is discovery evidence, never a substitute for a customer card.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import re
import time
from urllib.parse import urlsplit, parse_qs
import urllib.request
from source_markup import DOM, absolute_link
from social_depth import scoped_contacts

TEST_CONTENT = re.compile(r'\b(?:QA|test\s+order)\b|\u0442\u0435\u0441\u0442\u043e\u0432\u0430\u044f\s+\u0437\u0430\u044f\u0432\u043a\u0430|\u0440\u0435\u0430\u043b\u044c\u043d\u044b\u0435\s+\u0440\u0430\u0431\u043e\u0442\u044b[^.]{0,50}\u043d\u0435\s+\u0442\u0440\u0435\u0431\u0443\u044e\u0442',re.I)
CARD_PATHS = {
    'exkavator.ru': r'/exchange/item/\d+_[^/]+\.html$',
    'nerudonline.ru': r'/requests/[0-9a-f-]{36}/?$',
    'napodrabotku.ru': r'/order/\d+/?$',
    'vsem-podryad.ru': r'/request/[0-9a-f-]{36}/?$',
    'samosval.info': r'/[^?#]+/\d+/?$',
}


def known_card(url):
    try:
        p=urlsplit(url); host=(p.hostname or '').removeprefix('www.')
        if p.scheme not in ('https','http') or p.username or p.password or p.port not in (None,80,443):
            return False
        if host == 'samosval.info' and p.path == '/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php':
            ids = parse_qs(p.query).get('ID', [])
            return len(ids) == 1 and bool(re.fullmatch(r'[1-9]\d{3,11}', ids[0]))
        if host.endswith('.proms.ru') or host=='proms.ru':
            return bool(re.search(r'/item/\d+/?$',p.path))
        return bool(host in CARD_PATHS and re.fullmatch(CARD_PATHS[host],p.path))
    except ValueError:
        return False


def _field(node, cls=None, tag=None):
    found=node.find(tag,cls)
    return found.clean() if found else ''


def _item(source, url, title, description, location, date_text, key):
    import internet_leads_monitor as m
    if not known_card(url) or TEST_CONTENT.search(title+' '+description):
        return None
    try:
        dt=datetime.fromisoformat(date_text.replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):
        dt=m.parse_ddmmyy(date_text)
    if dt is None or not timedelta(minutes=-5) <= datetime.now(timezone.utc)-dt <= timedelta(days=m.RECENT_DAYS):
        return None
    result=m.build_open_feed_item(source,url,key,title,description,dt.strftime('%d.%m.%Y'),location=location,url=url)
    if result:
        result.update(contact_evidence_required=True,contact_text='',card_verified=False)
    return result


def follow_response_link(url, timeout=10):
    """Follow an observed NPD response button as a guest, no credentials.

    Only the publisher and its approved order provider may receive redirects.
    The final order identity is checked separately; a login page is not a card.
    """
    allowed = ('napodrabotku.ru', 'profi.ru')
    class Redirect(urllib.request.HTTPRedirectHandler):
        hops = 0
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            self.hops += 1
            target = absolute_link(req.full_url, newurl)
            h = (urlsplit(target).hostname or '').removeprefix('www.')
            if self.hops > 4 or h not in allowed:
                raise ValueError('UNVERIFIED_RESPONSE_REDIRECT')
            return super().redirect_request(req, fp, code, msg, headers, target)
    p = urlsplit(url)
    if p.scheme != 'https' or (p.hostname or '').removeprefix('www.') != allowed[0] or not re.fullmatch(r'/away/\d+',p.path):
        raise ValueError('NOT_OBSERVED_RESPONSE_ROUTE')
    request = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 ECOFLOT-Card-Verification/1.0'})
    with urllib.request.build_opener(Redirect).open(request,timeout=timeout) as response:
        # Loading a response route is not logging in or submitting a request.
        return response.geturl()


class Acquisition:
    def __init__(self,fetch,limit=32,budget=100,redirect_reader=follow_response_link):
        self.fetch,self.limit,self.budget=fetch,limit,budget
        self.redirect_reader=redirect_reader
        self.cache={};self.spent=0.;self.report={'cards_read':0,'contacts_recovered':0,'sources':{},'outcomes':{}}
        self.unchecked=set()

    def outcome(self,reason):
        self.report['outcomes'][reason]=self.report['outcomes'].get(reason,0)+1

    def parse_exkavator(self,page,url):
        root=DOM(page).root; cards=list(root.find_all(cls='item-card--request'));out=[]
        for node in cards:
            link=node.find('a',cls='item-card__title',attr='href')
            if not link: continue
            target=absolute_link(url,link.attrs['href'],True)
            item=_item('Exkavator',target,link.clean(),_field(node,'item-card__description'),
                       _field(node,'item-card__cities'),_field(node,'item-card__time'),
                       (re.search(r'/item/(\d+)',target) or ['',''])[1])
            if item:out.append(item)
        self.report['sources'][url]={'visible_cards':len(cards),'eligible_cards':len(out)}
        if not cards:self.unchecked.add(url+': listing markup not verified')
        return out

    def parse_nerudonline(self,page,url):
        root=DOM(page).root;cards=[n for n in root.find_all('article') if n.find('a',attr='href')];out=[]
        import internet_leads_monitor as m
        for node in cards:
            link=next((a for a in node.find_all('a',attr='href') if known_card(absolute_link(url,a.attrs['href'],True))),None)
            if not link:continue
            target=absolute_link(url,link.attrs['href'],True)
            route=next((n for n in node.walk() if '__cardRoute' in n.attrs.get('class','')),None)
            # Every explicitly labelled endpoint must remain inside the geography.
            endpoints=[]
            if route:
                endpoints=[c.clean() for c in route.children if hasattr(c,'tag') and c.tag=='span']
            if not endpoints or not all(m.geo_allowed(x) for x in endpoints):
                self.outcome('outside_or_unknown_route');continue
            stamp=node.find('time',attr='datetime')
            item=_item('NerudOnline',target,_field(node,tag='h3'),node.clean(),'; '.join(endpoints),
                       stamp.attrs['datetime'] if stamp else '',urlsplit(target).path.rstrip('/').rsplit('/',1)[-1])
            if item:out.append(item)
        self.report['sources'][url]={'visible_cards':len(cards),'eligible_cards':len(out)}
        if not cards:self.unchecked.add(url+': listing markup not verified')
        return out

    def parse_rentag(self,page,url):
        # Some public cards are test orders or require paid access. Do not invent
        # a detail URL from an internal ID or treat the platform phone as a buyer.
        root=DOM(page).root;cards=list(root.find_all(cls='application-card'));out=[]
        for node in cards:
            text=node.clean()
            if TEST_CONTENT.search(text):self.outcome('test_order');continue
            link=next((a for a in node.find_all('a',attr='href') if '/zayavki/' in a.attrs['href'] and re.search(r'\d',a.attrs['href'])),None)
            if not link:self.outcome('interactive_or_gated_card');continue
            self.unchecked.add(url+': interactive card needs verified public detail route')
        self.report['sources'][url]={'visible_cards':len(cards),'eligible_cards':len(out)}
        if cards and any(not TEST_CONTENT.search(c.clean()) for c in cards):
            self.unchecked.add(url+': some cards require guest navigation or account access')
        return out

    def enrich(self,item):
        import internet_leads_monitor as m
        own_card = known_card(item.get('url',''))
        if not own_card and m.ensure_public_contact(dict(item))[0]:
            return item
        targets=[]
        if own_card:
            targets.append(item['url'])
            # Do not trust a legacy listing/footer contact before verifying the
            # corresponding individual customer's card.
            item.update(phone='', contact_url='', contact_text='', contact_evidence_required=True)
        for link in item.get('card_links',[]):
            if known_card(link) and link not in targets: targets.append(link)
        for url in targets[:2]:
            if url not in self.cache:
                if len(self.cache)>=self.limit or self.spent>=self.budget:
                    self.unchecked.add('Card contact enrichment budget reached');self.outcome('budget');break
                started=time.monotonic()
                try:
                    page=self.fetch(url,timeout=max(1,min(12,self.budget-self.spent)))
                    self.report['cards_read']+=1
                    self.cache[url]=self.contact_from_card(page,url,item.get('title','') if url!=item.get('url') else '')
                except Exception as exc:
                    self.cache[url]={'reason':'read_failed','error':str(exc)[:180]}
                    self.unchecked.add(url+': '+str(exc)[:160])
                finally:self.spent+=time.monotonic()-started
            result=self.cache[url]
            if result.get('phone') or result.get('contact_url'):
                item.update({k:v for k,v in result.items() if k in ('phone','contact_url','contact_text','contact_evidence')})
                item.update(contact_evidence_required=True,contact_source_url=url,card_verified=True)
                if result.get('canonical_order_url'):
                    item['discovered_from'] = item.get('url')
                    item['url'] = result['canonical_order_url']
                self.report['contacts_recovered']+=1
                return item
            self.outcome(result.get('reason','no_public_contact'))
        return item

    def contact_from_card(self,page,url,title):
        root=DOM(page).root
        if (urlsplit(url).hostname or '').removeprefix('www.') == 'samosval.info':
            return self.samosval_contacts(root, url)
        title_node=root.find('h1',cls='title') or root.find('h1',cls='order-page__name') or root.find('h1')
        normal=lambda s:re.sub(r'\W+',' ',s.lower()).strip()
        # Link from a post is not proof that an unrelated contact page is its order.
        if title_node and title and not ({w for w in normal(title).split() if len(w)>3} & {w for w in normal(title_node.clean()).split() if len(w)>3}):
            return {'reason':'title_mismatch'}
        if (urlsplit(url).hostname or '').removeprefix('www.') == 'napodrabotku.ru':
            button = root.find('a',cls='order-page__go-to',attr='href')
            if button:
                observed = absolute_link(url, button.attrs['href'], True)
                if re.fullmatch(r'/away/\d+', urlsplit(observed).path):
                    try:
                        final = self.redirect_reader(observed, timeout=8)
                        p = urlsplit(final)
                        oid = parse_qs(p.query).get('o', [''])[0]
                        expected = urlsplit(url).path.rstrip('/').rsplit('/',1)[-1]
                        if (p.hostname or '').removeprefix('www.') == 'profi.ru' and p.path == '/backoffice/n.php' and oid == expected:
                            return {'contact_url':final, 'canonical_order_url':final,
                                    'contact_text':'', 'contact_evidence':[observed,final]}
                        self.outcome('response_route_not_individual_order')
                    except Exception as exc:
                        self.unchecked.add(url+': response route '+str(exc)[:120])
        scopes=[]
        for node in root.walk():
            cls=node.attrs.get('class','').lower();ident=node.attrs.get('id','').lower()
            if any(bad in cls+' '+ident for bad in ('footer','header','support','recommend','related','subscribe')):continue
            if node.has('detail-item-description-block') or node.has('order-description') or node.has('request-description') or node.has('order-page__details-text'):
                scopes.append(node)
            elif any(token in cls for token in ('buyer-contact','customer-contact','order-contact','request-contact')):
                scopes.append(node)
        if not scopes:
            self.unchecked.add(url+': card contact markup unverified or JavaScript rendering required')
            return {'reason':'contact_markup_unverified'}
        for scope in scopes:
            result=scoped_contacts(scope)
            if result['phone'] or result['contact_url']:
                return result
        gated=any(n.attrs.get('data-popup-id')=='popup-exchange-access' for n in root.walk())
        return {'reason':'contact_requires_access' if gated else 'no_public_contact'}


    def samosval_contacts(self, root, url):
        """Read only the customer-contact section on an observed detail card.

        Transport coordinates/rates and the site footer are not buyer contacts.
        Explicit paid/login gates are reported; they are never bypassed.
        """
        node = root.find(cls='news-detail')
        parts = urlsplit(url)
        rid = (parse_qs(parts.query).get('ID') or [parts.path.rstrip('/').rsplit('/', 1)[-1]])[0]
        if not node or not re.search(r'\bID\s*' + re.escape(rid) + r'(?!\d)', node.clean()):
            return {'reason': 'card_identity_unverified'}
        marker = '\u041a\u043e\u043d\u0442\u0430\u043a\u0442\u044b \u0437\u0430\u043a\u0430\u0437\u0447\u0438\u043a\u0430'
        flat = node.text()
        if marker.lower() not in flat.lower():
            return {'reason': 'customer_contact_section_missing'}
        pos = flat.lower().index(marker.lower())
        tail = flat[pos:]
        if re.search(r'\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\s+\u043a\u043e\u043d\u0442\u0430\u043a\u0442|\u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435\s+\u0434\u043e\u0441\u0442\u0443\u043f\s+\u043a\s+\u043a\u043e\u043d\u0442\u0430\u043a\u0442|\u0430\u0432\u0442\u043e\u0440\u0438\u0437\u0443\u0439\u0442\u0435\u0441\u044c', tail, re.I):
            self.unchecked.add(url + ': customer contacts require account/subscription')
            return {'reason': 'contact_requires_access'}
        # Slice the serialized customer section, preserving visible hyperlinks.
        # Everything before the label (coordinates, rates, description) is out.
        serialized = node.markup()
        match = re.search(re.escape(marker), serialized, re.I)
        if not match:
            return {'reason':'customer_contact_section_missing'}
        fragment = serialized[match.end():]
        fragment = re.split(r'\u0421\u043c\.\s*\u0442\u0430\u043a\u0436\u0435|\u0412\u044b\s+\u0442\u0430\u043a\u0436\u0435|\u043f\u043e\u0445\u043e\u0436\u0438\u0435\s+\u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d', fragment, maxsplit=1, flags=re.I)[0]
        scope = DOM(fragment).root
        contact = scoped_contacts(scope)
        return contact if contact['phone'] or contact['contact_url'] else {'reason': 'no_public_contact'}
