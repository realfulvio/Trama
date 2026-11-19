"""Validate binary logistic model in the Qt analysis dialog.

The generic dialog draws the fields of ``analisi.logistic_validation.OPTIONS``. This module adds the two things
that are specific to the method: the engine's checks (options, columns, fold codes, class counts, budgets and
the categorical coverage of every fold) run when the user presses Run, before the worker starts and before
anything is fitted; and the English engine messages are shown in the active language. Recipes keep the
canonical English keys and values.
"""
from analisi.i18n import translate_message
from analisi.logistic_validation import ERROR_PREFIX, METHOD, prepare

from .labels import field_label


def applies(dialog):
    return dialog.method == METHOD


def check(dialog, options):
    """Raise the engine's ``FieldError`` for the options and data of the dialog; nothing is fitted here."""
    if applies(dialog):
        prepare(dialog.data, options)


def message(error):
    """An engine message in the active language; other messages are returned unchanged."""
    return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label})
