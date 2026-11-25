"""Stable worksheet row references for graph presentation and structural edits."""

from bisect import bisect_left
import re
from uuid import uuid4

import numpy as np

ROW_SPANS = "point_row_spans"
_ORIGIN = re.compile(r"(?:base|[a-f0-9]{32})")
_TOKEN = re.compile(r"(?:base|[a-f0-9]{32}):[1-9][0-9]{0,9}")


class RowSpans(tuple):
    """Immutable tuple of ``(origin, first, count)`` spans; skips O(N) deepcopy inside pandas attrs."""

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def valid_token(token):
    return isinstance(token, str) and _TOKEN.fullmatch(token) is not None


def current_spans(frame):
    """Use positional IDs until the first structural edit. IDs are stored as contiguous ranges."""
    if ROW_SPANS in frame.attrs:
        spans = frame.attrs[ROW_SPANS]
        if sum(count for _, _, count in spans) != len(frame):
            return None
        return spans if isinstance(spans, RowSpans) else RowSpans(spans)
    return RowSpans((("base", 1, len(frame)),)) if len(frame) else RowSpans()


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
    return RowSpans(result)


def _slice(spans, start, stop):
    offset = 0
    for origin, first, count in spans:
        left, right = max(0, start - offset), min(count, stop - offset)
        if left < right:
            yield origin, first + left, right - left
        offset += count
        if offset >= stop:
            break


def _coalesce(spans):
    merged = []
    for origin, first, count in spans:
        if merged and merged[-1][0] == origin and merged[-1][1] + merged[-1][2] == first:
            prev_origin, prev_first, prev_count = merged[-1]
            merged[-1] = (prev_origin, prev_first, prev_count + count)
        else:
            merged.append((origin, first, count))
    return RowSpans(merged)


def moved_row_bounds(start, stop, destination):
    """Return the new 0-based [start, stop) bounds after moving [start, stop) to destination."""
    count = stop - start
    if destination < start:
        return destination, destination + count
    if destination > stop:
        return destination - count, destination
    return start, stop


def move_row_index(row, start, stop, destination):
    """Remap a 0-based row index after moving [start, stop) to destination."""
    if start <= destination <= stop:
        return row
    count = stop - start
    if destination < start:
        if destination <= row < start:
            return row + count
        if start <= row < stop:
            return destination + (row - start)
        return row
    if stop <= row < destination:
        return row - count
    if start <= row < stop:
        return destination - count + (row - start)
    return row


def row_move_slices(length, start, stop, destination):
    """Source row intervals in their order after a validated block move."""
    if destination < start:
        return (0, destination), (start, stop), (destination, start), (stop, length)
    if destination > stop:
        return (0, start), (stop, destination), (start, stop), (destination, length)
    return ((0, length),)


def after_insertion(frame, position, count):
    spans = current_spans(frame)
    return _coalesce((*_slice(spans, 0, position), (uuid4().hex, 1, count), *_slice(spans, position, len(frame))))


def after_move(frame, start, stop, destination):
    """Update contiguous row-identity spans after moving rows [start, stop) to destination."""
    length = len(frame)
    if (type(start) is not int or type(stop) is not int or type(destination) is not int
            or not (0 <= start < stop <= length) or not (0 <= destination <= length)):
        raise ValueError("Invalid row move range.")
    spans = current_spans(frame)
    if start <= destination <= stop:
        return spans
    return _coalesce(span for first, last in row_move_slices(length, start, stop, destination)
                     for span in _slice(spans, first, last))


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
    return RowSpans(result)


def validate_permutation(order, length):
    """Validate that ``order`` is a permutation of ``0..length - 1`` and return it as an ``np.intp`` array."""
    if type(length) is not int or length < 0:
        raise ValueError("Invalid row count.")
    if isinstance(order, np.ndarray):
        if order.dtype == np.bool_ or not np.issubdtype(order.dtype, np.integer) or order.ndim != 1 or len(order) != length:
            raise ValueError("Invalid row permutation.")
        arr = order.astype(np.intp, copy=False)
    else:
        try:
            items = list(order)
        except TypeError as error:
            raise ValueError("Invalid row permutation.") from error
        if len(items) != length or any(isinstance(item, bool) or not isinstance(item, (int, np.integer)) for item in items):
            raise ValueError("Invalid row permutation.")
        arr = np.asarray(items, dtype=np.intp)
    if length > 0:
        if int(arr.min()) < 0 or int(arr.max()) >= length:
            raise ValueError("Invalid row permutation.")
        if not np.array_equal(np.bincount(arr, minlength=length), np.ones(length, dtype=np.intp)):
            raise ValueError("Invalid row permutation.")
    return arr


def after_permutation(frame, order):
    """Update contiguous row-identity spans after applying row permutation ``order`` to ``frame``."""
    length = len(frame)
    order_arr = validate_permutation(order, length)
    spans = current_spans(frame)
    if spans is None:
        raise ValueError("Invalid worksheet row identities.")
    if length == 0:
        return RowSpans()
    if np.array_equal(order_arr, np.arange(length, dtype=np.intp)):
        return spans
    origins = []
    origin_map = {}
    orig_ids = np.empty(length, dtype=np.intp)
    ordinals = np.empty(length, dtype=np.int64)
    offset = 0
    for origin, first, count in spans:
        oid = origin_map.get(origin)
        if oid is None:
            oid = len(origins)
            origin_map[origin] = oid
            origins.append(origin)
        orig_ids[offset:offset + count] = oid
        ordinals[offset:offset + count] = np.arange(first, first + count, dtype=np.int64)
        offset += count
    p_orig = orig_ids[order_arr]
    p_ord = ordinals[order_arr]
    breaks = np.flatnonzero((p_orig[1:] != p_orig[:-1]) | (p_ord[1:] != p_ord[:-1] + 1)) + 1
    starts = np.concatenate((np.array([0], dtype=np.intp), breaks))
    stops = np.concatenate((breaks, np.array([length], dtype=np.intp)))
    return RowSpans((origins[int(p_orig[s])], int(p_ord[s]), int(e - s)) for s, e in zip(starts, stops))


def token_at(spans, row):
    for origin, first, count in spans:
        if row <= count:
            return f"{origin}:{first + row - 1}"
        row -= count
    return None


def row_tokens(frame, positions):
    """Return worksheet row identities for zero-based positions, in the requested order."""
    positions = tuple(positions)
    if not positions:
        return []
    wanted = sorted(set(positions))
    result, offset = {}, 0
    for origin, first, count in current_spans(frame) or ():
        begin = bisect_left(wanted, offset)
        end = bisect_left(wanted, offset + count, lo=begin)
        for position in wanted[begin:end]:
            result[position] = f"{origin}:{first + position - offset}"
        offset += count
    return [result[position] for position in positions]


def rows_of(spans, tokens):
    """Return the zero-based current position of each identity, or None for a deleted row."""
    tokens = tuple(tokens)
    if not tokens:
        return []
    wanted = {}
    for token in set(tokens):
        origin, number = token.split(":")
        wanted.setdefault(origin, {})[int(number)] = token
    numbers_by_origin = {origin: sorted(numbers) for origin, numbers in wanted.items()}
    result, offset = {}, 0
    for origin, first, count in spans or ():
        numbers = numbers_by_origin.get(origin, ())
        begin = bisect_left(numbers, first)
        end = bisect_left(numbers, first + count, lo=begin)
        for number in numbers[begin:end]:
            result[wanted[origin][number]] = offset + number - first
        offset += count
    return [result.get(token) for token in tokens]


def row_of(spans, token):
    origin, value = token.split(":")
    ordinal = int(value)
    offset = 0
    for source, first, count in spans:
        if source == origin and first <= ordinal < first + count:
            return offset + ordinal - first + 1
        offset += count
    return None
