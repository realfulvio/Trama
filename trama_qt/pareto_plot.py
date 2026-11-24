"""Pareto plot binding for the Classica Qt analysis dialog.

The generic dialog builds controls from ``analisi.pareto_plot.OPTIONS``. This binding preselects
a categorical column for ``Category`` on a fresh dialog, fills the default 80% threshold (while
allowing an empty field to disable the reference line), normalizes options into canonical EN form,
runs pre-flight checks, and translates engine messages into the active language.
"""
import pandas as pd
from PySide6.QtWidgets import QLabel

from analisi.i18n import tr, translate_message
from analisi.pareto_plot import (
    CATEGORY,
    DEFAULT_THRESHOLD,
    ERROR_PREFIX,
    METHOD,
    THRESHOLD,
    WEIGHT,
    check_options,
    normalize_options,
)

from .labels import field_label


def _format_threshold(value):
    if value in ("", None):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g}"
    return str(value)


class ParetoPlotBinding:
    """Manage defaults, canonical option normalization, pre-flight checks, and EN/IT error wording."""

    def __init__(self, dialog, saved):
        self.dialog = dialog
        self.category_box = dialog.controls[CATEGORY][1]
        self.weight_box = dialog.controls[WEIGHT][1]
        self.threshold_edit = dialog.controls[THRESHOLD][1]

        if not saved:
            self._choose_default_category()
            self.threshold_edit.setText(_format_threshold(DEFAULT_THRESHOLD))
        elif THRESHOLD in saved:
            self.threshold_edit.setText(_format_threshold(saved[THRESHOLD]))
        else:
            self.threshold_edit.setText(_format_threshold(DEFAULT_THRESHOLD))

        note = QLabel(tr("pareto.help.text"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        _, _, options_form = dialog.rows[THRESHOLD]
        options_form.addRow(QLabel(tr("pareto.help.caption")), note)

        for field_name, signal in (
            (CATEGORY, self.category_box.currentIndexChanged),
            (WEIGHT, self.weight_box.currentIndexChanged),
            (THRESHOLD, self.threshold_edit.textEdited),
        ):
            signal.connect(lambda _v=None, name=field_name: dialog.clear_field_error(name))

    def _choose_default_category(self):
        frame = self.dialog.data
        for col in frame.columns:
            if not pd.api.types.is_numeric_dtype(frame[col]):
                idx = self.category_box.findData(str(col))
                if idx >= 0:
                    self.category_box.setCurrentIndex(idx)
                return

    def canonical(self, options):
        return normalize_options(options)

    def check(self, options):
        check_options(self.dialog.data, options)

    def message(self, error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label})


def attach(dialog, saved):
    """Attach the Pareto binding when ``dialog.method`` is ``Pareto plot``."""
    return ParetoPlotBinding(dialog, saved) if dialog.method == METHOD else None
