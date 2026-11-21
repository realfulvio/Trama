"""Live design and method guidance for the Qt permutation dialog."""
from PySide6.QtWidgets import QLabel

from analisi import mean_permutation as engine
from analisi.i18n import tr
from analisi.mean_permutation_options import preview_text


def attach(dialog, pages):
    def note(page, text=""):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("muted")
        pages[page].addRow(label)
        return label

    design_note = note("variables")
    method_note = note("options")
    note("options", tr("perm.note.tails"))

    def widget(field):
        return dialog.controls[field][1]

    def refresh():
        values = {field: widget(field).currentData()
                  for field in (engine.FIRST, engine.SECOND, engine.DESIGN, engine.MODE)}
        for field, default in ((engine.RESAMPLES, engine.DEFAULT_RESAMPLES), (engine.SEED, 0)):
            try:
                values[field] = int(widget(field).text().strip())
            except ValueError:
                values[field] = default
        design_note.setText(tr(engine.DESIGN_NOTE_KEYS[values[engine.DESIGN]]))
        method_note.setText(preview_text(dialog.data, values))
        dialog._set_field_visibility(engine.visibility(values[engine.MODE]))
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)

    for field in (engine.FIRST, engine.SECOND, engine.DESIGN, engine.MODE):
        widget(field).currentIndexChanged.connect(refresh)
    for field in (engine.RESAMPLES, engine.SEED):
        widget(field).editingFinished.connect(refresh)
    refresh()
