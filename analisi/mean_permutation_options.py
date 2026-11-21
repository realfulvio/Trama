"""Preview and field messages for the mean difference permutation test."""

from .i18n import active_language, tr, translate_message, ui
from .mean_permutation import ERROR_PREFIX, EXACT, LABEL_KEYS, MODE, MONTE_CARLO, preview

NUMBERS = ("count", "work", "resamples", "units", "limit", "row")


def caption(field):
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def number(text):
    """A whole number written by the engine with English separators, shown in the active language."""
    return text.replace(",", ".") if active_language() == "it" else text


def translate_error(error):
    """An engine or dialog message in the active language; field names inside it become the dialog captions."""
    text = str(error)
    shown = translate_message(text, ERROR_PREFIX, {"field": caption, **dict.fromkeys(NUMBERS, number)})
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The dialog banner: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    named = message.lower()
    if field and field.lower() not in named and label.lower() not in named:
        message = f"{label}: {message}"
    return message


def preview_text(data, options):
    """The note under Method: Auto says which way it goes with these columns, Exact how many assignments."""
    mode = options.get(MODE)
    if mode == MONTE_CARLO:
        return tr("perm.preview.monte_carlo")
    planned = preview(data, options) if data is not None else None
    exact = planned is not None and planned["used"] == EXACT
    count = number(f"{planned['assignments']:,}") if exact else None
    if mode == EXACT:
        return tr("perm.preview.exact_count", count=count) if planned else tr("perm.preview.exact")
    if planned is None:
        return tr("perm.preview.auto")
    if planned["used"] == EXACT:
        return tr("perm.preview.auto_exact", count=count)
    return tr("perm.preview.auto_simulate")
