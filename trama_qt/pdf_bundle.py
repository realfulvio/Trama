"""File → Export multiple sheets to PDF on Qt: native graphs and layouts as the pages of one PDF."""
from dataclasses import dataclass

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QGroupBox, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout)

from analisi import figure_export as fe
from analisi.data import decimal_comma
from analisi.i18n import tr
from analisi.layout_geometry import page_size

from .theme import fit_dialog


@dataclass(frozen=True)
class BundleEntry:
    """One exportable sheet; ``ref`` is its navigator reference (two sheets may share a title)."""
    ref: tuple
    kind: str  # "Graph" or "Layout"
    name: str
    size: tuple
    raster: bool = False

    @property
    def label(self):
        return f"{tr('pdf.graph') if self.kind == 'Graph' else tr('pdf.layout')} · {self.name}"


def _raster(figure):
    return bool(figure.images) or any(axes.images for axes in figure.axes)


def bundle_sheets(project, graph_refs, imported_methods):
    """Ready native graphs and layouts in navigator order, plus notes on the sheets left out."""
    entries, stale, imported = [], [], []
    for index in graph_refs:
        run = project.runs[index]
        if run.method in imported_methods:
            imported.append(run.name)
        elif (not run.calculation_error and run.result is not None and run.result.figure is not None
              and run.result.figure.axes):
            figure = run.result.figure
            entries.append(BundleEntry(("graph", index), "Graph", run.name, tuple(figure.get_size_inches()),
                                       _raster(figure)))
        else:
            stale.append(run.name)
    for index, layout in enumerate(project.layouts):
        runs = project.layout_runs(layout)
        if runs and all(run.result and run.result.figure and not run.calculation_error for run in runs):
            entries.append(BundleEntry(("layout", index), "Layout", layout.name,
                                       page_size(layout.columns, len(runs), layout.paper),
                                       any(_raster(run.result.figure) for run in runs)))
        else:
            stale.append(layout.name)
    notes = []
    if stale:
        notes.append(tr("pdf.stale", names=", ".join(stale)))
    if imported:
        notes.append(tr("pdf.imported", names=", ".join(imported)))
    return entries, notes


class PdfBundleDialog(QDialog):
    """``result`` is ``{"refs": [...], "settings": {...}}`` in output order after OK."""

    def __init__(self, parent, entries, notes=()):
        super().__init__(parent)
        self.setWindowTitle(tr("pdf.title"))
        self.entries, self.notes, self.result = list(entries), list(notes), None
        counts, self.labels = {}, []
        for entry in self.entries:
            counts[entry.label] = counts.get(entry.label, 0) + 1
            self.labels.append(entry.label if counts[entry.label] == 1 else f"{entry.label} ({counts[entry.label]})")
        self.order = list(range(len(self.entries)))

        outer = QVBoxLayout(self)
        sheets = QGroupBox(tr("pdf.sheets"))
        grid = QGridLayout(sheets)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        grid.addWidget(self.list, 0, 0, 3, 1)
        for row, (key, step) in enumerate((("pdf.up", -1), ("pdf.down", 1))):
            button = QPushButton(tr(key))
            button.clicked.connect(lambda _=False, step=step: self.move(step))
            grid.addWidget(button, row, 1)
        outer.addWidget(sheets, 1)
        pages = QGroupBox(tr("pdf.pages"))
        form = QFormLayout(pages)
        self.width = QLineEdit()
        self.width.setMaximumWidth(140)
        self.width.setAccessibleName(tr("pdf.width"))
        form.addRow(tr("pdf.width"), self.width)
        self.transparent = QCheckBox(tr("pdf.transparent"))
        form.addRow("", self.transparent)
        hint = QLabel(tr("pdf.width_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        outer.addWidget(pages)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.fill(set(range(len(self.entries))))
        self.list.itemSelectionChanged.connect(self.refresh)
        self.width.textChanged.connect(self.refresh)
        self.transparent.toggled.connect(self.refresh)
        self.refresh()
        fit_dialog(self, 560, 520)

    def fill(self, selected):
        self.list.blockSignals(True)
        self.list.clear()
        for position, index in enumerate(self.order):
            self.list.addItem(self.labels[index])
            self.list.item(position).setSelected(index in selected)
        self.list.blockSignals(False)

    def positions(self):
        return sorted(self.list.row(item) for item in self.list.selectedItems())

    def selected(self):
        return [self.entries[self.order[position]] for position in self.positions()]

    def selected_labels(self):
        return [self.labels[self.order[position]] for position in self.positions()]

    def move(self, step):
        positions = self.positions()
        if not positions or (step < 0 and positions[0] == 0) or (step > 0 and positions[-1] == len(self.order) - 1):
            return
        chosen = {self.order[position] for position in positions}
        for position in (positions if step < 0 else reversed(positions)):
            other = position + step
            self.order[position], self.order[other] = self.order[other], self.order[position]
        self.fill(chosen)
        self.refresh()

    def settings(self):
        settings = {"format": "pdf", "transparent": self.transparent.isChecked()}
        text = self.width.text().strip()
        if text:
            try:
                settings["width_mm"] = float(decimal_comma(text))
            except ValueError:
                raise ValueError(tr("pdf.invalid_width")) from None
        return settings

    def check(self):
        chosen = self.selected()
        if not chosen:
            return None, tr("pdf.select")
        try:
            plans = fe.plan_pdf_bundle([entry.size for entry in chosen], self.settings(), self.selected_labels())
        except ValueError as error:
            return None, str(error)
        return plans, None

    def refresh(self):
        plans, problem = self.check()
        if problem:
            self.summary.setObjectName("errorBanner")
            self.summary.setText(problem)
        else:
            self.summary.setObjectName("")
            order = "\n".join(f"{i}. {label} — {plan['width_mm']:.1f} × {plan['height_mm']:.1f} mm"
                              for i, (label, plan) in enumerate(zip(self.selected_labels(), plans), 1))
            pages = tr("pdf.one_page") if len(plans) == 1 else tr("pdf.many_pages", count=len(plans))
            self.summary.setText(tr("pdf.order", pages=pages, order=order))
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        chosen = self.selected()
        notes = [tr("pdf.vector")] if chosen else []
        images = [entry.name for entry in chosen if entry.raster]
        if images:
            notes.append(tr("pdf.images", names=", ".join(images)))
        self.note.setText("\n".join(notes + self.notes))

    def accept(self):
        _plans, problem = self.check()
        if problem:
            self.refresh()
            return
        self.result = {"refs": [entry.ref for entry in self.selected()], "settings": self.settings()}
        super().accept()
