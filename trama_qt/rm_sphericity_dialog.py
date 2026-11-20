"""Repeated measures ANOVA in the Qt analysis dialog: the Sphericity correction choice.

The generic dialog draws the fields of ``analisi.workbench.METHODS``: Response, Factors, Subject and Sphericity
correction (None, Geisser–Greenhouse, Huynh-Feldt, Lower bound; a saved recipe that uses the one-way spelling keeps
it, named as a saved recipe). This binding adds what is specific to the method: a note under the choice that says
what it does and does not do, in the active language; the design check of the engine, which runs when the user presses
Run and before the worker starts, so that a design problem names the field to correct; and the English engine
sentences shown in the active language, led by the caption of that field. Recipes keep the canonical English keys
and values.
"""
from PySide6.QtWidgets import QLabel

from analisi import rm_sphericity
from analisi.field_error import FieldError
from analisi.i18n import tr

NOTES = {rm_sphericity.NONE: "rm.sphericity.note.none",
         rm_sphericity.CANONICAL: "rm.sphericity.note.gg",
         rm_sphericity.HF: "rm.sphericity.note.hf",
         rm_sphericity.LOWER: "rm.sphericity.note.lower",
         rm_sphericity.LEGACY: "rm.sphericity.note.legacy"}


class SphericityBinding:
    def __init__(self, dialog):
        self.dialog = dialog
        _caption, self.choice, form = dialog.rows[rm_sphericity.FIELD]
        legacy = self.choice.findData(rm_sphericity.LEGACY)
        if legacy >= 0:
            self.choice.setItemText(legacy, tr("rm.sphericity.choice.legacy"))
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        row, _role = form.getWidgetPosition(self.choice)
        form.insertRow(row + 1, self.note)
        self.choice.currentIndexChanged.connect(self.update)
        self.update()

    def update(self, *_):
        self.note.setText(tr(NOTES.get(self.choice.currentData(), NOTES[rm_sphericity.CANONICAL])))

    def check(self, options):
        """Raise the engine's ``FieldError`` for recipe and worksheet; nothing is fitted here.

        The corrections that need a complete design check it now. None keeps the engine's plain value errors.
        """
        token = rm_sphericity.correction(options, len(options.get(rm_sphericity.FACTORS, ())))
        if token in rm_sphericity.STRICT:
            rm_sphericity.check_design(self.dialog.data, options[rm_sphericity.RESPONSE],
                                       options[rm_sphericity.FACTORS], options[rm_sphericity.SUBJECT])

    @staticmethod
    def message(error, field=None):
        """An engine sentence of this method in the active language; any other message is returned unchanged.

        A dialog reopened after a failed calculation receives the sentence and its field apart.
        """
        if field and not hasattr(error, "field"):
            error = FieldError(field, str(error))
        return rm_sphericity.format_error(error) or str(error)


def attach(dialog):
    """The binding for Repeated measures ANOVA, or None for every other analysis."""
    if dialog.method != rm_sphericity.METHOD or rm_sphericity.FIELD not in dialog.rows:
        return None
    return SphericityBinding(dialog)
