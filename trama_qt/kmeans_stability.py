"""K-means stability in the Qt analysis dialog.

The generic dialog draws the fields of ``analisi.kmeans_stability.OPTIONS``. This binding adds what is specific to
the method: the Hartigan–Wong iteration limit is shown (and stored) only with that algorithm, the engine's cheap
checks and budgets run when the user presses Run, before any worker or process starts, and the English engine
messages are shown in the active language. The recipe keeps the canonical English keys and values.
"""
from analisi.i18n import translate_message
from analisi.kmeans_stability import ALGORITHM, ERROR_PREFIX, METHOD, prepare, visibility

from .labels import field_label


class StabilityBinding:
    def __init__(self, dialog):
        self.dialog = dialog
        self.algorithm = dialog.controls[ALGORITHM][1]
        self.algorithm.currentIndexChanged.connect(self.update)
        self.update()

    def update(self, *_):
        choice = self.algorithm.currentData()
        for name, visible in visibility(choice).items():
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
        """Raise the engine's ``FieldError`` for options, data or budgets; nothing is fitted here."""
        prepare(self.dialog.data, options)

    @staticmethod
    def message(error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label})


def attach(dialog):
    """The binding for K-means stability, or None for every other analysis."""
    if dialog.method != METHOD or ALGORITHM not in dialog.controls:
        return None
    return StabilityBinding(dialog)
