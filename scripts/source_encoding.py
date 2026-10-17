"""Decode public source text using declared encoding, not replacement glyphs."""
import re

# Narrow text-only codecs. Never dispatch arbitrary codecs from remote content.
CODECS = {
    'utf-8': 'utf-8', 'utf8': 'utf-8',
    'windows-1251': 'cp1251', 'cp1251': 'cp1251',
    'windows-1252': 'cp1252', 'cp1252': 'cp1252',
    'koi8-r': 'koi8-r', 'koi8-u': 'koi8-u',
    'iso-8859-5': 'iso8859-5', 'iso-8859-1': 'iso8859-1',
}
CHARSET = re.compile(r'charset\s*=\s*[\"\x27]?\s*([A-Za-z0-9._-]+)', re.I)


def decode_public_text(raw: bytes, content_type: str = '') -> str:
    if not isinstance(raw, bytes):
        raise TypeError('PUBLIC_RESPONSE_MUST_BE_BYTES')
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    declaration = CHARSET.search(str(content_type))
    if declaration is None:
        # Only declarations in the head, not a charset mention in a post body.
        head = raw[:16384].decode('ascii', 'ignore').split('</head>', 1)[0]
        head = re.sub(r'<!--[\s\S]*?-->', '', head)
        for tag in re.findall(r'<meta\b[^>]*>', head, re.I):
            declaration = CHARSET.search(tag)
            if declaration:
                break
        if declaration is None:
            declaration = re.search(r'^\s*<\?xml\b[^>]*encoding\s*=\s*[\"\x27]([A-Za-z0-9._-]+)', head, re.I)
    label = declaration.group(1).lower() if declaration else 'utf-8'
    codec = CODECS.get(label)
    if codec is None:
        raise ValueError('UNSUPPORTED_PUBLIC_TEXT_ENCODING: ' + label)
    # Bad bytes remain a visible acquisition error, not apparent empty content.
    return raw.decode(codec, errors='strict')


def decode_response(response) -> str:
    headers = getattr(response, 'headers', None)
    content_type = headers.get('Content-Type', '') if headers is not None else ''
    return decode_public_text(response.read(), content_type)
