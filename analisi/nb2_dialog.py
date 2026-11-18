"""Dialog captions, choices and messages of Negative binomial regression.

The recipe keeps the English keys and values of ``nb2_regression``; only what is shown on screen is translated.
"""
from .i18n import DEFAULT_LANGUAGE, active_language, tr, translate_message, ui
from .nb2_regression import (ALPHA, CATEGORIES, ESTIMATED, EXPOSURE, FIXED, LEVEL, MODE, PLOT, PREDICTORS,
                             RESPONSE)

LABEL_KEYS = {RESPONSE: "nb2.field.response", PREDICTORS: "nb2.field.predictors",
              CATEGORIES: "nb2.field.categories", EXPOSURE: "nb2.field.exposure", MODE: "nb2.field.mode",
              ALPHA: "nb2.field.alpha", LEVEL: "nb2.field.level", PLOT: "nb2.field.plot"}
CHOICE_KEYS = {ESTIMATED: "nb2.choice.estimated", FIXED: "nb2.choice.fixed"}
HINT_KEY = "nb2.hint"
ERROR_PREFIX = "nb2.error."
REASONS = ("not finite", "not positive definite", "nearly singular")


def caption(field):
    """The on-screen caption of a canonical field name."""
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else ui(field)


def _rows(text):
    """A row count written with English thousands separators (20,000) in the separators of the active language."""
    return text.replace(",", ".") if active_language() != DEFAULT_LANGUAGE else text


def _reason(text):
    return tr("nb2.reason." + text) if text in REASONS else text


def translate_error(error):
    """An engine or dialog message in the active language; field names inside it become the dialog captions."""
    text = str(error)
    shown = translate_message(text, ERROR_PREFIX, {"field": caption, "rows": _rows, "reason": _reason})
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The banner text for an error: translated and naming the field it belongs to."""
    field = getattr(error, "field", None) or field
    message = translate_error(error)
    if field:
        label = caption(field)
        named = message.lower()
        if field.lower() not in named and label.lower() not in named:
            message = f"{label}: {message}"
    return message
