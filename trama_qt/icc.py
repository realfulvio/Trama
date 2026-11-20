"""Intraclass correlation in the Qt analysis dialog.

The generic dialog draws the fields of ``analisi.icc.OPTIONS`` (and the ``Raters`` list the workbench adds). This
binding adds what is specific to the method: the bootstrap fields are shown (and stored) only with Bootstrap CI,
the raters are kept in the order the user ticked them (the profile graph and the sheets follow it), a short summary
of complete subjects, raters and unit sits under the columns, the engine's checks of recipe and worksheet run when
the user presses Run (before any worker starts), and the English engine messages are shown in the active language.
The recipe keeps the canonical English keys and values.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from analisi.i18n import tr, translate_message
from analisi.icc import (BOOTSTRAP, DEFINITION, ERROR_PREFIX, METHOD, RATERS, UNIT, check_options, summary, visibility)

from .labels import choice_label, field_label


class IccBinding:
    def __init__(self, dialog, saved):
        self.dialog = dialog
        self.raters = dialog.controls[RATERS][1]
        self.bootstrap = dialog.controls[BOOTSTRAP][1]
        checked = self._checked()
        kept = [str(name) for name in (saved.get(RATERS) or ())]
        self.order = [name for name in kept if name in checked] + [name for name in checked if name not in kept]
        self.raters.itemChanged.connect(self._ticked)
        self.bootstrap.toggled.connect(self.update)
        for name in (DEFINITION, UNIT):
            dialog.controls[name][1].currentIndexChanged.connect(self.refresh)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form = dialog.rows[RATERS][2]
        caption = QLabel(tr("icc.summary.caption"))
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        caption.setMinimumWidth(150)
        caption.setMaximumWidth(230)
        form.addRow(caption, self.summary)
        self.update()
        self.refresh()

    def _checked(self):
        return [self.raters.item(i).text() for i in range(self.raters.count())
                if self.raters.item(i).checkState() == Qt.CheckState.Checked]

    def _ticked(self, item):
        name = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            if name not in self.order:
                self.order.append(name)
        elif name in self.order:
            self.order.remove(name)
        self.refresh()

    def ordered(self, options):
        """The recipe with the raters in the order they were ticked."""
        if RATERS not in options:
            return options
        checked = self._checked()
        names = [name for name in self.order if name in checked] + [name for name in checked
                                                                    if name not in self.order]
        return {**options, RATERS: names}

    def update(self, *_):
        for name, visible in visibility(self.bootstrap.isChecked()).items():
            row = self.dialog.rows.get(name)
            if row is None:
                continue
            _caption, widget, form = row
            form.setRowVisible(widget, visible)
            if visible:
                self.dialog.hidden.discard(name)
            else:
                self.dialog.hidden.add(name)

    def refresh(self, *_):
        names = [name for name in self.order if name in self._checked()]
        if len(names) < 2:
            self.summary.setText(tr("icc.summary.none"))
            return
        counts = summary(self.dialog.data, {RATERS: names})
        definition = self.dialog.controls[DEFINITION][1].currentData()
        unit = self.dialog.controls[UNIT][1].currentData()
        self.summary.setText("\n".join((
            tr("icc.summary.counts", **counts),
            tr("icc.summary.order", names=" → ".join(names)),
            tr("icc.summary.unit", definition=choice_label(definition), unit=choice_label(unit)))))

    def check(self, options):
        """Raise the engine's ``FieldError`` for recipe and worksheet; nothing is resampled here."""
        check_options(self.dialog.data, options)

    @staticmethod
    def message(error):
        return translate_message(str(error), ERROR_PREFIX, convert={"field": field_label, "raters": field_label})


def attach(dialog, saved):
    """The binding for Intraclass correlation, or None for every other analysis."""
    if dialog.method != METHOD or RATERS not in dialog.controls or BOOTSTRAP not in dialog.controls:
        return None
    return IccBinding(dialog, saved)
