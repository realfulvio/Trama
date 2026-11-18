"""Dialog parts of Meta-analysis of effect estimates: the unit note, the SE caption and error banners.

The recipe keeps the English field names and choices. On screen the Standard error caption follows the
measure: with Ratio it reads "SE of ln(ratio)" and a highlighted note explains that the ratios are entered
as they are while their standard errors belong to the natural logarithm.
"""
from tkinter import ttk

from . import ui_theme
from .i18n import tr, translate_message, ui
from .meta_analysis import (DIFFERENCE, ERROR_PREFIX, LABEL_KEYS, MEASURE, MODEL, MODEL_NOTE_KEY, NOTE_KEYS, RATIO,
                            RATIO_SE_KEY, SE, visibility)

HINT = "#486075"
UNIT = "#8a3b12"


def caption(field):
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def translate_error(error):
    """An engine message in the active language; field names inside it become the dialog captions."""
    text = str(error)
    shown = translate_message(text, ERROR_PREFIX, {"field": caption, "other": caption})
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


def fields(dialog):
    """Visibility of the random-effects controls for the current pooling model."""
    if MODEL not in dialog.controls:
        return {}
    return visibility(dialog.controls[MODEL][1].get())


def attach(dialog, studies, options, positions):
    """Add the unit note and the model note, and keep the SE caption and the visible fields in step."""
    measure = dialog.controls[MEASURE][1]
    heading = dialog.field_rows[SE][0]
    note = ttk.Label(studies, wraplength=ui_theme.px(420), foreground=UNIT, justify="left")
    note.grid(row=positions[studies], column=0, columnspan=2, sticky="w", pady=(8, 0))
    dialog.meta_unit_note = note

    def refresh_unit(*_):
        ratio = measure.get() == RATIO
        heading.configure(text=tr(RATIO_SE_KEY) if ratio else caption(SE))
        note.configure(text=tr(NOTE_KEYS[RATIO if ratio else DIFFERENCE]))

    measure.trace_add("write", refresh_unit)
    refresh_unit()
    ttk.Label(options, text=tr(MODEL_NOTE_KEY), wraplength=ui_theme.px(420), foreground=HINT,
              justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
    dialog.controls[MODEL][1].trace_add("write", lambda *_: dialog.show_fields(fields(dialog)))
    dialog.show_fields(fields(dialog))
