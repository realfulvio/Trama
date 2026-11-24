"""Raincloud plot binding for the Classica Qt analysis dialog.

The generic dialog builds controls from ``analisi.raincloud_plot.OPTIONS``. This binding toggles
``Bandwidth multiplier`` visibility with ``Show density``, preselects a numeric-looking response
column when string values prevent pandas from marking it numeric, shows a brief note, runs
pre-flight option validation before starting the worker, and translates engine messages.
"""
import numpy as np
from PySide6.QtWidgets import QLabel

from analisi.i18n import tr, translate_message
from analisi.raincloud_plot import (
    BANDWIDTH_MULTIPLIER,
    ERROR_PREFIX,
    GROUP,
    METHOD,
    ORIENTATION,
    RESPONSE,
    SHOW_BOX,
    SHOW_DENSITY,
    SHOW_POINTS,
    _parse_response,
    check_options,
    visibility,
)

from .labels import field_label


class RaincloudPlotBinding:
    """Manage conditional bandwidth field, pre-flight checks, and EN/IT error wording."""

    def __init__(self, dialog, saved):
        self.dialog = dialog
        self.response_box = dialog.controls[RESPONSE][1]
        self.group_box = dialog.controls[GROUP][1]
        self.orientation_box = dialog.controls[ORIENTATION][1]
        self.density_box = dialog.controls[SHOW_DENSITY][1]
        self.box_box = dialog.controls[SHOW_BOX][1]
        self.points_box = dialog.controls[SHOW_POINTS][1]
        self.bandwidth_edit = dialog.controls[BANDWIDTH_MULTIPLIER][1]

        if not saved:
            self._choose_default_response()

        note = QLabel(tr("raincloud.help.text"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        _, _, options_form = dialog.rows[BANDWIDTH_MULTIPLIER]
        options_form.addRow(QLabel(tr("raincloud.help.caption")), note)

        self.density_box.toggled.connect(self._sync_visibility)
        self._sync_visibility()

        for field_name, widget, signal in (
            (RESPONSE, self.response_box, self.response_box.currentIndexChanged),
            (GROUP, self.group_box, self.group_box.currentIndexChanged),
            (ORIENTATION, self.orientation_box, self.orientation_box.currentIndexChanged),
            (SHOW_DENSITY, self.density_box, self.density_box.toggled),
            (SHOW_BOX, self.box_box, self.box_box.toggled),
            (SHOW_POINTS, self.points_box, self.points_box.toggled),
            (BANDWIDTH_MULTIPLIER, self.bandwidth_edit, self.bandwidth_edit.textEdited),
        ):
            signal.connect(lambda _v=None, name=field_name: dialog.clear_field_error(name))

    def _choose_default_response(self):
        frame = self.dialog.data
        current = self.response_box.currentData()
        if current in frame and np.isfinite(_parse_response(frame[current])).any():
            return
        for col in frame.columns:
            if np.isfinite(_parse_response(frame[col])).any():
                idx = self.response_box.findData(str(col))
                if idx >= 0:
                    self.response_box.setCurrentIndex(idx)
                return

    def _sync_visibility(self):
        self.dialog._set_field_visibility(visibility(self.density_box.isChecked()))

    def check(self, options):
        check_options(self.dialog.data, options)

    def message(self, error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label})


def attach(dialog, saved):
    """Attach the raincloud binding when ``dialog.method`` is ``Raincloud plot``."""
    return RaincloudPlotBinding(dialog, saved) if dialog.method == METHOD else None
