"""Empirical cumulative distribution (ECDF) binding for the Qt analysis dialog.

The generic dialog renders the fields declared in ``analisi.ecdf_graph.OPTIONS``.
This binding adds dynamic visibility for ``Input`` (Single response vs Separate
columns), preserves the user's exact check order of ``Variables`` across edits
and reopened recipes, runs pre-flight validation before the worker starts, and
translates engine errors into the active UI language.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from analisi.ecdf_graph import (ERROR_PREFIX, GROUP, INPUT, MAX_CURVES, METHOD, RESPONSE, SEPARATE, SINGLE,
                                VARIABLES, check_options, visibility)
from analisi.i18n import tr, translate_message

from .labels import field_label

_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")


def _grouped(text):
    """Format comma-grouped numbers (2,000,000) with dots in Italian (2.000.000)."""
    return text.replace(",", ".") if _GROUPED.fullmatch(text) else text


class EcdfBinding:
    def __init__(self, dialog, saved):
        self.dialog = dialog
        self.input_box = dialog.controls[INPUT][1]
        self.response_box = dialog.controls[RESPONSE][1]
        self.group_box = dialog.controls[GROUP][1]
        self.variables = dialog.controls[VARIABLES][1]

        # On a fresh dialog, cap initial auto-checked numeric columns to MAX_CURVES.
        if VARIABLES not in saved:
            self.variables.blockSignals(True)
            checked_count = 0
            for i in range(self.variables.count()):
                item = self.variables.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    checked_count += 1
                    if checked_count > MAX_CURVES:
                        item.setCheckState(Qt.CheckState.Unchecked)
            self.variables.blockSignals(False)

        checked = self._checked()
        kept = [str(name) for name in (saved.get(VARIABLES) or ())]
        self.order = [name for name in kept if name in checked] + [name for name in checked if name not in kept]

        self.input_box.currentIndexChanged.connect(self.update)
        self.response_box.currentIndexChanged.connect(self._field_changed)
        self.group_box.currentIndexChanged.connect(self._field_changed)
        self.variables.itemChanged.connect(self._ticked)

        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form = dialog.rows[VARIABLES][2]
        caption = QLabel(tr("ecdf.summary.caption"))
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        caption.setMinimumWidth(150)
        caption.setMaximumWidth(230)
        form.addRow(caption, self.summary)

        self.update()

    def _checked(self):
        return [self.variables.item(i).text() for i in range(self.variables.count())
                if self.variables.item(i).checkState() == Qt.CheckState.Checked]

    def _ticked(self, item):
        name = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            if name not in self.order:
                self.order.append(name)
        elif name in self.order:
            self.order.remove(name)
        self.dialog.clear_field_error(VARIABLES)
        self.refresh()

    def _field_changed(self, *_):
        self.dialog.clear_field_error(RESPONSE)
        self.dialog.clear_field_error(GROUP)
        self.refresh()

    def ordered(self, options):
        """Return options with ``Variables`` in the exact selection order."""
        if options.get(INPUT) != SEPARATE or VARIABLES not in options:
            return options
        checked = self._checked()
        names = [name for name in self.order if name in checked] + [name for name in checked if name not in self.order]
        return {**options, VARIABLES: names}

    def update(self, *_):
        mode = self.input_box.currentData()
        self.dialog._set_field_visibility(visibility(mode))
        if self.dialog.error_field in self.dialog.hidden:
            self.dialog.clear_field_error(self.dialog.error_field)
        self.refresh()

    def refresh(self, *_):
        mode = self.input_box.currentData()
        if mode == SEPARATE:
            checked = self._checked()
            names = [name for name in self.order if name in checked] + [name for name in checked if name not in self.order]
            if not names:
                self.summary.setText(tr("ecdf.summary.none"))
            else:
                self.summary.setText(tr("ecdf.summary.order", names=" → ".join(names)))
            return
        response = self.response_box.currentData() or self.response_box.currentText()
        group = self.group_box.currentData() or ""
        if group:
            self.summary.setText(tr("ecdf.summary.grouped", response=response, group=group))
        else:
            self.summary.setText(tr("ecdf.summary.single", response=response))

    def check(self, options):
        """Validate recipe and worksheet before starting the background worker."""
        check_options(self.dialog.data, options)

    @staticmethod
    def message(error):
        return translate_message(str(error), ERROR_PREFIX,
                                 convert={"field": field_label, "limit": _grouped})


def attach(dialog, saved):
    """Attach the ECDF binding for Empirical cumulative distribution, else None."""
    if (dialog.method != METHOD or INPUT not in dialog.controls or RESPONSE not in dialog.controls
            or GROUP not in dialog.controls or VARIABLES not in dialog.controls):
        return None
    return EcdfBinding(dialog, saved)
