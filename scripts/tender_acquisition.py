"""Acquire individual procurement cards, with explicit identity/location/deadline.

Public GETs only. Catalogue hints and Telegram posts are discovery, not proof of
an active procurement. Menu links never become candidates. No network on import.
"""
from datetime import datetime
import re
import time
from urllib.parse import urlsplit, parse_qs
from source_markup import DOM, absolute_link
from social_depth import read_history, parse_public_page
from search_reliability import parse_deadline, tender_service_demand, MSK

B2B = ('b2b-center.ru','b2b-fsk.ru')
PRIMARY = B2B + ('zakupki.gov.ru','rts-tender.ru','roseltorg.ru','fabrikant.ru','etpgpb.ru','sberbank-ast.ru')
YEAR_DATE = re.compile(r'(?<!\d)\d{1,2}[./]\d{1,2}[./]20\d{2}(?:\s+\d{1,2}:\d{2})?')


def host(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')


def procurement_id(url):
    """Only supported observed individual URLs, not arbitrary digits in links."""
    try:
        p=urlsplit(url);h=host(url);q=parse_qs(p.query)
        if p.scheme not in ('https','http') or p.username or p.password or p.port not in (None,80,443):return ''
        if h in B2B:
            m=re.search(r'/market/[^?]*tender-(\d{5,12})/?$',p.path)
            if m:return m[1]
            if p.path=='/market/view.html' and re.fullmatch(r'\d{5,12}',q.get('id',[''])[0]):return q['id'][0]
        if h=='zakupki.gov.ru' and '/notice/' in p.path:
            value=(q.get('regNumber') or q.get('noticeInfoId') or [''])[0]
            if re.fullmatch(r'\d{8,25}',value):return value
        if h=='gentender.ru':
            m=re.match(r'^/zakupka/((?:\d{19}|\d{11}|[a-z]{2,8}-\d+))-',p.path)
            if m:return m[1]
        if h in PRIMARY:
            if re.search(r'/(?:procedure|purchase|notice|tender|trade|auction|procDetail)(?:/|$)',p.path,re.I):
                value=next((q[k][0] for k in ('regNumber','number','id','purchase','procedure','trade','tender','notice') if k in q),'')
                if re.fullmatch(r'[A-Za-z0-9_-]{5,80}',value):return value
                m=re.search(r'/(\d{8,25})(?:/|$)',p.path)
                if m:return m[1]
        return ''
    except (ValueError,TypeError):return ''


def text(node,cls=None,tag=None):
    part=node.find(tag,cls) if node else None
    return part.clean() if part else ''


def explicit_date(value):
    m=YEAR_DATE.search(str(value or ''))
    return m[0].replace('/','.') if m else ''


def clean_title(root):
    # B2B's h1 is a procedure banner, h2 is the actual object of procurement.
    return text(root,tag='h2') or text(root,'main-title') or text(root,tag='h1')


def observed_primary_links(root,base):
    out=[]
    for a in root.find_all('a',attr='href'):
        url=absolute_link(base,a.attrs['href'])
        if host(url) in PRIMARY and procurement_id(url) and url not in out:out.append(url)
    return out


class TenderAcquisition:
    def __init__(self,fetch,known_ids=None,limit=48,budget=180,defer_resolution=False):
        self.fetch=fetch;self.known_ids=known_ids if known_ids is not None else set()
        self.defer_resolution = defer_resolution
        self.limit=limit;self.budget=budget;self.spent=0.;self.cache={};self.verified={};self.unchecked=set()
        # A primary source that times out repeatedly must not consume the
        # whole card-verification budget. Other hosts remain available.
        self.get_attempts=0
        self.host_failures={}
        self.host_retry_at={}
        self.host_failure_limit=2
        self.host_probe_every=12
        self.report={'detail_requests':0,'verified_cards':0,'listing_candidates':0,'menu_links_rejected':0,'outcomes':{},'sources':{}}

    def outcome(self,reason):
        self.report['outcomes'][reason]=self.report['outcomes'].get(reason,0)+1

    def get(self,url):
        if url in self.cache:return self.cache[url]
        source = host(url)
        if (self.host_failures.get(source,0)>=self.host_failure_limit
                and self.get_attempts<self.host_retry_at.get(source,0)):
            raise RuntimeError('SOURCE_HOST_COOLDOWN')
        if len(self.cache)>=self.limit or self.spent>=self.budget:
            self.unchecked.add('Tender card verification budget reached');raise RuntimeError('CARD_VERIFICATION_BUDGET')
        self.get_attempts+=1
        start=time.monotonic()
        try:
            page=self.fetch(url,timeout=max(1,min(9,self.budget-self.spent)))
            self.host_failures[source]=0
            self.host_retry_at.pop(source,None)
            self.cache[url]=page;self.report['detail_requests']+=1;return page
        except Exception:
            # A timeout is not a permanent cache hit. After two failures,
            # pause this host; probe after other sources had 12 GET attempts.
            # Failed individual cards remain unverified and may be revisited
            # in a later run.
            self.host_failures[source]=self.host_failures.get(source,0)+1
            if self.host_failures[source]>=self.host_failure_limit:
                self.host_retry_at[source]=self.get_attempts+self.host_probe_every
            self.cache.pop(url, None)
            raise
        finally:self.spent+=time.monotonic()-start

    def defer(self, url, expected_title='', source=''):
        rid = procurement_id(url)
        if not rid:
            return None
        return dict(id=rid, title=expected_title, link=url, region='', deadline='',
                    customer='', price='', law='', acquisition_pending=True,
                    intake_source=source or host(url), source=source or host(url))

    def discover(self, url, expected_title='', source=''):
        if self.defer_resolution:
            return self.defer(url, expected_title, source)
        return self.resolve(url, expected_title)

    def extract_gentender(self,page,region):
        root=DOM(page).root;out=[];cards=list(root.find_all(cls='t-card'))
        for node in cards:
            a=node.find('a',cls='t-title',attr='href')
            if not a:continue
            url=absolute_link('https://gentender.ru',a.attrs['href'],True);rid=procurement_id(url)
            if not rid:
                if tender_service_demand(a.clean()):
                    self.unchecked.add('GenTender / '+region+': unsupported individual-link format')
                continue
            out.append({'id':rid,'title':a.clean(),'law':text(node,'t-law'),'region':text(node,'t-region'),
                        'customer':text(node,'t-cust'),'price':text(node,'t-price'),'deadline':'',
                        'deadline_hint':text(node,'t-dl'),'link':url,'source':'GenTender individual card',
                        'acquisition_pending':True, 'intake_source':'GenTender / '+region})
        self.report['listing_candidates']+=len(out)
        self.report['sources']['GenTender / '+region]={'visible_cards':len(cards),'individual_links':len(out)}
        if not cards:self.unchecked.add('GenTender / '+region+': catalogue markup not verified')
        return out

    def extract_direct(self,page,label,url,region):
        # A few B2B-Center listing responses are >2.5 MB. The full DOM
        # reader intentionally rejects those pages, but the individual
        # procurement anchors can still be parsed without caching the
        # surrounding navigation and unrelated catalogue text.
        if len(page) > 2500000:
            from source_repair import Anchors
            parser = Anchors()
            parser.feed(page[:8000000])
            out, seen = [], set()
            for anchor in parser.links:
                target = absolute_link(url, anchor.get('href', ''))
                rid = procurement_id(target)
                if not rid or host(target) not in PRIMARY or target in seen:
                    continue
                # Do not assume a generic or truncated anchor is an order;
                # the downstream primary-card verifier must confirm demand.
                title = re.sub(r'\\s+', ' ', anchor.get('text', '')).strip()
                if not tender_service_demand(title):
                    continue
                seen.add(target)
                entry = self.discover(target, expected_title=title, source=label)
                if entry:
                    out.append(entry)
                if len(out) >= 50:
                    break
            self.report['sources'][url] = {
                'oversized_html': len(page), 'observed_demand_links': len(seen),
                'verified_cards': sum(not e.get('acquisition_pending', False) for e in out),
            }
            if len(page) > 8000000:
                self.unchecked.add(label + ': oversized listing scanned first 8MB only')
            if not seen:
                self.unchecked.add(label + ': oversized listing has no verified service links')
            return out
        root=DOM(page).root;out=[];seen=set();containers=list(root.find_all(cls='card-item'))
        self.report['menu_links_rejected']+=sum(1 for a in root.find_all('a',attr='href') if not procurement_id(absolute_link(url,a.attrs['href'])))
        if containers:
            for node in containers:
                title=text(node,'card-item__title')
                if not tender_service_demand(title):continue
                links=observed_primary_links(node,url)
                for target in links[:2]:
                    rid=procurement_id(target)
                    if rid in seen:continue
                    seen.add(rid)
                    entry=self.discover(target,expected_title=title,source=label)
                    if entry:out.append(entry)
        else:
            # Corporate lists often have no common CSS. Require a procurement
            # URL, then read the actual card; never use neighbouring menu text.
            links=observed_primary_links(root,url)
            for target in links[:12]:
                rid=procurement_id(target)
                if rid in seen:continue
                seen.add(rid)
                entry=self.discover(target,source=label)
                if entry:out.append(entry)
            if not links:self.unchecked.add(label+': no verified procurement markup or card links')
        self.report['sources'][url]={'card_containers':len(containers),'individual_candidates':len(seen),'verified_cards':sum(not e.get('acquisition_pending',False) for e in out)}
        return out

    def extract_telegram(self,page,label,channel,region):
        base='https://t.me/s/'+channel;coverage={}
        def fetch(url,**kwargs):return page if url==base else self.fetch(url,**kwargs)
        posts=read_history(channel,fetch,days=7,max_pages=12,max_seconds=35,report=coverage)
        out=[];seen=set()
        for post in posts:
            if not post.get('body'):continue
            links = []
            for anchor in post['body'].find_all('a',attr='href'):
                url = absolute_link(post['url'],anchor.attrs['href'])
                if host(url) in PRIMARY and procurement_id(url):
                    anchor_label = anchor.clean()
                    if tender_service_demand(anchor_label): links.insert(0,url)
                    elif len(anchor_label)<12 or re.search(r'\b(?:link|\u0437\u0430\u043a\u0443\u043f\u043a|\u0442\u0435\u043d\u0434\u0435\u0440)',anchor_label,re.I): links.append(url)
                    else: self.outcome('non_service_link')
            for url in links:
                rid=procurement_id(url)
                if rid in seen:continue
                seen.add(rid)
                entry=self.discover(url,source='Telegram / '+channel)
                if entry:
                    entry=dict(entry,discovered_from=post['url'])
                    out.append(entry)
        coverage.update(individual_links=len(seen),verified_cards=sum(not e.get('acquisition_pending',False) for e in out))
        self.report['sources'][base]=coverage
        if not coverage.get('complete'):self.unchecked.add('Tender Telegram/'+channel+': '+coverage['stop_reason'])
        return out

    def verify_entry(self,entry):
        if entry.get('verification',{}).get('acquisition_version')=='cards-v1':
            return bool(entry.get('id')==procurement_id(entry.get('link','')) and parse_deadline(entry.get('deadline')))
        if entry.get('acquisition_pending'):
            result=self.resolve(entry['link'],expected_title=entry.get('title',''))
            if result:entry.update(result);return True
            return False
        return None  # Preserve unrelated legacy contracts in the adapter.

    def resolve(self,url,expected_title=''):
        rid=procurement_id(url)
        if not rid:return None
        if 'TENDER-'+rid in self.known_ids:
            self.outcome('already_recorded');return None
        if url in self.verified:return self.verified[url]
        if len(self.cache) >= self.limit or self.spent >= self.budget:
            self.unchecked.add(url+': CARD_VERIFICATION_BUDGET')
            self.outcome('verification_deferred')
            return None
        self.verified[url]=None
        try:
            root=DOM(self.get(url)).root
            h=host(url)
            if h=='gentender.ru':
                fact={text(n,'fk'):text(n,'fv') for n in root.find_all(cls='fact')}
                actual=fact.get('\u041d\u043e\u043c\u0435\u0440 \u0437\u0430\u043a\u0443\u043f\u043a\u0438','')
                if actual != rid:
                    self.outcome('identity_mismatch');return None
                title=text(root,tag='h1')
                if not tender_service_demand(title):self.outcome('not_service');return None
                address=fact.get('\u041c\u0435\u0441\u0442\u043e \u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0438','')
                import internet_leads_monitor as internet
                if address and not internet.geo_allowed(address):self.outcome('outside_work_region');return None
                # Follow the real source link printed on this exact card.
                links=[u for u in observed_primary_links(root,url) if procurement_id(u)==rid]
                for target in links[:2]:
                    result=self.resolve(target,expected_title=title)
                    if result:
                        self.verified[url]=dict(result,discovered_from=url);return self.verified[url]
                self.unchecked.add('GenTender/'+rid+': primary card or explicit deadline not verified')
                self.outcome('primary_unverified');return None
            if h in B2B:
                entry=self.parse_b2b(root,url,rid)
            elif h=='zakupki.gov.ru':
                entry=self.parse_eis(root,url,rid)
            else:
                self.unchecked.add(h+': unsupported card markup, no automatic acceptance');return None
            if not entry:return None
            if expected_title:
                normalize=lambda s:set(re.findall(r'[\w]+',s.lower()))
                x,y=normalize(expected_title),normalize(entry['title'])
                if x and len(x&y)/max(1,min(len(x),len(y)))<0.55:
                    self.outcome('title_mismatch');return None
            import internet_leads_monitor as internet
            deadline=parse_deadline(entry['deadline'])
            if not tender_service_demand(entry['title']):self.outcome('not_service');return None
            if not internet.geo_allowed(entry['region']):self.outcome('outside_or_unknown_work_region');return None
            if deadline is None or deadline<=datetime.now(MSK):self.outcome('closed_or_unknown_deadline');return None
            entry.update(id=rid,source=h+' / verified individual procurement',acquisition_pending=False,
                verification={'acquisition_version':'cards-v1','id_confirmed':True,'title_confirmed':True,
                              'deadline_confirmed':True,'work_address_confirmed':True,'source_url':url})
            self.verified[url]=entry;self.report['verified_cards']+=1
            return entry
        except Exception as exc:
            # Network and parsing exceptions must not poison the per-run cache.
            # Deterministic rejects above remain cached until the next run.
            self.verified.pop(url, None)
            self.cache.pop(url, None)
            if str(exc)=='SOURCE_HOST_COOLDOWN':
                self.unchecked.add(host(url)+': source temporarily paused after repeated GET failures')
                self.outcome('host_cooldown')
            else:
                self.unchecked.add(url+': '+str(exc)[:140])
                self.outcome('card_unavailable')
            return None

    def parse_b2b(self,root,url,rid):
        title=clean_title(root)
        heading=text(root,tag='h1')
        canonical=next((n.attrs.get('href','') for n in root.find_all('link') if n.attrs.get('rel')=='canonical'),'')
        if not re.search(r'(?<!\d)'+re.escape(rid)+r'(?!\d)',heading) and procurement_id(canonical)!=rid:
            self.outcome('identity_mismatch');return None
        rows={n.attrs.get('id',''):n for n in root.find_all('tr',attr='id')}
        deadline=explicit_date(rows['trade_info_date_end'].clean()) if 'trade_info_date_end' in rows else ''
        addr=rows.get('trade_info_address');address=addr.clean().split(':',1)[-1].strip() if addr else ''
        if not address:
            match=re.search(r'\u043f\u043e \u0430\u0434\u0440\u0435\u0441\u0443\s*:?\s*(.+)$',title,re.I)
            address=match[1] if match else ''
        customer=rows.get('trade-info-organizer-name')
        price=rows.get('trade_info_price')
        return {'title':title,'link':url,'deadline':deadline,'region':address,
                'customer':customer.clean().split(':',1)[-1].strip() if customer else '',
                'price':price.clean().split(':',1)[-1].strip() if price else '',
                'law':'Commercial procurement'}

    def parse_eis(self,root,url,rid):
        # These semantic labels occur on public EIS common-info cards. Unknown
        # JavaScript/challenge pages deliberately do not pass the contract.
        fields={}
        for section in root.find_all('section'):
            label=text(section,'section__title');value=text(section,'section__info')
            if label and value:fields[label.lower()]=value
        title=next((v for k,v in fields.items() if '\u043d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435 \u043e\u0431\u044a\u0435\u043a\u0442\u0430 \u0437\u0430\u043a\u0443\u043f\u043a\u0438' in k),'')
        deadline=next((explicit_date(v) for k,v in fields.items() if '\u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f' in k and '\u043f\u043e\u0434\u0430\u0447\u0438' in k),'')
        address=next((v for k,v in fields.items() if '\u043c\u0435\u0441\u0442\u043e \u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0438' in k or '\u043c\u0435\u0441\u0442\u043e \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f' in k),'')
        if not address:
            match=re.search(r'\u043f\u043e \u0430\u0434\u0440\u0435\u0441\u0443\s*:?\s*(.+)$',title,re.I)
            address=match[1] if match else ''
        number=root.find(cls='cardMainInfo__purchaseLink')
        if not number or rid not in number.clean() or not title or not deadline:
            self.unchecked.add(url+': EIS identity/title/deadline markup not verified');return None
        customer=next((v for k,v in fields.items() if k=='\u043d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435 \u043e\u0440\u0433\u0430\u043d\u0438\u0437\u0430\u0446\u0438\u0438'),'')
        return dict(title=title,link=url,deadline=deadline,region=address,customer=customer,price=text(root,'cost'),law='EIS')
