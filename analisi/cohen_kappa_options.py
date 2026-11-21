"""Cohen kappa analysis-dialog options and messages shared by Classic and Qt."""

from .cohen_kappa import FIRST, SECOND, UNWEIGHTED, observed_categories
from .cohen_kappa_workbench import CHOICE_KEYS, ERROR_PREFIX, LABEL_KEYS, PREFIX
from .data import decimal_comma
from .field_error import FieldError
from .i18n import localized_count as number, tr, translate_message, ui


def caption(field):
    """The dialog caption of a canonical field name (the name itself for an unknown field)."""
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def choice(value):
    return tr(CHOICE_KEYS[value]) if value in CHOICE_KEYS else value


def translate_error(error):
    """An engine message in the active language; field names and choices inside it become the dialog captions.

    Worksheet values (column names, categories, cell values) are copied literally. A message that is not one of
    the catalog entries (a shared helper's) goes through the common interface catalog.
    """
    text = str(error)
    converters = {"field": caption, "first": caption, "weighting": choice, "limit": number, "count": number,
                  "high": number}
    shown = translate_message(text, ERROR_PREFIX, converters)
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


def read_typed(text):
    """A bootstrap field as typed: an integer, else a number (decimal comma accepted), else the text itself.

    The analysis reads these fields only with the bootstrap on, so a value that does not parse is kept in the
    recipe as written and reported on its own field when it is used.
    """
    raw = str(text).strip()
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(decimal_comma(raw))
    except ValueError:
        return raw


def defaults(frame):
    """First and second rating of a new analysis: the first two columns of the worksheet."""
    columns = [str(name) for name in frame.columns]
    return {FIRST: columns[0], SECOND: columns[1]} if len(columns) >= 2 else {}


def _listed(labels, limit=6):
    shown = ", ".join(labels[:limit])
    return shown + (" …" if len(labels) > limit else "")


def propose_order(items, observed):
    kept = [name for name in items if name in observed]
    return kept + [name for name in observed if name not in kept]


def order_notes(items, observed, weighting, problem):
    """Describe the differences with the complete pairs and required explicit order."""
    lines = []
    if problem:
        lines.append(problem)
    if observed is not None and items:
        fresh = [name for name in observed if name not in items]
        stale = [name for name in items if name not in observed]
        if fresh:
            lines.append(tr(PREFIX + "order.new", levels=_listed(fresh)))
        if stale:
            lines.append(tr(PREFIX + "order.stale", levels=_listed(stale)))
    if not items and weighting != UNWEIGHTED:
        lines.append(tr(PREFIX + "order.needed"))
    return lines


def preview(frame, first, second):
    """Categories of the complete pairs for the editor: (labels, "") or (None, the translated reason)."""
    try:
        return observed_categories(frame, first, second), ""
    except (FieldError, ValueError, KeyError, TypeError) as error:
        return None, describe_error(error)
