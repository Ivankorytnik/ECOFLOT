"""Replace only the incompatible reporting function after checking its blob."""
from pathlib import Path
import hashlib
p=Path('scripts/full_cycle_orchestrator.py')
b=p.read_bytes()
s=b.decode('utf-8')
marker='from search_reporting import publish_cycle'
if marker not in s:
    blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    if blob!='dc4dfb5604090fa8ee693a70160b708bbcfa0cb9':
        raise RuntimeError('COORDINATOR_CHANGED: rebase before applying')
    start=s.index('def send_cycle_notice(state):')
    end=s.index('\n\ndef main():',start)
    s=s[:start]+'''def send_cycle_notice(state):
    from search_reporting import publish_cycle
    publish_cycle(state)
'''+s[end:]
    p.write_text(s,encoding='utf-8')
print('Native search_complete reporting installed; no server code replaced.')
