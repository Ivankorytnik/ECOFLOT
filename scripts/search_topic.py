"""Query-aware result filtering before any third-party page is requested."""
import re
from urllib.parse import urlsplit, unquote
from source_repair import (Anchors, unwrap_result, host_is, UnverifiedSearch,
                           parse_results as base_parse_results)


def result_matches_query(url, title, query):
    """Reject unrelated engine fallbacks before fetching third-party pages."""
    if not query:
        return True
    query = query.lower().replace('\u0451', '\u0435')
    scoped = re.search(r'(?:^|\s)site:([a-z0-9.-]+)(?:/([^\s]+))?', query)
    if scoped:
        domain, path = scoped.groups()
        parsed = urlsplit(url)
        if not host_is(parsed.hostname or '', (domain,)):
            return False
        if path and not unquote(parsed.path).startswith('/' + path):
            return False
    topics = {
        '\u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b': ('\u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b', 'samosval', 'dump-truck'),
        '\u0442\u043e\u043d\u0430\u0440': ('\u0442\u043e\u043d\u0430\u0440', 'tonar'),
        '\u044d\u043a\u0441\u043a\u0430\u0432\u0430\u0442\u043e\u0440': ('\u044d\u043a\u0441\u043a\u0430\u0432\u0430\u0442\u043e\u0440', 'ekskavator', 'exkavator', 'excavator'),
        '\u0441\u043f\u0435\u0446\u0442\u0435\u0445': ('\u0441\u043f\u0435\u0446\u0442\u0435\u0445', 'specteh', 'spetsteh', 'spectex', 'spetste'),
        '\u0433\u0440\u0443\u043d\u0442': ('\u0433\u0440\u0443\u043d\u0442', 'grunt'),
        '\u043c\u0443\u0441\u043e\u0440': ('\u043c\u0443\u0441\u043e\u0440', 'musor'),
        '\u043e\u0442\u0445\u043e\u0434': ('\u043e\u0442\u0445\u043e\u0434', 'othod', 'otkhod'),
        '\u043a\u043e\u043d\u0442\u0435\u0439\u043d\u0435\u0440': ('\u043a\u043e\u043d\u0442\u0435\u0439\u043d\u0435\u0440', 'konteiner', 'konteyner'),
        '\u0434\u0435\u043c\u043e\u043d\u0442\u0430\u0436': ('\u0434\u0435\u043c\u043e\u043d\u0442\u0430\u0436', 'demontazh'),
        '\u043f\u0433\u0441': ('\u043f\u0433\u0441', 'pgs'),
        '\u0449\u0435\u0431': ('\u0449\u0435\u0431', 'scheb', 'shcheb'),
        '\u0438\u043b\u043e\u0441\u043e\u0441': ('\u0438\u043b\u043e\u0441\u043e\u0441', 'ilosos'),
        '\u0430\u0441\u0441\u0435\u043d\u0438\u0437': ('\u0430\u0441\u0441\u0435\u043d\u0438\u0437', 'asseniz'),
        '\u0436\u0431\u043e': ('\u0436\u0431\u043e', 'zhbo'),
    }
    needles = {word for topic, words in topics.items() if topic in query for word in words}
    hay = (unquote(url) + ' ' + str(title)).lower().replace('\u0451', '\u0435')
    return not needles or any(word in hay for word in needles)


def parse_results(page, engine, query=None):
    urls = base_parse_results(page, engine)
    if not query or not urls:
        return urls
    parser = Anchors(); parser.feed(page or '')
    labels = {}
    for anchor in parser.links:
        url = unwrap_result(anchor['href'], engine)
        if url:
            labels[url] = labels.get(url, '') + ' ' + anchor['text']
    relevant = [url for url in urls if result_matches_query(url, labels.get(url, ''), query)]
    if not relevant:
        raise UnverifiedSearch(engine+': results do not match the requested topic or site')
    return relevant
