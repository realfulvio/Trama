"""Stable worksheet row references for graph presentation and structural edits."""

import re
from uuid import uuid4

ROW_SPANS = "point_row_spans"
_ORIGIN = re.compile(r"(?:base|[a-f0-9]{32})")
_TOKEN = re.compile(r"(?:base|[a-f0-9]{32}):[1-9][0-9]{0,9}")


def valid_token(token):
    return isinstance(token, str) and _TOKEN.fullmatch(token) is not None


def current_spans(frame):
    """Use positional IDs until the first structural edit. IDs are stored as contiguous ranges."""
    if ROW_SPANS in frame.attrs:
        spans = frame.attrs[ROW_SPANS]
        return spans if sum(count for _, _, count in spans) == len(frame) else None
    return (("base", 1, len(frame)),) if len(frame) else ()


def saved_spans(spans, length):
    """Validate persisted ranges and reject overlapping identities."""
    problem = "Invalid worksheet row identities."
    if not isinstance(spans, (list, tuple)) or len(spans) > length:
        raise ValueError(problem)
    by_origin = {}
    total = 0
    result = []
    for span in spans:
        if not isinstance(span, (list, tuple)) or len(span) != 3:
            raise ValueError(problem)
        origin, first, count = span
        if (not isinstance(origin, str) or not _ORIGIN.fullmatch(origin)
                or type(first) is not int or type(count) is not int or first < 1 or count < 1
                or first + count > 10 ** 10):
            raise ValueError(problem)
        by_origin.setdefault(origin, []).append((first, first + count))
        total += count
        result.append((origin, first, count))
    if total != length:
        raise ValueError(problem)
    for ranges in by_origin.values():
        ranges.sort()
        if any(end > start for (_, end), (start, _) in zip(ranges, ranges[1:])):
            raise ValueError(problem)
    return tuple(result)


def _slice(spans, start, stop):
    offset = 0
    for origin, first, count in spans:
        left, right = max(0, start - offset), min(count, stop - offset)
        if left < right:
            yield origin, first + left, right - left
        offset += count
        if offset >= stop:
            break


def after_insertion(frame, position, count):
    spans = current_spans(frame)
    return (*_slice(spans, 0, position), (uuid4().hex, 1, count), *_slice(spans, position, len(frame)))


def after_deletion(frame, removed):
    spans = current_spans(frame)
    removed = iter(row for row in removed if 0 <= row < len(frame))
    cut = next(removed, len(frame))
    offset, result = 0, []
    for origin, first, count in spans:
        end = offset + count
        start = offset
        while cut < end:
            if start < cut:
                result.append((origin, first + start - offset, cut - start))
            start = cut + 1
            cut = next(removed, len(frame))
        if start < end:
            result.append((origin, first + start - offset, end - start))
        offset = end
    return tuple(result)


def token_at(spans, row):
    for origin, first, count in spans:
        if row <= count:
            return f"{origin}:{first + row - 1}"
        row -= count
    return None


def row_of(spans, token):
    origin, value = token.split(":")
    ordinal = int(value)
    offset = 0
    for source, first, count in spans:
        if source == origin and first <= ordinal < first + count:
            return offset + ordinal - first + 1
        offset += count
    return None
