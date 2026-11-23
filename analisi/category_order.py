"""Worksheet category order for graphs, keyed by type-preserving level identities."""

from collections import Counter

from .graph_legend import MAX_LEGEND_KEY_LENGTH, typed_group_token
from .i18n import tr


WORKSHEET_ORDERS = "category_orders"
CATEGORY_ORDER_VERSION = 5
MAX_LEVELS = 256


def validated_orders(orders, columns):
    if not isinstance(orders, dict):
        raise ValueError("Invalid saved category orders.")
    available = set(columns)
    for name, tokens in orders.items():
        if (name not in available or not isinstance(tokens, list) or not 1 <= len(tokens) <= MAX_LEVELS
                or not all(isinstance(token, str) and 1 <= len(token) <= MAX_LEGEND_KEY_LENGTH for token in tokens)
                or len(set(tokens)) != len(tokens)):
            raise ValueError("Invalid saved category order for a worksheet column.")
    return orders


def ranks(frame, column):
    order = frame.attrs.get(WORKSHEET_ORDERS, {}).get(column, ())
    return {token: index for index, token in enumerate(order)}


def preferred_levels(values, priority):
    """Keep the order of the input levels for values absent from the worksheet preference."""
    return sorted(values, key=lambda value: priority.get(typed_group_token(value), len(priority))) if priority else values


def _column_levels(frame, name):
    """Current nonblank levels in display order, with stable identities for edits."""
    labels = {}
    column = frame[name]
    for value in column.dropna().to_numpy(dtype=object):
        token = typed_group_token(value)
        if len(token) > MAX_LEGEND_KEY_LENGTH:
            raise ValueError(tr("worksheet_order.limit", limit=MAX_LEVELS))
        labels.setdefault(token, str(value))
        if len(labels) > MAX_LEVELS:
            raise ValueError(tr("worksheet_order.limit", limit=MAX_LEVELS))
    counts = Counter(labels.values())
    return [(token, repr(label) if counts[label] > 1 and token.startswith("str:") else label)
            for token, label in labels.items()]


def set_order(dataset, name, tokens):
    """Replace the worksheet metadata as one undoable edit. An empty order restores automatic ordering."""
    orders = dict(dataset.raw.attrs.get(WORKSHEET_ORDERS, {}))
    if tokens:
        orders[name] = list(tokens)
        validated_orders(orders, dataset.raw.columns)
    else:
        orders.pop(name, None)
    if orders == dataset.raw.attrs.get(WORKSHEET_ORDERS, {}):
        return
    raw = dataset.raw.copy(deep=False)
    if orders:
        raw.attrs[WORKSHEET_ORDERS] = orders
    else:
        raw.attrs.pop(WORKSHEET_ORDERS, None)
    dataset.raw = raw


def keep_source_columns(frame, rename=None):
    """Carry preferences only for source columns that survived an edit."""
    stored = frame.attrs.get(WORKSHEET_ORDERS)
    if not stored:
        return
    rename = rename or {}
    kept = {rename.get(name, name): order for name, order in stored.items()
            if rename.get(name, name) in frame.columns}
    if kept:
        frame.attrs[WORKSHEET_ORDERS] = kept
    else:
        frame.attrs.pop(WORKSHEET_ORDERS, None)


class OrderDraft:
    """The confirmations used by both desktop editors. The worksheet stays untouched until Apply."""

    def __init__(self, dataset, name):
        self.automatic = _column_levels(dataset.raw, name)
        self.saved = dataset.raw.attrs.get(WORKSHEET_ORDERS, {}).get(name, [])
        priority = ranks(dataset.raw, name)
        self.initial = sorted(self.automatic, key=lambda entry: priority.get(entry[0], len(priority)))
        self.levels = list(self.initial)
        self.reset = False

    def move(self, row, step):
        target = row + step
        if not (0 <= row < len(self.levels) and 0 <= target < len(self.levels)):
            return row
        self.levels[row], self.levels[target] = self.levels[target], self.levels[row]
        self.reset = False
        return target

    def restore_automatic(self):
        self.levels = list(self.automatic)
        self.reset = True

    def result(self):
        if self.reset:
            return [] if self.saved else None
        if self.levels == self.initial:
            return None
        return [token for token, _ in self.levels]
