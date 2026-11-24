"""Two-factor interaction plot binding for the Qt analysis dialog.

The generic dialog builds controls from ``analisi.interaction_plot.OPTIONS``.
This binding adds dynamic visibility for ``Confidence level`` (shown only when
``Error bars`` is ``Confidence interval``), displays the short descriptive help
note, runs pre-flight checks before starting the worker, and translates engine
``FieldError`` messages into the active UI language.
"""
from PySide6.QtWidgets import QLabel

from analisi.i18n import tr, translate_message
from analisi.interaction_plot import (
    CONFIDENCE_LEVEL,
    DEFAULT_ERROR_BARS,
    ERROR_BARS,
    ERROR_PREFIX,
    METHOD,
    RESPONSE,
    SERIES_FACTOR,
    X_FACTOR,
    check_options,
    visibility,
)

from .labels import field_label


class InteractionPlotBinding:
    """Manage visibility, help note, pre-flight validation, and error wording."""

    def __init__(self, dialog, saved):
        self.dialog = dialog
        self.response_box = dialog.controls[RESPONSE][1]
        self.x_box = dialog.controls[X_FACTOR][1]
        self.series_box = dialog.controls[SERIES_FACTOR][1]
        self.error_bars_box = dialog.controls[ERROR_BARS][1]
        self.confidence_edit = dialog.controls[CONFIDENCE_LEVEL][1]

        if RESPONSE not in saved:
            used = {self.x_box.currentData(), self.series_box.currentData()}
            if self.response_box.currentData() in used:
                for i in range(self.response_box.count() - 1, -1, -1):
                    col = self.response_box.itemData(i)
                    if col and col not in used:
                        self.response_box.setCurrentIndex(i)
                        break

        self.help_note = QLabel(tr("interaction.help.text"))
        self.help_note.setObjectName("muted")
        self.help_note.setWordWrap(True)
        options_form = dialog.rows[ERROR_BARS][2]
        options_form.addRow(QLabel(tr("interaction.help.caption")), self.help_note)

        self.response_box.currentIndexChanged.connect(lambda _i: self._clear_roles())
        self.x_box.currentIndexChanged.connect(lambda _i: self._clear_roles())
        self.series_box.currentIndexChanged.connect(lambda _i: self._clear_roles())
        self.error_bars_box.currentIndexChanged.connect(self._mode_changed)
        self.confidence_edit.textChanged.connect(lambda _t: self.dialog.clear_field_error(CONFIDENCE_LEVEL))

        self._sync_visibility()

    def _clear_roles(self):
        for field in (RESPONSE, X_FACTOR, SERIES_FACTOR):
            self.dialog.clear_field_error(field)

    def _mode_changed(self, _index):
        self.dialog.clear_field_error(ERROR_BARS)
        self._sync_visibility()

    def _sync_visibility(self):
        mode = self.error_bars_box.currentData()
        self.dialog._set_field_visibility(visibility(mode))
        if self.dialog.error_field in self.dialog.hidden:
            self.dialog.clear_field_error(self.dialog.error_field)

    def check(self, options):
        """Validate recipe and worksheet before starting the background worker."""
        check_options(self.dialog.data, options)

    @staticmethod
    def message(error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label})


def attach(dialog, saved):
    """Attach the binding when ``dialog.method`` is ``Interaction plot``."""
    if dialog.method != METHOD:
        return None
    required = (RESPONSE, X_FACTOR, SERIES_FACTOR, ERROR_BARS, CONFIDENCE_LEVEL)
    if any(name not in dialog.controls for name in required):
        return None
    return InteractionPlotBinding(dialog, saved)
