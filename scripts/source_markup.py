"""Small, dependency-free DOM reader for public source cards.

Data outside the selected card (navigation, footer, scripts) is never a contact.
"""
from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit, urljoin

VOID = frozenset(('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'))
IGNORE = frozenset(('script','style','noscript','svg','nav','footer','header'))

class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
        self.children = []

    def has(self, cls):
        return cls in self.attrs.get('class', '').split()

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find(self, tag=None, cls=None, attr=None):
        return next(self.find_all(tag, cls, attr), None)

    def find_all(self, tag=None, cls=None, attr=None):
        for node in self.walk():
            if (tag is None or node.tag == tag) and (cls is None or node.has(cls)) and (attr is None or attr in node.attrs):
                yield node

    def visible(self):
        current = self
        while current is not None:
            style = (current.attrs.get('style') or '').replace(' ', '').lower()
            if (current.tag in IGNORE or 'hidden' in current.attrs or current.attrs.get('aria-hidden') == 'true'
                    or 'display:none' in style or 'visibility:hidden' in style):
                return False
            current = current.parent
        return True

    def text(self):
        if self.tag in IGNORE or 'hidden' in self.attrs or self.attrs.get('aria-hidden') == 'true':
            return ''
        style = self.attrs.get('style', '').replace(' ', '').lower()
        if 'display:none' in style or 'visibility:hidden' in style:
            return ''
        if self.tag == 'br':
            return '\n'
        chunks = [c.text() if isinstance(c, Node) else c for c in self.children]
        text = ''.join(chunks)
        if self.tag in ('p','div','li','tr','article','section','h1','h2','h3','h4','dt','dd'):
            text = '\n' + text + '\n'
        return text

    def clean(self):
        return re.sub(r'\s+', ' ', self.text()).strip()

    def markup(self):
        if not self.tag:
            return ''.join(c.markup() if isinstance(c, Node) else escape(c) for c in self.children)
        attrs = ''.join(' '+k+'="'+escape(v or '', quote=True)+'"' for k,v in self.attrs.items())
        start = '<'+self.tag+attrs+'>'
        if self.tag in VOID:
            return start
        return start + ''.join(c.markup() if isinstance(c, Node) else escape(c) for c in self.children) + '</'+self.tag+'>'

class DOM(HTMLParser):
    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root
        if len(page) > 2500000:
            raise ValueError('SOURCE_PAGE_TOO_LARGE')
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def absolute_link(base, href, same_host=False):
    try:
        url = urljoin(base, href).split('#',1)[0]
        p, b = urlsplit(url), urlsplit(base)
        if p.scheme not in ('https','http') or p.username or p.password or p.port not in (None,80,443):
            return ''
        if same_host and (p.hostname or '').removeprefix('www.') != (b.hostname or '').removeprefix('www.'):
            return ''
        return url
    except (ValueError,TypeError):
        return ''
