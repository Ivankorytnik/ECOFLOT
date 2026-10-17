#!/usr/bin/env python3
"""Public read-only acquisition verification; never imports or calls send paths."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from card_acquisition import Acquisition
from social_depth import parse_public_page, read_history, scoped_contacts
from tender_acquisition import TenderAcquisition, procurement_id
import internet_leads_monitor as internet
import social_leads_monitor as social


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--fixtures',required=True)
    args.add_argument('--output',required=True)
    args.add_argument('--offline',action='store_true')
    options=args.parse_args()
    root=Path(options.fixtures)
    manifest=json.loads((root/'manifest.json').read_text())
    cached={x['url']:(root/(x['name']+'.html')).read_text() for x in manifest if (root/(x['name']+'.html')).exists()}
    def fetch(url,**kwargs):
        if url in cached:return cached[url]
        if options.offline:raise RuntimeError('NO_OFFLINE_FIXTURE')
        return internet.fetch(url,timeout=kwargs.get('timeout',12),attempts=1)
    # Guard every possible production delivery entrypoint during the diagnosis.
    def forbidden(*a,**k):raise AssertionError('SMOKE_MUST_NOT_SEND')
    result={'read_only':True,'checked_at':datetime.now(timezone.utc).isoformat(),'telegram':[], 'cards':{}, 'tenders':{}}
    with patch.object(internet,'send_webhook',forbidden),patch.object(social,'send_webhook',forbidden):
        acquisition=Acquisition(fetch,limit=12,budget=35)
        for name,method,url in (
            ('exkavator','parse_exkavator','https://exkavator.ru/exchange/rent/main.html'),
            ('nerudonline','parse_nerudonline','https://nerudonline.ru/rabota/samosvaly'),
            ('rentag','parse_rentag','https://rentag.ru/arenda-spectehniki/zayavki')):
            try:
                items=getattr(acquisition,method)(fetch(url),url)
                for item in items[:2]:acquisition.enrich(item)
                result['cards'][name]={'individual_candidates':len(items),
                    'contact_ready':sum(internet.ensure_public_contact(dict(i))[0] for i in items),
                    'examples':[{'id':i['request_id'],'url':i['url']} for i in items[:3]]}
            except Exception as exc:result['cards'][name]={'error':str(exc)[:200]}
        result['card_acquisition']=acquisition.report
        result['card_unchecked']=sorted(acquisition.unchecked)
        for channel in ('vsem_podryad','samosvalam_rabota','rabota_dlya_samosvalov_promsru','samosvalinfo',
                        'dumptrucks_work','spezteh','tonary_karery'):
            report={}
            posts=read_history(channel,fetch,days=7,max_pages=30,max_seconds=35,report=report)
            count=0
            for post in posts:
                if social.demand_ok(post['text']) and internet.matched_geo(post['text']):
                    contacts=scoped_contacts(post['body'],channel)
                    count+=bool(contacts['phone'] or contacts['contact_url'])
            report['geo_service_with_public_contact']=count
            result['telegram'].append(report)
        tender=TenderAcquisition(fetch,limit=14,budget=65)
        url='https://gentender.ru/tenders/utilizaciya-othodov/moskva'
        try:
            entries=tender.extract_gentender(fetch(url),'Moscow')
            result['tenders']['gentender_observed_individual_links']=len(entries)
        except Exception as exc:result['tenders']['gentender_error']=str(exc)[:180]
        # The procurement is obtained from the FSK post, never invented by ID.
        url='https://t.me/s/fsk_tenders'
        try:
            found=tender.extract_telegram(fetch(url),'FSK','fsk_tenders','Moscow')
            result['tenders']['fsk_verified']=[{'id':i['id'],'title':i['title'],'deadline':i['deadline'],
                'work_address':i['region'],'url':i['link']} for i in found]
        except Exception as exc:result['tenders']['fsk_error']=str(exc)[:180]
        result['tender_acquisition']=tender.report
        result['tender_unchecked']=sorted(tender.unchecked)
    Path(options.output).parent.mkdir(parents=True,exist_ok=True)
    Path(options.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    # Source outages are evidence, not assertion failures or clean empty searches.
    # Offline contracts are enforced in the separate complete regression suite.
    return 0


if __name__=='__main__':raise SystemExit(main())
