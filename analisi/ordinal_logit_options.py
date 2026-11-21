"""Category order and field messages shared by the analysis dialogs."""

from .i18n import localized_count as number, tr, translate_message, ui
from .ordinal_logit import proposed_order

ERROR_PREFIX = "ord.error."


def caption(field):
    return ui(field)


def translate_error(error):
    """An engine message in the active language; worksheet names inside it are copied literally."""
    text = str(error)
    shown = translate_message(text, ERROR_PREFIX, {"limit": number, "count": number, "parameters": number,
                                                   "minimum": number})
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The dialog banner for an error: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    named = message.lower()
    if field and field.lower() not in named and label.lower() not in named:
        message = f"{label}: {message}"
    return message


def read_observed(data, response, predictors):
    """The categories of the response in the rows where the response and every predictor are filled."""
    if not response:
        return []
    return proposed_order(data, response, predictors)


def merged(order, observed):
    """The current arrangement restricted to the observed categories, each new one placed after its predecessor."""
    kept = [label for label in order if label in observed]
    for position, label in enumerate(observed):
        if label in kept:
            continue
        before = next((previous for previous in reversed(observed[:position]) if previous in kept), None)
        kept.insert(0 if before is None else kept.index(before) + 1, label)
    return kept


def shown(labels, limit=4):
    text = ", ".join(f'"{label}"' for label in labels[:limit])
    return text + (", …" if len(labels) > limit else "")


class OrderState:
    def __init__(self, saved):
        self.order = [str(label) for label in saved] if isinstance(saved, (list, tuple)) else []
        self.observed = None
        self.response = None

    def sync(self, observed, response):
        """Keep a stale saved order until the user explicitly resets it."""
        observed = list(observed)
        if self.observed is None:
            if not self.order:
                self.order = list(observed)
        elif response != self.response:
            self.order = list(observed)
        elif observed and set(self.order) == set(self.observed) and set(observed) != set(self.order):
            self.order = merged(self.order, observed)
        self.observed, self.response = observed, response

    def reset(self):
        self.order = list(self.observed or [])

    def move(self, index, step):
        target = index + step
        if not 0 <= index < len(self.order) or not 0 <= target < len(self.order):
            return None
        self.order[index], self.order[target] = self.order[target], self.order[index]
        return target

    def hint(self):
        """Return the localized guidance and whether the order differs from the worksheet."""
        if not self.observed:
            return tr("ord.hint.order" if self.order else "ord.hint.order_empty"), False
        added = [label for label in self.observed if label not in self.order]
        removed = [label for label in self.order if label not in self.observed]
        if added and removed:
            return tr("ord.hint.order_changed", added=shown(added), removed=shown(removed)), True
        if removed:
            return tr("ord.hint.order_removed", removed=shown(removed)), True
        if added:
            return tr("ord.hint.order_added", added=shown(added)), True
        return tr("ord.hint.order"), False
