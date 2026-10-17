#!/usr/bin/env python3
"""Bounded GET-only verification. No CRM changes or Telegram sends."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from card_acquisition import Acquisition, known_card
from social_depth import read_history, scoped_contacts
from tender_acquisition import TenderAcquisition
from tender_intake import prioritize, intake_key
import internet_leads_monitor as internet
import social_leads_monitor as social
import tender_monitor as tender


def main():
    report = dict(at=datetime.now(timezone.utc).isoformat(), read_only=True,
                  leads_created=0, messages_sent=0, channels=[], cards=[], tenders=[])
    def fetch(url, **kwargs):
        return internet.fetch(url, timeout=kwargs.get('timeout', 12), attempts=1)
    def forbidden(*args, **kwargs):
        raise AssertionError('VERIFICATION_MUST_NOT_SEND')
    def read_channel(pair):
        label, channel = pair
        coverage = {}
        posts = read_history(channel, fetch, max_pages=50, max_seconds=40, report=coverage)
        items = []
        for post in posts:
            if not post['text'] or not social.demand_ok(post['text']) or not internet.matched_geo(post['text']):
                continue
            item = dict(title=social.social_title(post['text']), url=post['url'], description=post['text'],
                        card_links=[url for url in post.get('links', []) if known_card(url)])
            item.update(scoped_contacts(post['body'], channel))
            items.append(item)
        coverage.update(eligible_posts=len(items), observed_card_links=sum(len(i['card_links']) for i in items))
        return coverage, items
    with patch.object(internet, 'send_webhook', forbidden), patch.object(social, 'send_webhook', forbidden), patch.object(tender, 'send_webhook', forbidden):
        with ThreadPoolExecutor(max_workers=3) as pool:
            sources = list(pool.map(read_channel, social.CHANNELS))
        contact_reader = Acquisition(fetch, limit=12, budget=45)
        for coverage, items in sources:
            report['channels'].append(coverage)
            for item in items[:2]:
                before = bool(item.get('phone') or item.get('contact_url'))
                contact_reader.enrich(item)
                report['cards'].append(dict(post=item['url'], links=item['card_links'],
                    contact_in_post=before, card_verified=bool(item.get('card_verified')),
                    contact_available=bool(item.get('phone') or item.get('contact_url')),
                    contact_source=item.get('contact_source_url', '')))
        reader = TenderAcquisition(fetch, limit=28, budget=110, defer_resolution=True)
        entries = []
        for label, channel, region in tender.TELEGRAM_TENDER_SOURCES:
            try:
                entries.extend(reader.extract_telegram(fetch('https://t.me/s/'+channel), label, channel, region))
            except Exception as exc:
                reader.unchecked.add(channel+': '+str(exc)[:140])
        for label, url in tender.SOURCES[:2]:
            try:
                entries.extend(e for e in reader.extract_gentender(fetch(url), label)
                               if __import__('search_reliability').tender_service_demand(e.get('title')))
            except Exception as exc:
                reader.unchecked.add(label+': '+str(exc)[:140])
        unique = {entry['id']: entry for entry in entries}
        ordered = prioritize([(entry, intake_key(entry)) for entry in unique.values()])
        report['tender_candidates'] = len(ordered)
        for entry, _ in ordered:
            if reader.verify_entry(entry):
                report['tenders'].append({k: entry.get(k) for k in ('id','title','link','deadline','region','verification')})
        report.update(contact_report=contact_reader.report, contact_unchecked=sorted(contact_reader.unchecked),
                      tender_report=reader.report, tender_unchecked=sorted(reader.unchecked))
    folder = Path('acquisition-evidence'); folder.mkdir(exist_ok=True)
    (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
