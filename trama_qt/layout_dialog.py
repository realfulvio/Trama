"""Compose or edit a layout on Qt: name, paper, columns, background and up to twelve graph panels."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
                               QVBoxLayout)

from analisi.i18n import tr
from analisi.layout_geometry import AUTO_PAPER, PAPER_SIZES, WHITE
from analisi.presentation import Layout

PANEL_LIMIT = 12


class LayoutDialog(QDialog):
    """``runs`` are the graphs that can be panels; ``result`` is the new ``Layout`` after OK."""

    def __init__(self, parent, runs, current=None):
        super().__init__(parent)
        self.setWindowTitle(tr("layout.edit" if current else "layout.create"))
        self.runs, self.current, self.result = runs, current, None
        by_reference = {run.reference: index for index, run in enumerate(runs)}
        self.order = [by_reference[ref] for ref in current.panels if ref in by_reference] if current else []
        counts, self.labels = {}, []
        for run in runs:
            counts[run.name] = counts.get(run.name, 0) + 1
            self.labels.append(run.name if counts[run.name] == 1 else f"{run.name} ({counts[run.name]})")

        outer = QVBoxLayout(self)
        page = QGroupBox(tr("layout.page"))
        form = QFormLayout(page)
        self.name = QLineEdit(current.name if current else "Figure 1")
        form.addRow(tr("layout.name"), self.name)
        self.paper = QComboBox()
        for paper in PAPER_SIZES:
            self.paper.addItem(tr(f"layout.paper.{paper}"), paper)
        self.paper.setCurrentIndex(max(0, self.paper.findData(current.paper if current else AUTO_PAPER)))
        self.columns = QComboBox()
        self.columns.addItems(["1", "2", "3", "4"])
        self.columns.setCurrentText(str(current.columns if current else 2))
        row = QHBoxLayout()
        row.addWidget(self.paper, 1)
        row.addWidget(QLabel(tr("layout.columns")))
        row.addWidget(self.columns)
        form.addRow(tr("layout.paper"), row)
        self.background = QLineEdit(current.background if current else WHITE)
        self.background.setMaximumWidth(120)
        self.swatch = QLabel()
        self.swatch.setFixedSize(22, 22)
        choose = QPushButton(tr("layout.choose"))
        choose.clicked.connect(self.choose_background)
        self.background.textChanged.connect(self._swatch)
        row = QHBoxLayout()
        row.addWidget(self.background)
        row.addWidget(self.swatch)
        row.addWidget(choose)
        row.addStretch(1)
        form.addRow(tr("layout.background"), row)
        outer.addWidget(page)

        panels = QGridLayout()
        available = QGroupBox(tr("layout.available"))
        QVBoxLayout(available)
        self.available = QListWidget()
        self.available.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available.addItems(self.labels)
        self.available.itemDoubleClicked.connect(lambda _item: self.add_selected())
        available.layout().addWidget(self.available)
        chosen = QGroupBox(tr("layout.panels"))
        QVBoxLayout(chosen)
        self.panels = QListWidget()
        chosen.layout().addWidget(self.panels)
        commands = QVBoxLayout()
        for key, handler in (("layout.add", self.add_selected), ("layout.remove", self.remove_selected),
                             ("layout.up", lambda: self.move_selected(-1)),
                             ("layout.down", lambda: self.move_selected(1))):
            button = QPushButton(tr(key))
            button.clicked.connect(handler)
            commands.addWidget(button)
        commands.addStretch(1)
        panels.addWidget(available, 0, 0)
        panels.addLayout(commands, 0, 1)
        panels.addWidget(chosen, 0, 2)
        outer.addLayout(panels, 1)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._swatch()
        self.fill_panels()
        self.resize(720, 520)

    def _swatch(self, *_):
        color = QColor(self.background.text().strip())
        self.swatch.setStyleSheet(f"background: {color.name() if color.isValid() else WHITE};"
                                  " border: 1px solid #8a9aa6; border-radius: 3px;")

    def choose_background(self):
        color = QColorDialog.getColor(QColor(self.background.text().strip() or WHITE), self)
        if color.isValid():
            self.background.setText(color.name())

    def show_problem(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    def fill_panels(self, selection=None):
        self.panels.clear()
        for i, graph in enumerate(self.order):
            self.panels.addItem(f"{chr(ord('A') + i)} · {self.labels[graph]}")
        if selection is not None and self.order:
            self.panels.setCurrentRow(min(selection, len(self.order) - 1))
        self.show_problem("")

    def add_selected(self):
        chosen = sorted(self.available.row(item) for item in self.available.selectedItems())
        if len(self.order) + len(chosen) > PANEL_LIMIT:
            self.show_problem(tr("layout.panel_limit"))
            return
        if chosen:
            self.order.extend(chosen)
            self.fill_panels(len(self.order) - 1)

    def remove_selected(self):
        index = self.panels.currentRow()
        if 0 <= index < len(self.order):
            del self.order[index]
            self.fill_panels(index)

    def move_selected(self, step):
        index = self.panels.currentRow()
        target = index + step
        if 0 <= index < len(self.order) and 0 <= target < len(self.order):
            self.order[index], self.order[target] = self.order[target], self.order[index]
            self.fill_panels(target)

    def accept(self):
        if not self.order:
            self.show_problem(tr("layout.select"))
            self.available.setFocus()
            return
        try:
            self.result = Layout(self.name.text().strip(), int(self.columns.currentText()),
                                 [self.runs[i].reference for i in self.order], self.paper.currentData(),
                                 self.background.text().strip())
        except ValueError as error:
            self.show_problem(str(error))
            return
        super().accept()
