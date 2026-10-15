"""Fix observed false-positive lead classification; no network or notifications."""
from pathlib import Path

MARKER = '# ECOFLOT quality repair 2026-10-15'

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source changed; refusing ambiguous replacement: ' + old[:80])
    return text.replace(old, new, 1)

def main():
    path = Path('scripts/internet_leads_monitor.py')
    text = path.read_text('utf-8')
    if MARKER in text:
        print('Quality repair already applied')
        return
    old = '    if any(x in hay for x in labor_markers) and not any(x in hay for x in explicit_ecoflot_demand):\n'
    new = '''    # ECOFLOT quality repair 2026-10-15
    labor_role = re.search(r'\b(?:разнорабоч[а-я]*|подсобн[а-я]*|монтажник[а-я]*|каменщик[а-я]*|маляр[а-я]*|штукатур[а-я]*|плиточник[а-я]*)\b', hay)
    if (any(x in hay for x in labor_markers) or labor_role) and not any(x in hay for x in explicit_ecoflot_demand):
'''.replace('\x08', r'\b')
    text = once(text, old, new)
    old = '    if any(x in hay for x in ("тко","контейнерная площадка","регулярный вывоз")):\n'
    new = '    if re.search(r"\\bтко\\b", hay) or any(x in hay for x in ("контейнерная площадка","регулярный вывоз")):\n'
    text = once(text, old, new)
    old = '''def infer_work_equipment(title, description):
    hay = normalize((title or "") + " " + (description or ""))
'''
    new = old + '''    if (re.search(r'\bрасчистк[а-я]*\s+(?:участ[а-я]*|территори[а-я]*)\b', hay)
            or re.search(r'\bснять\s+(?:растительный\s+)?слой\s+(?:почвы|грунта)\b', hay)
            or 'снятие растительного слоя' in hay):
        return "Расчистка участка / снятие растительного слоя", "Экскаватор-погрузчик / самосвал"
'''.replace('\x08', r'\b')
    text = once(text, old, new)
    path.write_text(text, encoding='utf-8')
    print('Fixed abbreviation boundaries, land clearing, and worker-only requests.')

if __name__ == '__main__':
    main()
