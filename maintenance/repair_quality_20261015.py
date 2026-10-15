"""Fix observed false-positive classification and URL-derived phone numbers."""
from pathlib import Path

MARKER = '# ECOFLOT quality repair 2026-10-15'
PHONE_MARKER = '# ECOFLOT phone evidence repair 2026-10-15'

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source changed; refusing ambiguous replacement: ' + old[:80])
    return text.replace(old, new, 1)

def main():
    path = Path('scripts/internet_leads_monitor.py')
    text = path.read_text('utf-8')
    if MARKER not in text:
        old = '    if any(x in hay for x in labor_markers) and not any(x in hay for x in explicit_ecoflot_demand):\n'
        new = r'''    # ECOFLOT quality repair 2026-10-15
    labor_role = re.search(r'\b(?:разнорабоч[а-я]*|подсобн[а-я]*|монтажник[а-я]*|каменщик[а-я]*|маляр[а-я]*|штукатур[а-я]*|плиточник[а-я]*)\b', hay)
    if (any(x in hay for x in labor_markers) or labor_role) and not any(x in hay for x in explicit_ecoflot_demand):
'''
        text = once(text, old, new)
        old = '    if any(x in hay for x in ("тко","контейнерная площадка","регулярный вывоз")):\n'
        new = '    if re.search(r"\\bтко\\b", hay) or any(x in hay for x in ("контейнерная площадка","регулярный вывоз")):\n'
        text = once(text, old, new)
        old = '''def infer_work_equipment(title, description):
    hay = normalize((title or "") + " " + (description or ""))
'''
        new = old + r'''    if (re.search(r'\bрасчистк[а-я]*\s+(?:участ[а-я]*|территори[а-я]*)\b', hay)
            or re.search(r'\bснять\s+(?:растительный\s+)?слой\s+(?:почвы|грунта)\b', hay)
            or 'снятие растительного слоя' in hay):
        return "Расчистка участка / снятие растительного слоя", "Экскаватор-погрузчик / самосвал"
'''
        text = once(text, old, new)
    if PHONE_MARKER not in text:
        old = '    m = phone_re.search(raw)\n'
        new = r'''    # ECOFLOT phone evidence repair 2026-10-15
    # Numeric groups inside URLs and UUIDs are not customer phone evidence.
    phone_text = re.sub(r'(?:https?://|www\.)[^\s<>]+', ' ', raw, flags=re.I)
    phone_text = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', ' ', phone_text, flags=re.I)
    m = phone_re.search(phone_text)
'''
        text = once(text, old, new)
    path.write_text(text, encoding='utf-8')
    print('Quality and phone evidence repairs applied idempotently.')

if __name__ == '__main__':
    main()
