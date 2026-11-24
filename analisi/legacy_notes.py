"""Recover editable text and supported emphasis from imported notes."""
import re

from .info import MAX_INFO_NOTES, MAX_NOTE_STYLES, NOTE_BOLD, NOTE_ITALIC, NOTE_UNDERLINE, _text

WORKSHEET_NOTES = "legacy_worksheet_notes"
_RANGE = re.compile(r"(0|[1-9][0-9]{0,5})~(0|[1-9][0-9]{0,5})")
_INLINE = {"B": NOTE_BOLD, "I": NOTE_ITALIC, "U": NOTE_UNDERLINE}


def checked_text(value):
    if not _text(value, MAX_INFO_NOTES):
        raise ValueError("Invalid imported note text.")
    return value


def archive_note(value):
    if isinstance(value, str):
        return checked_text(value), ()
    if not isinstance(value, dict):
        raise ValueError("Invalid imported formatted note.")
    text = checked_text(value.get("string"))
    formatting = value.get("formatting")
    if not isinstance(formatting, list) or len(formatting) > MAX_NOTE_STYLES:
        return text, ()
    # The indexed runs verified on the source files contain only BMP text.
    if any(ord(char) > 0xFFFF for char in text):
        return text, ()
    spans, stop = [], 0
    for run in formatting:
        if not isinstance(run, dict):
            return text, ()
        span, attributes = run.get("range"), run.get("attributes")
        match = _RANGE.fullmatch(span) if isinstance(span, str) else None
        if match is None or not isinstance(attributes, dict):
            return text, ()
        first, last = map(int, match.groups())
        if not stop <= first <= last < len(text):
            return text, ()
        stop = last + 1
        mask = NOTE_BOLD if attributes.get("fontWeight") == "bold" else 0
        if attributes.get("underline") is True:
            mask |= NOTE_UNDERLINE
        if mask:
            spans.append((first, stop, mask))
    return text, tuple(spans)


def xml_note(element):
    if element is None:
        return "", ()
    pieces, spans, end = [], [], 0
    stack = [(element, 0)]
    while stack:
        node, mask = stack.pop()
        if isinstance(node, str):
            start, end = end, end + len(node)
            pieces.append(node)
            if mask:
                if spans and spans[-1][1:] == (start, mask):
                    spans[-1] = spans[-1][0], end, mask
                else:
                    spans.append((start, end, mask))
            continue
        next_mask = mask | _INLINE.get(node.tag.rsplit("}", 1)[-1], 0)
        for child in reversed(node):
            if child.tail:
                stack.append((child.tail, next_mask))
            stack.append((child, next_mask))
        if node.text:
            stack.append((node.text, next_mask))
    text = checked_text("".join(pieces))
    return text, tuple(spans) if len(spans) <= MAX_NOTE_STYLES else ()
