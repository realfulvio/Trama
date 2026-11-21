"""Group choices and follow-up guidance for the Qt RMST dialog."""
from PySide6.QtWidgets import QLabel

from analisi import rmst
from analisi.i18n import tr
from analisi.rmst_dialog import limit_hint
from analisi.rmst_workbench import HINT_KEYS, visibility


def attach(dialog, pages):
    def control(name):
        return dialog.controls[name][1]

    reference = control(rmst.REFERENCE)
    limit = QLabel()
    limit.setWordWrap(True)
    limit.setObjectName("muted")
    pages["variables"].addRow(limit)
    for page, hints in (("variables", ("horizon",)), ("options", ("codes", "estimate"))):
        for key in hints:
            note = QLabel(tr(HINT_KEYS[key]))
            note.setWordWrap(True)
            note.setObjectName("muted")
            pages[page].addRow(note)

    def refresh():
        choices = {field: control(field).currentData() for field in (rmst.TIME, rmst.STATUS, rmst.GROUP)}
        for field in (rmst.EVENT_CODE, rmst.CENSOR_CODE):
            choices[field] = control(field).text()
        selected = reference.currentData()
        levels = rmst.group_levels(dialog.data, choices)
        if selected and selected not in levels:
            levels.append(selected)
        reference.clear()
        for level in levels:
            reference.addItem(level, level)
        if selected:
            reference.setCurrentIndex(reference.findData(selected))
        dialog._set_field_visibility(visibility(choices[rmst.GROUP]))
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)
        limit.setText(limit_hint(rmst.horizon_limit(dialog.data, choices)))
        limit.setVisible(bool(limit.text()))

    for field in (rmst.TIME, rmst.STATUS, rmst.GROUP):
        control(field).currentIndexChanged.connect(refresh)
    for field in (rmst.EVENT_CODE, rmst.CENSOR_CODE):
        control(field).editingFinished.connect(refresh)
    refresh()
