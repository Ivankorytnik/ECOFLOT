"""Narrow correction for verified foreman-only false positives. No I/O to services."""
from pathlib import Path
import hashlib
p = Path('scripts/internet_leads_monitor.py')
b = p.read_bytes()
s = b.decode('utf-8')
old = '|плиточник[а-я]*)'
new = '|плиточник[а-я]*|прораб[а-я]*|бригадир[а-я]*)'
if new not in s:
    blob = hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()
    if blob != 'ed7451342073824b41621c1e63cca7c059c2b0b5' or s.count(old) != 1:
        raise RuntimeError('SOURCE_CHANGED: rebase and review before applying')
    s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8')
print('Foreman-only orders rejected; explicit equipment or haulage demand remains allowed.')
