"""Fair procurement verification order; discovery is not acceptance."""
from collections import OrderedDict, deque
import hashlib
import re
from urllib.parse import urlsplit
from search_reliability import tender_service_demand


def intake_key(entry):
    return hashlib.sha1(str(entry.get('id') or entry.get('link') or '').encode('utf-8')).hexdigest()


def source_group(entry):
    return str(entry.get('intake_source') or urlsplit(entry.get('link', '')).hostname or 'unknown')


def priority(entry):
    title = str(entry.get('title', '')).lower().replace('\u0451', '\u0435')
    strong = bool(re.search(r'\u0432\u044b\u0432\u043e\u0437|\u043f\u043e\u0433\u0440\u0443\u0437|\u0441\u0430\u043c\u043e\u0441\u0432\u0430\u043b|\u043a\u043e\u0442\u043b\u043e\u0432\u0430\u043d|\u0440\u0430\u0441\u0447\u0438\u0441\u0442', title))
    return (0 if strong else 1 if tender_service_demand(title) else 2, str(entry.get('id', '')))


def should_skip_verification(entry):
    """Discard only clearly unrelated titled hints before spending card budget.

    Empty or generic headlines must still reach the primary-card verifier.
    A service title always wins, even if it contains a banned noun.
    """
    if not entry.get('acquisition_pending'):
        return False
    title = str(entry.get('title') or '').lower().replace('\u0451', '\u0435').strip()
    if not title or tender_service_demand(title):
        return False
    return bool(re.search(
        r'\b(?:\u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0430|\u043f\u0440\u0438\u043e\u0431\u0440\u0435\u0442\u0435\u043d\u0438\u0435|'
        r'\u0431\u0440\u043e\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435|\u043e\u0445\u0440\u0430\u043d\u0430|'
        r'\u0433\u0435\u043e\u0434\u0435\u0437\u0438\u0447\u0435\u0441\u043a\u0438\u0435)\b', title)
        or '\u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 ' in title
        or '\u0437\u0430\u043f\u0430\u0441\u043d\u044b\u0445 \u0447\u0430\u0441\u0442\u0435\u0439' in title)


def prioritize(candidates):
    """Round-robin sources. Unknown titles remain candidates, not clean zeroes."""
    groups = OrderedDict()
    for pair in candidates:
        groups.setdefault(source_group(pair[0]), []).append(pair)
    queues = [deque(sorted(items, key=lambda pair: priority(pair[0]))) for items in groups.values()]
    result = []
    while queues:
        remaining = []
        for queue in queues:
            result.append(queue.popleft())
            if queue:
                remaining.append(queue)
        queues = remaining
    return result
