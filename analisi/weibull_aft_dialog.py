"""Dialog parts of Weibull AFT regression: the line editor of the requested times and the error messages.

The editor keeps what the user typed: a time is a number when it parses and the raw text otherwise, so the
analysis reports the value that needs fixing on the right field instead of the dialog rewriting it. Messages are
the English text of the engine; ``translate_error`` shows them in the active language.
"""
from .competing_risks_dialog import TimeListEditor, number
from .i18n import tr, translate_message, ui
from .weibull_aft_workbench import ERROR_PREFIX, HINT_KEYS, LABEL_KEYS


def caption(field):
    """The dialog caption of a canonical field name (the name itself for an unknown field)."""
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def translate_error(error):
    """An engine message in the active language; the field names inside it become the dialog captions.

    Worksheet values (column names, codes, levels) are copied literally. A message that is not one of the catalog
    entries (a shared helper's) goes through the common interface catalog.
    """
    text = str(error)
    converters = {"field": caption, "role": caption, "first": caption, "graph": caption, "limit": number,
                  "count": number}
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


class TimesEditor(TimeListEditor):
    """Optional times at which the survival of the profiles is reported; blank lines are ignored."""

    hint_key = HINT_KEYS["times"]
    rows = 4
