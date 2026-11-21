"""Native controls for Weibull AFT survival profiles and requested times."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPlainTextEdit

from analisi import weibull_aft as engine
from analisi.i18n import tr, translate_message, ui
from analisi.weibull_aft_workbench import ERROR_PREFIX, HINT_KEYS, LABEL_KEYS, visibility

from .predictor_profiles import Profiles, typed_number


class Times(QPlainTextEdit):
    def __init__(self, saved):
        rows = saved if isinstance(saved, (list, tuple)) else []
        super().__init__("\n".join(str(value) for value in rows))
        self.setTabChangesFocus(True)
        self.setFixedHeight(5 * self.fontMetrics().lineSpacing())

    def values(self):
        return [typed_number(line) for line in self.toPlainText().splitlines() if line.strip()]


def attach(dialog, pages):
    """Refresh the profile columns when a role changes and show Shape in Fixed mode."""
    predictors = dialog.controls[engine.PREDICTORS][1]
    categories = dialog.controls[engine.CATEGORICAL][1]
    profiles = dialog.controls[engine.PROFILES][1]
    shape_mode = dialog.controls[engine.SHAPE_MODE][1]

    def picked(box):
        return [box.item(i).text() for i in range(box.count())
                if box.item(i).checkState() == Qt.CheckState.Checked]

    def update_profiles():
        profiles.change_predictors(picked(predictors), picked(categories))

    def update_shape():
        dialog._set_field_visibility(visibility(shape_mode.currentData()))
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)

    for box in (predictors, categories):
        box.itemChanged.connect(lambda _item: update_profiles())
    shape_mode.currentIndexChanged.connect(update_shape)
    update_profiles()
    update_shape()
    for page, key in (("variables", "status"), ("options", "model"), ("predicted", "profiles"),
                      ("predicted", "times")):
        note = QLabel(tr(HINT_KEYS[key]))
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        pages[page].addRow(note)


def message(error):
    caption = lambda text: tr(LABEL_KEYS.get(text, text))
    thousands = lambda text: text.replace(",", ".")
    shown = translate_message(error, ERROR_PREFIX, convert={
        "field": caption, "role": caption, "first": caption, "graph": caption,
        "limit": thousands, "count": thousands,
    })
    return ui(shown) if shown == str(error) else shown
