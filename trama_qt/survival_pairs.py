"""Pairwise survival choices for the Qt analysis dialog."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from analisi import weighted_logrank
from analisi.i18n import tr, ui
from analisi.survival_input import (CENSOR_CODE, EVENT_CODE, OTHER_STATUS, PAIRWISE_ADJUSTED,
                                   PAIRWISE_CONTROL, PAIRWISE_CORRECTION, PAIRWISE_PAIRS,
                                   PAIRWISE_FDR, PAIRWISE_SCOPE)
from analisi.workbench import survival_levels


class PairEditor(QWidget):
    changed = Signal()

    def __init__(self, pairs):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.pairs = list(pairs) if isinstance(pairs, (list, tuple)) else []
        self.levels = ()
        self.first = QComboBox()
        self.second = QComboBox()
        self.list = QListWidget()
        self.list.setMaximumHeight(100)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.setFocusProxy(self.first)
        add = QPushButton(ui("Add"))
        add.setAutoDefault(False)
        add.clicked.connect(self.add_pair)
        remove = QPushButton(ui("Remove"))
        remove.setAutoDefault(False)
        remove.clicked.connect(self.remove_pair)
        choices = QHBoxLayout()
        choices.addWidget(self.first, 1)
        choices.addWidget(self.second, 1)
        choices.addWidget(add)
        selected = QHBoxLayout()
        selected.addWidget(self.list, 1)
        selected.addWidget(remove, alignment=Qt.AlignmentFlag.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(choices)
        layout.addLayout(selected)
        layout.addWidget(self.note)

    def set_levels(self, levels):
        self.levels = tuple(levels)
        for combo in (self.first, self.second):
            prior = combo.currentData()
            combo.clear()
            combo.addItem("", None)
            for label in levels:
                combo.addItem(label, label)
            combo.setCurrentIndex(max(0, combo.findData(prior)))
        self.refresh()

    def refresh(self):
        self.list.clear()
        unavailable = False
        for pair in self.pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(label in self.levels for label in pair):
                self.list.addItem(f"{pair[0]}  →  {pair[1]}")
            else:
                self.list.addItem(ui("Unavailable pair"))
                unavailable = True
        self.note.setText(ui("Remove unavailable pairs and choose groups in the current data.") if unavailable else "")

    def add_pair(self):
        pair = [self.first.currentData(), self.second.currentData()]
        if None in pair or pair[0] == pair[1]:
            self.note.setText(ui("Choose two different groups."))
        elif any(isinstance(saved, (list, tuple)) and list(saved) in (pair, pair[::-1]) for saved in self.pairs):
            self.note.setText(ui("This pair is already in the list."))
        else:
            self.pairs.append(pair)
            self.refresh()
            self.list.setCurrentRow(len(self.pairs) - 1)
            self.changed.emit()

    def remove_pair(self):
        row = self.list.currentRow()
        if row >= 0:
            del self.pairs[row]
            self.refresh()
            self.changed.emit()

    def values(self):
        return list(self.pairs)


def attach(dialog):
    control = lambda name: dialog.controls[name][1]
    correction, scope, adjusted = (control(name) for name in (PAIRWISE_CORRECTION, PAIRWISE_SCOPE, PAIRWISE_ADJUSTED))
    weighting = control(weighted_logrank.WEIGHTING)
    control_group, picker = (control(name) for name in (PAIRWISE_CONTROL, PAIRWISE_PAIRS))
    note = QLabel(tr("weight.help"))
    note.setObjectName("infoBanner")
    note.setWordWrap(True)
    dialog.rows[weighted_logrank.WEIGHTING][2].insertRow(0, note)

    def picked(name):
        box = control(name)
        return [box.item(row).text() for row in range(box.count())
                if box.item(row).checkState() == Qt.CheckState.Checked]

    def sync_fields():
        dialog._set_field_visibility(weighted_logrank.field_visibility(
            correction.currentData(), scope.currentData(), adjusted.isChecked(), weighting.currentData()))
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)

    def sync_groups():
        options = {"Time": control("Time").currentData(), "Event columns": picked("Event columns"),
                   "Grouping variables": picked("Grouping variables"), EVENT_CODE: control(EVENT_CODE).text(),
                   CENSOR_CODE: control(CENSOR_CODE).text(), OTHER_STATUS: control(OTHER_STATUS).currentData()}
        try:
            groups = survival_levels(dialog.data, options)
        except ValueError:
            groups = []
        prior = control_group.currentText()
        offered = list(dict.fromkeys(["", *groups, *([prior] if prior else [])]))
        control_group.clear()
        for label in offered:
            control_group.addItem(label, label)
        control_group.setCurrentIndex(control_group.findData(prior))
        picker.set_levels(groups)

    for name in ("Event columns", "Grouping variables"):
        control(name).itemChanged.connect(sync_groups)
    control("Time").currentIndexChanged.connect(sync_groups)
    control(OTHER_STATUS).currentIndexChanged.connect(sync_groups)
    for name in (EVENT_CODE, CENSOR_CODE):
        control(name).editingFinished.connect(sync_groups)
    correction.currentIndexChanged.connect(sync_fields)
    scope.currentIndexChanged.connect(sync_fields)
    adjusted.toggled.connect(sync_fields)
    weighting.currentIndexChanged.connect(sync_fields)
    for name in (weighted_logrank.RHO, weighted_logrank.GAMMA):
        control(name).textChanged.connect(lambda _text, field=name: dialog.clear_field_error(field))
    picker.changed.connect(lambda: dialog.clear_field_error(PAIRWISE_PAIRS))
    control(PAIRWISE_FDR).textChanged.connect(lambda: dialog.clear_field_error(PAIRWISE_FDR))
    sync_fields()
    sync_groups()
