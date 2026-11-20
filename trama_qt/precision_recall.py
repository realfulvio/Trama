"""Precision–recall curve in the Qt analysis dialog.

The generic dialog draws the fields of ``analisi.precision_recall.OPTIONS``. This binding adds what is specific to
the method: the second direction is shown only with a second score, and the level, replicates and seed only with
Bootstrap CI (hidden fields are neither validated nor stored); a line under the variables tells, while the user
chooses, how many samples the curves will share and their prevalence, or why they cannot be counted yet; the
engine's checks of recipe and worksheet run when the user presses Run, before the worker starts, and name the field
to fix; and the English engine messages are shown in the active language. The recipe keeps the canonical English
keys and values.
"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit

from analisi.field_error import FieldError
from analisi.i18n import active_language, translate_message
from analisi.precision_recall import (BOOTSTRAP, CODE_FIELDS, ERROR_PREFIX, METHOD, NEGATIVE, OUTCOME, POSITIVE, SCORE,
                                      SECOND_SCORE, check_options, visibility)

from .labels import field_label

PREVIEW_ROWS = 200_000      # a longer worksheet is counted when the user presses Run, not at every keystroke
DEBOUNCE_MS = 250
WATCHED = (OUTCOME, POSITIVE, NEGATIVE, SCORE, SECOND_SCORE)
_TEXT = {
    "samples": ("Common samples: {n} · Positives: {positives} · Negatives: {negatives} · Prevalence: {prevalence}",
                "Campioni comuni: {n} · Positivi: {positives} · Negativi: {negatives} · Prevalenza: {prevalence}"),
    "left_out": ("{count} row(s) left out for blank cells.", "{count} riga/righe escluse per celle vuote."),
    "later": ("The sample count appears when you press Run.", "Il conteggio dei campioni compare dopo Esegui."),
}


def _text(key, **values):
    english, italian = _TEXT[key]
    return (italian if active_language() == "it" else english).format(**values)


def _number(value):
    shown = f"{value:.4g}"
    return shown.replace(".", ",") if active_language() == "it" else shown


class PrecisionRecallBinding:
    def __init__(self, dialog):
        self.dialog = dialog
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        _caption, widget, form = dialog.rows[OUTCOME]
        form.addRow(self.info)
        self.timer = QTimer(dialog)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DEBOUNCE_MS)
        self.timer.timeout.connect(self.summarize)
        for name in WATCHED:
            control = dialog.controls[name][1]
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self.changed)
            elif isinstance(control, QLineEdit):
                control.textChanged.connect(self.changed)
        self.second = dialog.controls[SECOND_SCORE][1]
        self.bootstrap = dialog.controls[BOOTSTRAP][1]
        self.second.currentIndexChanged.connect(self.update)
        if isinstance(self.bootstrap, QCheckBox):
            self.bootstrap.toggled.connect(self.update)
        self.update()
        self.summarize()

    def update(self, *_):
        for name, visible in visibility(self.second.currentData(), self.bootstrap.isChecked()).items():
            row = self.dialog.rows.get(name)
            if row is None:
                continue
            _caption, widget, form = row
            form.setRowVisible(widget, visible)
            if visible:
                self.dialog.hidden.discard(name)
            else:
                self.dialog.hidden.add(name)

    def changed(self, *_):
        self.timer.start()

    def summarize(self):
        """The shared sample count and the prevalence, or the reason there is none yet (never an error banner)."""
        if len(self.dialog.data) > PREVIEW_ROWS:
            self.info.setText(_text("later"))
            return
        try:
            options = {**self.dialog.options(), BOOTSTRAP: False}
            plan = check_options(self.dialog.data, options)
        except FieldError as error:
            self.info.setText(self.message(error))
            return
        except (ValueError, OverflowError) as error:
            self.info.setText(str(error))
            return
        text = _text("samples", n=f"{plan.n:,}", positives=f"{plan.positives:,}", negatives=f"{plan.negatives:,}",
                     prevalence=_number(plan.prevalence))
        if plan.excluded:
            text += "\n" + _text("left_out", count=len(plan.excluded))
        self.info.setText(text)

    def check(self, options):
        """Raise the engine's ``FieldError`` for recipe and worksheet; nothing is resampled here."""
        check_options(self.dialog.data, options)

    @staticmethod
    def message(error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label, "other": field_label})


def attach(dialog):
    """The binding for Precision–recall curve, or None for every other analysis."""
    if dialog.method != METHOD or OUTCOME not in dialog.controls or SECOND_SCORE not in dialog.controls:
        return None
    return PrecisionRecallBinding(dialog)


__all__ = ["CODE_FIELDS", "PrecisionRecallBinding", "attach"]
