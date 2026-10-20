#!/usr/bin/env python3
"""Read-only live source smoke: GET public pages, never send/write leads.

Logs counts and source availability only. No phone numbers, user data,
credentials, sheet calls or requests to the ECOFLOT webhook.
"""
import json
import time
from urllib.parse import urlsplit

import internet_leads_monitor as m
from primary_source_recovery import collect_propokupki, parse_samosval_orders
from social_depth import read_history
from tender_acquisition import TenderAcquisition

def inspect(name, work):
    started=time.monotonic()
    try:
        result=work()
        return dict(source=name, ok=True, seconds=round(time.monotonic()-started,2), **result)
    except Exception as exc:
        return dict(source=name, ok=False, seconds=round(time.monotonic()-started,2),
                    reason=type(exc).__name__+': '+str(exc)[:130])

def propokupki():
    items, errors=collect_propokupki(m)
    return dict(verified_candidates=len(items), issues=len(errors),
                contact_routes=sum(bool(x.get('phone') or x.get('contact_url')) for x in items),
                sample_hosts=list(dict.fromkeys(urlsplit(x.get('url','')).hostname for x in items))[:5])

def samosval():
    label,url=m.SAMOSVAL_INFO_SOURCES[0]
    page=m.fetch(url,timeout=15,attempts=1)
    items=parse_samosval_orders(m,page,url)
    return dict(bytes=len(page), verified_candidates=len(items),
                distinct_order_ids=len({x['request_id'] for x in items}))

def telegram():
    coverage={}
    posts=read_history('samosvalinfo',m.fetch,days=7,max_pages=4,max_seconds=40,report=coverage)
    return dict(recent_posts=len(posts),pages=coverage.get('pages',0),
                complete=coverage.get('complete',False),
                stop_reason=coverage.get('stop_reason','unknown'))

def b2b():
    url='https://www.b2b-center.ru/search/moskva/samosvaly/'
    import tender_monitor
    page=tender_monitor.fetch(url,timeout=18)
    scanner=TenderAcquisition(lambda *_a,**_kw: '',defer_resolution=True)
    entries=scanner.extract_direct(page,'B2B-Center',url,'Москва')
    return dict(bytes=len(page), individual_service_links=len(entries),
                oversized=len(page)>2500000)

def main():
    data=[inspect('ProPokupki',propokupki),inspect('Samosval.info',samosval),
          inspect('Telegram public channel',telegram),inspect('B2B-Center listing',b2b)]
    print(json.dumps(dict(probe='ECOFLOT-public-GET-only',data=data),ensure_ascii=False,indent=2))
    # One offline green test does not guarantee source availability: require
    # at least one verified primary GET to establish the real data path.
    return 0 if any(x['ok'] for x in data) else 2

if __name__=='__main__':
    raise SystemExit(main())
