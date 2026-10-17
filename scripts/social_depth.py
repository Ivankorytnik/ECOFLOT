"""Read public Telegram history using observed pagination links, never a login.

The report distinguishes a reached date boundary from a bounded/incomplete scan.
"""
from datetime import datetime, timedelta, timezone
import re
import time
from urllib.parse import urlsplit, parse_qs
from source_markup import DOM, absolute_link


def parse_public_page(page, channel):
    root = DOM(page).root
    messages, seen = [], set()
    for node in root.find_all(attr='data-post'):
        match = re.fullmatch(r'([A-Za-z0-9_]+)/([1-9]\d*)', node.attrs['data-post'])
        if not match or match[1].lower() != channel.lower() or match[2] in seen:
            continue
        seen.add(match[2])
        body = node.find(cls='tgme_widget_message_text')
        stamp = node.find('time', attr='datetime')
        try:
            dt = datetime.fromisoformat(stamp.attrs['datetime'].replace('Z','+00:00')) if stamp else None
            if dt and dt.tzinfo is None:
                dt = None
        except ValueError:
            dt = None
        post_url = 'https://t.me/'+match[1]+'/'+match[2]
        links = []
        for anchor in node.find_all('a', attr='href'):
            if not anchor.visible():
                continue
            # Link previews are part of a post, unlike its footer/author links.
            in_body = False
            parent = anchor
            while parent is not None and parent is not node:
                in_body = in_body or parent is body
                parent = parent.parent
            if not (in_body or anchor.has('tgme_widget_message_link_preview')):
                continue
            url = absolute_link(post_url, anchor.attrs['href'])
            if url and url not in links:
                links.append(url)
        messages.append({'id':match[2], 'channel':match[1], 'published':dt,
                         'text':body.text().strip() if body else '',
                         'body':body, 'markup':node.markup(), 'links':links,
                         'url':post_url})
    base = 'https://t.me/s/'+channel
    next_url = ''
    for link in root.find_all('a', attr='href'):
        if not link.has('tme_messages_more'):
            continue
        url = absolute_link(base, link.attrs['href'], same_host=True)
        p = urlsplit(url)
        before = parse_qs(p.query).get('before',[''])[0]
        if p.path == '/s/'+channel and re.fullmatch(r'[1-9]\d*',before):
            next_url = url
            break
    return messages, next_url


def read_history(channel, fetch, *, days=7, max_pages=30, max_seconds=70, now=None, report=None):
    if not re.fullmatch(r'[A-Za-z0-9_]{5,64}',channel):
        raise ValueError('INVALID_PUBLIC_CHANNEL')
    report = report if report is not None else {}
    report.update(channel=channel,pages=0,posts=0,missing_dates=0,complete=False,stop_reason='not_started')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    cutoff, deadline = now-timedelta(days=days), time.monotonic()+max_seconds
    url, seen, page_keys, output = 'https://t.me/s/'+channel, set(), set(), []
    previous_cursor = None
    for _ in range(max_pages):
        if time.monotonic() >= deadline:
            report['stop_reason'] = 'time_limit'
            break
        try:
            page = fetch(url, timeout=max(1,min(15,deadline-time.monotonic())))
            posts, older = parse_public_page(page,channel)
        except Exception as exc:
            report.update(stop_reason='access_or_parse_error',error=str(exc)[:200])
            break
        report['pages'] += 1
        if not posts:
            report['stop_reason'] = 'public_posts_unavailable'
            break
        signature = tuple(p['id'] for p in posts)
        if signature in page_keys:
            report['stop_reason'] = 'pagination_stalled'
            break
        page_keys.add(signature)
        dated = []
        for post in posts:
            if post['id'] in seen:
                continue
            seen.add(post['id'])
            stamp = post['published']
            if stamp is None:
                report['missing_dates'] += 1
            else:
                dated.append(stamp)
                if cutoff <= stamp <= now+timedelta(minutes=5):
                    output.append(post)
        report['posts'] = len(seen)
        # A single pinned old post must not prematurely terminate fresh history.
        if dated and max(dated) < cutoff:
            report.update(complete=not report['missing_dates'],stop_reason='date_boundary')
            break
        if not older:
            report.update(complete=not report['missing_dates'],stop_reason='history_end')
            break
        cursor = int(parse_qs(urlsplit(older).query)['before'][0])
        if previous_cursor is not None and cursor >= previous_cursor:
            report['stop_reason'] = 'pagination_stalled'
            break
        previous_cursor = cursor
        report['next_url'] = older
        url = older
    else:
        report['stop_reason'] = 'page_limit'
    report['recent_posts'] = len(output)
    report['cutoff'] = cutoff.isoformat()
    return output


def scoped_contacts(body, channel=''):
    """Phone/email from full post text; contact hrefs only inside the post body."""
    from internet_leads_monitor import extract_public_contact
    if body is None:
        return {'phone':'','contact_url':'','contact_text':'','contact_evidence_required':True}
    text = body.text()
    # Promotional channel URLs and arbitrary post links cannot count as contacts.
    plain = re.sub(r'(?:https?://|www\.)[^\s<>]+',' ',text,flags=re.I)
    plain = re.sub(r'(?<![\w.])@[A-Za-z0-9_]{5,64}\b',' ',plain)
    phone, contact = extract_public_contact(plain)
    if contact and not contact.startswith('mailto:'):
        contact = ''
    evidence = []
    for link in body.find_all('a',attr='href'):
        if not link.visible():
            continue
        url = link.attrs['href']
        p = urlsplit(url)
        if p.scheme == 'tel':
            value,_ = extract_public_contact(p.path)
            if value:
                phone = phone or value
                evidence.append('tel:'+value)
        elif p.scheme == 'mailto' and re.fullmatch(r'[^\s@]+@[^\s@]+\.[A-Za-z]{2,}',p.path):
            contact = contact or 'mailto:'+p.path
            evidence.append('mailto:'+p.path)
        elif p.scheme == 'https' and p.hostname in ('t.me','telegram.me'):
            user = p.path.strip('/')
            context = link.parent.clean() if link.parent else ''
            if (re.fullmatch(r'[A-Za-z0-9_]{5,32}',user) and user.lower()!=channel.lower()
                    and not user.lower().endswith('bot')
                    and re.search(r'\b(?:contact|telegram)|\u043a\u043e\u043d\u0442\u0430\u043a\u0442|\u0441\u0432\u044f\u0437|\u043f\u0438\u0448|\u043d\u0430\u043f\u0438\u0441|\u0442\u0435\u043b\u0435\u0433\u0440\u0430\u043c',context,re.I)):
                contact = contact or url
                evidence.append(url)
        elif p.scheme=='https' and p.hostname=='wa.me' and re.fullmatch(r'\+?\d{10,15}',p.path.strip('/')):
            contact = contact or url
            evidence.append(url)
    # An explicit labelled @handle that was not hyperlinked is still a contact.
    m = re.search(r'(?:\u043a\u043e\u043d\u0442\u0430\u043a\u0442|\u0441\u0432\u044f\u0437|\u043f\u0438\u0448\u0438\u0442\u0435|\u0442\u0435\u043b\u0435\u0433\u0440\u0430\u043c|telegram)[^\n@]{0,55}@([A-Za-z0-9_]{5,32})\b',text,re.I)
    if m and m[1].lower()!=channel.lower() and not m[1].lower().endswith('bot'):
        contact = contact or 'https://t.me/'+m[1]
    return {'phone':phone,'contact_url':contact,'contact_text':plain,
            'contact_evidence_required':True,'contact_evidence':evidence}
