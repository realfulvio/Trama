"""Compact letter display (CLD) for pairwise comparisons on graphs.

Groups that share a symbol were not found different by the chosen test (P > alpha); a pair with
P ≤ alpha shares no symbol. The symbols are the maximal cliques of the non-significance graph,
built with the insert–absorb algorithm of Piepho (2004), ordered by the X positions of their
members and named a…z, aa, ab… (or A…Z, AA…, or 1, 2, 3…).

Nothing here touches a figure or Tk: :func:`plan_letters` only proposes positions in data units.
"""
from math import isfinite, log10

import numpy as np

MIN_GROUPS, MAX_GROUPS = 2, 30
MAX_WORKING_SETS = 4096
MAX_SYMBOLS = 64
DEFAULT_ALPHA = .05
IDENTIFIERS = ("lower", "upper", "numbers")
PLACEMENTS = ("individual", "aligned")
GAP = .04
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


# ---------------------------------------------------------------------------
# Symbols


def symbol(position, identifiers="lower"):
    """The symbol of the clique at ``position`` (0-based): a…z, aa, ab…; A…Z, AA…; or 1, 2, 3…"""
    value = position + 1
    if identifiers == "numbers":
        return str(value)
    text = ""
    while value:
        value, digit = divmod(value - 1, 26)
        text = ALPHABET[digit] + text
    return text.upper() if identifiers == "upper" else text


def _probability(value):
    """A finite P value in [0, 1] as float, or None (booleans, text and NaN are not P values)."""
    if value is None or isinstance(value, (bool, np.bool_, str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) and 0 <= number <= 1 else None


def _alpha(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError("Alpha must be a number greater than 0 and less than 1.")
    value = float(value)
    if not (isfinite(value) and 0 < value < 1):
        raise ValueError("Alpha must be a number greater than 0 and less than 1.")
    return value


# ---------------------------------------------------------------------------
# Letters


def pair_matrix(groups, comparisons):
    """``{frozenset(pair): p}`` for the requested groups. Raises ValueError when a pair is missing or conflicting."""
    try:
        members = set(groups)
    except TypeError:
        raise ValueError("Group keys must be hashable values.") from None
    found = {}
    for row in comparisons or ():
        if not isinstance(row, dict):
            continue
        left, right = row.get("left"), row.get("right")
        try:
            if left not in members or right not in members or left == right:
                continue
        except TypeError:
            continue
        p = _probability(row.get("p"))
        if p is None:
            continue
        pair = frozenset((left, right))
        if pair in found and found[pair] != p:
            raise ValueError(f"The source gives two different P values for {left} and {right}.")
        found[pair] = p
    expected = len(groups) * (len(groups) - 1) // 2
    if len(found) != expected:
        missing = next((a, b) for i, a in enumerate(groups) for b in groups[i + 1:] if frozenset((a, b)) not in found)
        raise ValueError(f"Compact letters need a valid P value for every pair of the shown groups; "
                         f"{expected - len(found)} of {expected} are missing (for example {missing[0]} vs "
                         f"{missing[1]}). The source must provide all the comparisons required.")
    return found


def _insert_absorb(count, significant):
    """Maximal cliques of the non-significance graph as bit masks (insert–absorb)."""
    sets = [(1 << count) - 1]
    for i, j in significant:
        both = (1 << i) | (1 << j)
        kept, split = [], []
        for mask in sets:
            if mask & both == both:
                split.extend((mask & ~(1 << i), mask & ~(1 << j)))
            else:
                kept.append(mask)
        if not split:
            continue
        if len(kept) + len(split) > MAX_WORKING_SETS:
            raise ValueError(f"The comparisons need more than {MAX_WORKING_SETS} working sets of groups; "
                             "compact letters cannot be assigned. Use brackets or show fewer groups.")
        # Absorb: the kept sets are already an antichain and no kept set lies inside a split one
        # (it would lie inside the set it was split from), so only the new sets need checking.
        fresh = []
        for mask in sorted(set(split), key=lambda value: -value.bit_count()):
            if any(mask & other == mask for other in kept) or any(mask & other == mask for other in fresh):
                continue
            fresh.append(mask)
        sets = kept + fresh
    return sets


def compact_letters(groups, comparisons, *, alpha=DEFAULT_ALPHA, identifiers="lower"):
    """Map each group key (in X order) to its list of symbols.

    ``comparisons`` holds ``{"left", "right", "p"}`` records as produced by
    :func:`analisi.pairwise_graph.comparison_rows`. Pairs outside ``groups`` and invalid P values are
    ignored; a reversed duplicate with the same P value is accepted. Raises ValueError for invalid input,
    a missing or conflicting pair, or a result over the working-set or symbol limits.
    """
    if isinstance(groups, (str, bytes, dict)) or not hasattr(groups, "__iter__"):
        raise ValueError("Groups must be a sequence of keys in X order.")
    groups = list(groups)
    if not MIN_GROUPS <= len(groups) <= MAX_GROUPS:
        raise ValueError(f"Compact letters need between {MIN_GROUPS} and {MAX_GROUPS} groups; {len(groups)} are shown.")
    try:
        distinct = len(set(groups)) == len(groups)
    except TypeError:
        raise ValueError("Group keys must be hashable values.") from None
    if not distinct:
        raise ValueError("Each group key must appear only once.")
    alpha = _alpha(alpha)
    if identifiers not in IDENTIFIERS:
        raise ValueError(f"Identifiers must be one of {', '.join(IDENTIFIERS)}.")
    matrix = pair_matrix(groups, comparisons)
    significant = [(i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))
                   if matrix[frozenset((groups[i], groups[j]))] <= alpha]
    cliques = _insert_absorb(len(groups), significant)
    if len(cliques) > MAX_SYMBOLS:
        raise ValueError(f"The comparisons need {len(cliques)} letters, more than the limit of {MAX_SYMBOLS}. "
                         "Use brackets or show fewer groups.")
    ordered = sorted(tuple(i for i in range(len(groups)) if mask >> i & 1) for mask in cliques)
    result = {key: [] for key in groups}
    for position, members in enumerate(ordered):
        name = symbol(position, identifiers)
        for index in members:
            result[groups[index]].append(name)
    # The display must agree with every comparison: no shared symbol exactly for significant pairs.
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            shared = bool(set(result[groups[i]]) & set(result[groups[j]]))
            if shared == (matrix[frozenset((groups[i], groups[j]))] <= alpha):
                raise ValueError("Internal error: the compact letters do not match the comparisons.")
    return result


# ---------------------------------------------------------------------------
# Placement


def _finite(value):
    if isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def plan_letters(anchors, assignments, y_limits, *, yscale="linear", fixed_y=False, placement="individual"):
    """Place one text per group above its highest value. Returns ``(labels, top, warning)``.

    ``labels`` holds ``{"key", "text", "x", "y"}`` sorted by X and key; ``top`` is the proposed upper
    Y limit in data units (unchanged with ``fixed_y``); ``warning`` is a message or None.
    """
    low, high = y_limits
    if not assignments:
        return [], high, None
    if yscale not in ("linear", "log"):
        return [], high, "Compact letters need a linear or logarithmic Y axis."
    if not (_finite(low) is not None and _finite(high) is not None and low < high):
        return [], high, "Compact letters are not drawn on an inverted or empty Y axis."
    log = yscale == "log"
    if log and low <= 0:
        return [], high, "The logarithmic Y axis has no room for compact letters."
    if placement not in PLACEMENTS:
        raise ValueError(f"Placement must be one of {', '.join(PLACEMENTS)}.")
    forward = log10 if log else float
    inverse = (lambda value: 10 ** value) if log else float
    gap = (forward(high) - forward(low)) * GAP
    valid = {}
    for key in assignments:
        anchor = anchors.get(key) if isinstance(anchors, dict) else None
        if not isinstance(anchor, dict):
            continue
        x, top = _finite(anchor.get("x")), _finite(anchor.get("top"))
        if x is None or top is None or (log and top <= 0):
            continue
        valid[key] = anchor["x"], forward(top)
    omitted = len(valid) < len(assignments)
    if placement == "aligned" and valid:
        highest = max(top for _, top in valid.values())
        valid = {key: (x, highest) for key, (x, _) in valid.items()}
    labels, top, clipped = [], high, False
    for key, (x, height) in sorted(valid.items(), key=lambda item: (item[1][0], item[0])):
        y = height + gap
        try:
            position, ceiling = inverse(y), inverse(y + gap)
        except OverflowError:
            omitted = True
            continue
        if not (isfinite(position) and isfinite(ceiling)):
            omitted = True
            continue
        if fixed_y and ceiling > high:
            clipped = True
            continue
        labels.append({"key": key, "text": " ".join(assignments[key]), "x": x, "y": position})
        if not fixed_y:
            top = max(top, ceiling)
    warning = None
    if clipped:
        warning = "Some compact letters do not fit below the fixed Y maximum and are not drawn."
    elif omitted:
        warning = "Some groups have no value that can be shown on this axis; their letters are not drawn."
    return labels, top, warning
