"""Dialog parts of Restricted mean survival time: typed numbers, field captions and the error messages.

The dialog keeps what the user typed when it is not a number, so the analysis reports the value on the field that
needs fixing instead of the dialog rewriting it. Messages are the English text of the engine; ``translate_error``
shows them in the active language, with the decimal comma for numbers in Italian.
"""
import re

from .data import decimal_comma
from .i18n import DEFAULT_LANGUAGE, active_language, tr, translate_message, ui
from .rmst import show_number
from .rmst_workbench import ERROR_PREFIX, HINT_KEYS, LABEL_KEYS

GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")
DECIMAL = re.compile(r"[+-]?\d+\.\d+(?:e[+-]?\d+)?")


def caption(field):
    """The dialog caption of a canonical field name (the name itself for an unknown field)."""
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def amount(text):
    """A number of a message in the separators of the active language: 50,000 → 50.000 and 6.5 → 6,5 in Italian."""
    if active_language() == DEFAULT_LANGUAGE:
        return text
    if GROUPED.fullmatch(text):
        return text.replace(",", ".")
    if DECIMAL.fullmatch(text):
        return text.replace(".", ",")
    return text


def shown_number(value):
    """A saved number as the dialog shows it, with the decimal comma in Italian."""
    return amount(show_number(value))


def read_number(text):
    """A typed number, accepting the decimal comma; empty or unparsable text is kept for the engine to report."""
    text = str(text).strip()
    if not text:
        return ""
    try:
        return float(decimal_comma(text))
    except ValueError:
        return text


def translate_error(error):
    """An engine message in the active language; field names become captions, worksheet values stay literal."""
    text = str(error)
    converters = {"field": caption, "role": caption, "first": caption, "limit": amount, "count": amount,
                  "value": amount}
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


def limit_hint(limit):
    """The line under Horizon: the largest usable horizon, or nothing while the data fields are incomplete."""
    return "" if limit is None else tr(HINT_KEYS["limit"], limit=shown_number(limit))
