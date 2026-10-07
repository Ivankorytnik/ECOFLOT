"""Fail closed when the tabular feed loses an approved recipient's ID.

Mixed numeric/text spreadsheet columns may return a null minority-typed ID.
An approved row with no usable ID must not silently shrink the audience.
"""
import re

APPROVED = frozenset(('approved', '\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d'))


def active_chats(rows):
    approved, excluded = set(), set()
    for index, row in enumerate(rows, 2):
        if not row or not any(value is not None and str(value).strip() for value in row):
            continue
        if len(row) < 2:
            raise ValueError('RECIPIENT_ROW_INCOMPLETE:' + str(index))
        raw, role = row[:2]
        chat = '' if raw is None else str(raw).strip()
        role = str(role or '').strip().casefold().replace('\u0451', '\u0435')
        if role in APPROVED:
            if not re.fullmatch(r'-?\d+', chat):
                raise ValueError('APPROVED_RECIPIENT_ID_MISSING_OR_INVALID:' + str(index))
            approved.add(chat)
        elif chat:
            if not re.fullmatch(r'-?\d+', chat):
                raise ValueError('RECIPIENT_ID_INVALID:' + str(index))
            excluded.add(chat)
    return approved - excluded
