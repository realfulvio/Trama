"""Bland–Altman for repeated pairs in the Qt analysis dialog.

The generic dialog draws the fields of ``analisi.bland_altman_repeated.OPTIONS``. This binding adds what is specific
to the method: Confidence level, Bootstrap replicates and Seed are shown (and stored) only with the subject
bootstrap; the engine's checks of recipe and worksheet run when the user presses Run, before the worker starts; and
the English engine messages are shown in the active language. The recipe keeps the canonical English keys and values.
"""
from analisi.bland_altman_repeated import ERROR_PREFIX, INTERVALS, METHOD, check_options, visibility
from analisi.i18n import translate_message

from .labels import field_label


class RepeatedAgreementBinding:
    def __init__(self, dialog):
        self.dialog = dialog
        self.intervals = dialog.controls[INTERVALS][1]
        self.intervals.currentIndexChanged.connect(self.update)
        self.update()

    def update(self, *_):
        for name, visible in visibility(self.intervals.currentData()).items():
            row = self.dialog.rows.get(name)
            if row is None:
                continue
            _caption, widget, form = row
            form.setRowVisible(widget, visible)
            if visible:
                self.dialog.hidden.discard(name)
            else:
                self.dialog.hidden.add(name)

    def check(self, options):
        """Raise the engine's ``FieldError`` for recipe and worksheet; nothing is resampled here."""
        check_options(self.dialog.data, options)

    @staticmethod
    def message(error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label})


def attach(dialog):
    """The binding for Bland–Altman for repeated pairs, or None for every other analysis."""
    if dialog.method != METHOD or INTERVALS not in dialog.controls:
        return None
    return RepeatedAgreementBinding(dialog)
