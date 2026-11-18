"""Dialog rules for Deming regression: tabs, visible fields, field checks, recipe pruning and error text.

The Variables tab holds X, Y and the optional Y series; Uncertainty holds the input choice with the ratio or the
two SDs; Output holds the projections, the parameter intervals and the identity line. Fields that do not apply to
the chosen input are hidden, and a hidden field is left out of the recipe.
"""
from tkinter import ttk

import numpy as np

from . import ui_theme
from .deming import (INTERVAL_METHOD, KNOWN_SDS, LEVEL, PROJECTIONS, RATIO, UNCERTAINTY, VARIANCE_RATIO, X_SD, Y_SD,
                     Y_SERIES, read_settings)
from .field_error import FieldError
from .i18n import tr, translate_message, ui

METHOD = "Deming regression"
UNCERTAINTY_TAB = "Uncertainty"
TABS = {"Output": (PROJECTIONS, INTERVAL_METHOD, LEVEL, "Identity line")}
UNCERTAINTY_FIELDS = (UNCERTAINTY, RATIO, X_SD, Y_SD)
# Keys a recipe of 0.92 and earlier does not have; they are left out while they still hold their default.
DEFAULTS = ((UNCERTAINTY, VARIANCE_RATIO), (Y_SERIES, []), (PROJECTIONS, False))


def visibility(mode, interval_method):
    """The ratio belongs to Variance ratio, the SDs to Known SDs, and the level to Jackknife (t)."""
    known = mode == KNOWN_SDS
    return {RATIO: not known, X_SD: known, Y_SD: known, LEVEL: interval_method == "Jackknife (t)"}


def extended(options):
    """True when a recipe uses any 0.93 feature; everything else keeps the historical analysis."""
    return bool(options.get(UNCERTAINTY) == KNOWN_SDS or options.get(Y_SERIES) or options.get(PROJECTIONS))


def prune_options(options, saved):
    """Drop untouched 0.93 defaults so a recipe from an earlier version is saved exactly as it was."""
    saved = saved if isinstance(saved, dict) else {}
    for key, default in DEFAULTS:
        if key not in saved and options.get(key) == default:
            options.pop(key, None)
    return options


def check_options(options, data):
    """Field errors that stay in the dialog. The historical checks come first and keep their wording."""
    if options.get(UNCERTAINTY, VARIANCE_RATIO) == VARIANCE_RATIO:
        ratio = options[RATIO]
        if not np.isfinite(ratio) or ratio <= 0:
            raise FieldError(RATIO, f"{RATIO} must be finite and greater than 0.")
    if options.get(INTERVAL_METHOD) == "Jackknife (t)":
        level = options.get(LEVEL)
        if level is None or not np.isfinite(level) or not 0 < level < 100:
            raise FieldError(LEVEL, f"{LEVEL} must be finite and strictly between 0 and 100.")
    if extended(options):
        read_settings(data, options)


def format_error(error, field):
    """The error in the active language, naming the field once."""
    message = translate_message(str(error), "deming.error.", convert={"field": ui})
    label = ui(field) if field else ""
    # Series messages already name the series between quotes, so they never get a field prefix.
    if field and field != Y_SERIES and field not in message and label not in message:
        message = f"{label}: {message}"
    return message


def add_notes(variables_page, variables_row, uncertainty_page, uncertainty_row):
    """The two explanatory notes. Returns the SD note, which only applies to Known SDs."""
    series = ttk.Label(variables_page, text=tr("deming.note.series"), wraplength=ui_theme.px(420),
                       foreground="#486075", justify="left")
    series.grid(row=variables_row, column=0, columnspan=2, sticky="w", pady=(8, 0))
    sds = ttk.Label(uncertainty_page, text=tr("deming.note.sds"), wraplength=ui_theme.px(420),
                    foreground="#486075", justify="left")
    sds.grid(row=uncertainty_row, column=0, columnspan=2, sticky="w", pady=(8, 0))
    return sds
