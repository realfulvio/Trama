"""Compose or edit a layout on Qt: name, paper, columns, background and up to twelve graph panels."""
from pathlib import Path

from PySide6.QtGui import QColor, QKeySequence, QPixmap, QShortcut
from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
                               QVBoxLayout)

from analisi.family_workflow import MAX_PREFIX
from analisi.i18n import tr, ui
from analisi.layout_arrangement import PanelArrangement
from analisi.layout_geometry import AUTO_PAPER, AXIS_ALIGNMENTS, PANEL_SIZES, PAPER_SIZES, WHITE
from analisi.presentation import Layout
from analisi.legacy_layout_edit import edited_layout_preview

from .strings import qt
from .theme import fit_dialog

PANEL_LIMIT = 12


class LayoutDialog(QDialog):
    """``runs`` are the graphs that can be panels; ``result`` is the new ``Layout`` after OK."""

    def __init__(self, parent, runs, current=None):
        super().__init__(parent)
        self.setWindowTitle(tr("layout.edit" if current else "layout.create"))
        self.runs, self.current, self.result = runs, current, None
        by_reference = {run.reference: index for index, run in enumerate(runs)}
        self.order = [by_reference.get(ref) for ref in current.panels] if current else ([] if runs else [None])
        self.original_panels = list(range(len(self.order))) if current else [None] * len(self.order)
        QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)
        counts, self.labels = {}, []
        for run in runs:
            counts[run.name] = counts.get(run.name, 0) + 1
            self.labels.append(run.name if counts[run.name] == 1 else f"{run.name} ({counts[run.name]})")

        outer = QVBoxLayout(self)
        page = QGroupBox(tr("layout.page"))
        form = QFormLayout(page)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
        self.panel_size = self.arrangement_choice(
            form, "panel_size", PANEL_SIZES, current.panel_size if current else "original")
        self.axis_alignment = self.arrangement_choice(
            form, "axis_alignment", AXIS_ALIGNMENTS, current.axis_alignment if current else "none")
        outer.addWidget(page)

        panels = QGridLayout()
        available = QGroupBox(tr("layout.available"))
        QVBoxLayout(available)
        self.available = QListWidget()
        self.available.setAccessibleName(available.title())
        self.available.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available.addItems(self.labels)
        self.available.itemDoubleClicked.connect(lambda _item: self.add_selected())
        available.layout().addWidget(self.available)
        chosen = QGroupBox(tr("layout.panels"))
        QVBoxLayout(chosen)
        self.panels = QListWidget()
        self.panels.setAccessibleName(chosen.title())
        chosen.layout().addWidget(self.panels)
        commands = QVBoxLayout()
        empty = QHBoxLayout()
        self.empty_count = QSpinBox()
        self.empty_count.setRange(1, PANEL_LIMIT)
        self.empty_count.setAccessibleName(qt("qt.layout_empty_count"))
        self.empty_count.setToolTip(qt("qt.layout_empty_count"))
        empty.addWidget(self.empty_count)
        add_empty = QPushButton(qt("qt.layout_add_empty"))
        add_empty.clicked.connect(self.add_empty)
        empty.addWidget(add_empty, 1)
        commands.addLayout(empty)
        for label, handler in ((tr("layout.add"), self.add_selected), (tr("layout.remove"), self.remove_selected),
                               (tr("layout.up"), lambda: self.move_selected(-1)),
                               (tr("layout.down"), lambda: self.move_selected(1))):
            button = QPushButton(label)
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
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setAutoDefault(True)
        ok.setDefault(True)
        self._swatch()
        self.fill_panels()
        fit_dialog(self, 720, 520)

    def arrangement_choice(self, form, key, values, current):
        label = tr(f"layout.{key}")
        choice = QComboBox()
        choice.setAccessibleName(label)
        choice.setToolTip(tr(f"layout.{key}.tip"))
        choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        choice.setMinimumContentsLength(12)
        for value in values:
            choice.addItem(tr(f"layout.{key}.{value}"), value)
        choice.setCurrentIndex(choice.findData(current))
        form.addRow(label, choice)
        return choice

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
            original = self.original_panels[i]
            if graph is not None:
                label = self.labels[graph]
            elif original is not None and (link := self.current.graph_link(original)) is not None:
                label = qt("qt.layout_linked_graph", file=Path(link.path).name)
            elif original is not None and self.current.arrangement.picture(original) is not None:
                label = qt("qt.layout_picture")
            else:
                label = qt("qt.layout_empty_slot")
            self.panels.addItem(f"{chr(ord('A') + i)} · {label}")
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
            self.original_panels.extend([None] * len(chosen))
            self.fill_panels(len(self.order) - 1)

    def add_empty(self):
        count = self.empty_count.value()
        if len(self.order) + count > PANEL_LIMIT:
            self.show_problem(tr("layout.panel_limit"))
            return
        self.order.extend([None] * count)
        self.original_panels.extend([None] * count)
        self.fill_panels(len(self.order) - 1)

    def remove_selected(self):
        index = self.panels.currentRow()
        if 0 <= index < len(self.order):
            del self.order[index]
            del self.original_panels[index]
            self.fill_panels(index)

    def move_selected(self, step):
        index = self.panels.currentRow()
        target = index + step
        if 0 <= index < len(self.order) and 0 <= target < len(self.order):
            self.order[index], self.order[target] = self.order[target], self.order[index]
            origins = self.original_panels
            origins[index], origins[target] = origins[target], origins[index]
            self.fill_panels(target)

    def accept(self):
        if not self.order:
            self.show_problem(qt("qt.layout_needs_slot"))
            self.empty_count.setFocus()
            return
        arrangement = self.current.arrangement.remap(self.original_panels) if self.current else PanelArrangement()
        links = dict(self.current.graph_links) if self.current else {}
        try:
            self.result = Layout(self.name.text().strip(), int(self.columns.currentText()),
                                 [self.runs[i].reference if i is not None else None for i in self.order],
                                 self.paper.currentData(), self.background.text().strip(), self.panel_size.currentData(),
                                 self.axis_alignment.currentData(), self.current.tables if self.current else [],
                                 arrangement, tuple((index, links[origin]) for index, origin in enumerate(
                                     self.original_panels) if origin in links))
        except ValueError as error:
            self.show_problem(str(error))
            return
        super().accept()


class LayoutGraphDialog(QDialog):
    """Choose a graph for an empty or occupied panel on the active layout."""

    EDIT_GEOMETRY = 2
    GO_ORIGIN = 3
    CURRENT_PICTURE = "current-picture"

    def __init__(self, parent, layout, runs, panel=None):
        super().__init__(parent)
        self.runs = {run.reference: run for run in runs}
        self.local_runs = self.runs
        self.source_project = self.source_figure = None
        self.pending = None
        self.poll = QTimer(self, interval=40)
        self.poll.timeout.connect(self._receive_source)
        self.finished.connect(self._discard_source_request)
        self.picture = layout.arrangement.picture(panel)
        self.current_link = layout.graph_link(panel)
        self.source_path = None
        self.current = self.CURRENT_PICTURE if self.picture else layout.panels[panel] if panel is not None else None
        self.setWindowTitle(qt("qt.layout_replace_graph" if self.current else "qt.layout_place_graph").rstrip("…"))
        QShortcut(QKeySequence("F1"), self, self.show_shortcuts)
        form = QFormLayout(self)
        self.panels = QComboBox()
        self.panels.setAccessibleName(qt("qt.layout_panel"))
        for index in (panel,) if panel is not None else layout.empty_panels:
            if index not in layout.arrangement.locked:
                self.panels.addItem(chr(ord("A") + index), index)
        form.addRow(qt("qt.layout_panel"), self.panels)
        self.panels.setEnabled(panel is None)
        self.sources = QComboBox()
        self.sources.setAccessibleName(qt("qt.layout_source"))
        self.sources.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sources.setMinimumContentsLength(18)
        self.sources.addItem(qt("qt.layout_current_source"))
        for session, (caption, tip) in zip(parent.sessions, parent.sessions.labels(), strict=True):
            if session is not parent.sessions.active:
                self.sources.addItem(caption, session)
                self.sources.setItemData(self.sources.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        browse = QPushButton(qt("qt.layout_source_browse"))
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        source_row = QHBoxLayout()
        source_row.addWidget(self.sources, 1)
        source_row.addWidget(browse)
        form.addRow(qt("qt.layout_source"), source_row)
        self.graphs = QComboBox()
        self.graphs.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.graphs.setMinimumContentsLength(24)
        self.graphs.setAccessibleName(qt("qt.layout_graph"))
        self.origin_button = QPushButton(qt("qt.layout_go_origin_short"))
        self.origin_button.setAccessibleName(qt("qt.layout_go_origin"))
        self.origin_button.setAutoDefault(False)
        self.origin_button.clicked.connect(self._go_origin)
        self.origin = None
        graph_row = QHBoxLayout()
        graph_row.addWidget(self.graphs, 1)
        graph_row.addWidget(self.origin_button)
        form.addRow(qt("qt.layout_graph"), graph_row)
        self.embed = QCheckBox(qt("qt.layout_picture_create"))
        self.embed.setToolTip(qt("qt.layout_picture_tip"))
        form.addRow(self.embed)
        self.method = QComboBox()
        self.method.setAccessibleName(qt("qt.layout_transfer_method"))
        self.method.addItem(qt("qt.layout_transfer_picture"), "picture")
        self.method.addItem(qt("qt.layout_transfer_editable"), "family")
        form.addRow(qt("qt.layout_transfer_method"), self.method)
        self.prefix = QLineEdit()
        self.prefix.setMaxLength(MAX_PREFIX)
        self.prefix.setAccessibleName(qt("qt.layout_transfer_prefix"))
        self.prefix.setToolTip(qt("qt.layout_transfer_prefix_tip"))
        form.addRow(qt("qt.layout_transfer_prefix"), self.prefix)
        self.preview = QLabel()
        self.preview.setAccessibleName(qt("qt.layout_graph_preview"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(145)
        self.preview.setWordWrap(True)
        form.addRow(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText(tr("setup.cancel"))
        cancel.setAutoDefault(False)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.geometry_button = None
        if self.current is not None and len(layout.arrangement.objects((panel,))[0]) == 1:
            self.geometry_button = buttons.addButton(qt("qt.layout_position"), QDialogButtonBox.ButtonRole.ActionRole)
            self.geometry_button.setAutoDefault(False)
            self.geometry_button.clicked.connect(lambda: self.done(self.EDIT_GEOMETRY))
        self.ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.sources.currentIndexChanged.connect(self._change_source)
        self.method.currentIndexChanged.connect(self._show_transfer_options)
        self.graphs.currentIndexChanged.connect(self.update_preview)
        self._change_source()
        self.graphs.setFocus()
        fit_dialog(self, 520, self.sizeHint().height())

    def _browse(self):
        from .project import PROJECT_SUFFIXES

        extensions = " ".join(f"*{suffix}" for suffix in sorted(PROJECT_SUFFIXES))
        name, _ = QFileDialog.getOpenFileName(self, qt("qt.layout_source_files"), "",
                                             f'{qt("qt.layout_source_files")} ({extensions})')
        if not name:
            return
        sessions = self.parentWidget().sessions
        session = sessions.find(name)
        if session is sessions.active:
            self.sources.setCurrentIndex(0)
        elif session is not None:
            self.sources.setCurrentIndex(next(i for i in range(self.sources.count())
                                              if self.sources.itemData(i) is session))
        else:
            path = Path(name)
            index = next((i for i in range(self.sources.count()) if self.sources.itemData(i) == path), -1)
            if index < 0:
                self.sources.addItem(path.name, path)
                index = self.sources.count() - 1
                self.sources.setItemData(index, str(path), Qt.ItemDataRole.ToolTipRole)
            self.sources.setCurrentIndex(index)

    def _show_transfer_options(self, *_):
        external = self.sources.currentIndex() > 0
        self.layout().setRowVisible(self.embed, not external)
        self.layout().setRowVisible(self.method, external)
        self.layout().setRowVisible(self.prefix, external and self.method.currentData() == "family")

    def _fill_graphs(self, runs, *, local=False):
        self.runs = runs
        with QSignalBlocker(self.graphs):
            self.graphs.clear()
            if local and self.current is not None:
                self.graphs.addItem(qt("qt.layout_no_assigned_graph"), None)
                if self.picture is not None:
                    label = qt("qt.layout_linked_graph", file=Path(self.current_link.path).name) if self.current_link else (
                        qt("qt.layout_picture"))
                    self.graphs.addItem(label, self.CURRENT_PICTURE)
            for run in runs.values():
                self.graphs.addItem(f"{run.name} · {run.title} ({run.slot + 1})", run.reference)
            if local and self.current is not None:
                match = next((i for i in range(self.graphs.count()) if self.graphs.itemData(i) == self.current), 0)
                self.graphs.setCurrentIndex(match)
        self.graphs.setEnabled(bool(self.graphs.count()))
        self.origin_button.setEnabled(False)

    def _change_source(self, *_):
        from .layout_transfer import read_source

        self._discard_source_request()
        self.source_project = self.source_figure = None
        source = self.sources.currentData()
        self.source_path = source if isinstance(source, Path) else (
            source.project.path or source.project.origin if source is not None else None)
        live = self.method.findData("live")
        if self.source_path is not None and live < 0:
            self.method.addItem(qt("qt.layout_transfer_live"), "live")
        elif self.source_path is None and live >= 0:
            self.method.removeItem(live)
        self._show_transfer_options()
        if self.geometry_button is not None:
            self.geometry_button.setEnabled(False)
        if source is None:
            self._fill_graphs(self.local_runs, local=True)
            self.update_preview()
            return
        self._fill_graphs({})
        try:
            snapshot = None if isinstance(source, Path) else source.project.snapshot()
        except Exception as error:
            self._show_source_error(error)
            return
        self._request_source(lambda _: read_source(source, snapshot), self._source_loaded)

    def _request_source(self, job, ready):
        from .project import CalculationControl

        self._discard_source_request()
        control = CalculationControl()
        self.pending = (self.parentWidget().worker.submit(job, control), control, ready)
        self.ok_button.setEnabled(False)
        self.origin_button.setEnabled(False)
        self.preview.setToolTip("")
        self.preview.setText(qt("qt.layout_source_loading"))
        self.poll.start()

    def _discard_source_request(self, *_):
        if self.pending is not None:
            future, control, _ = self.pending
            control.cancel.set()
            future.cancel()
            self.pending = None
        self.poll.stop()

    def _receive_source(self):
        future, _, ready = self.pending
        if not future.done():
            return
        self.pending = None
        self.poll.stop()
        try:
            ready(future.result())
        except Exception as error:
            self._show_source_error(error)

    def _show_source_error(self, error):
        self.ok_button.setEnabled(False)
        self.preview.setToolTip(str(error))
        self.preview.setText(qt("qt.layout_source_error", error=str(error)[:160]))

    def _source_loaded(self, outcome):
        self.source_project, runs = outcome
        self._fill_graphs({run.reference: run for run in runs})
        self.update_preview()

    def _show_figure(self, figure):
        from .gallery_thumbs import figure_image

        ratio = self.preview.devicePixelRatioF()
        pixmap = QPixmap.fromImage(figure_image(figure, round(410 * ratio), round(145 * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        self.preview.setPixmap(pixmap)

    def _external_preview(self, figure):
        self._show_figure(figure)
        self.source_figure = figure
        self.ok_button.setEnabled(True)
        self.origin_button.setEnabled(True)

    def _go_origin(self):
        if not self.origin_button.isEnabled():
            return
        graph = self.graphs.currentData()
        selected = self.sources.currentData()
        if graph == self.CURRENT_PICTURE:
            self.origin = (self.current_link, None)
        elif isinstance(selected, Path):
            from .layout_transfer import make_graph_link

            try:
                self.origin = (make_graph_link(self.source_project, selected, graph), None)
            except ValueError as error:
                self.preview.setText(qt("qt.layout_go_origin_failed", error=error))
                return
        else:
            self.origin = (graph, selected or self.parentWidget().sessions.active)
        self.done(self.GO_ORIGIN)

    def show_shortcuts(self):
        self.parentWidget().show_shortcuts()
        self.ok_button.setDefault(True)

    def update_preview(self, *_):
        self.preview.clear()
        self.preview.setToolTip("")
        graph = self.graphs.currentData()
        self.graphs.setToolTip(self.graphs.currentText())
        external = self.source_project is not None
        if self.geometry_button is not None:
            self.geometry_button.setEnabled(self.sources.currentIndex() == 0 and graph == self.current)
        run = self.runs.get(graph)
        self.ok_button.setEnabled(not external and bool(self.graphs.count()))
        self.origin_button.setEnabled(not external and (run is not None
                                      or (graph == self.CURRENT_PICTURE and self.current_link is not None)))
        if external:
            from .layout_transfer import prepare_preview

            self.source_figure = None
            if run is None:
                self.preview.setText(qt("qt.layout_source_empty"))
            else:
                source = self.source_project
                self._request_source(lambda control: prepare_preview(source, run, control), self._external_preview)
            return
        self.embed.setEnabled(run is not None and run.result is not None and run.result.figure is not None
                              and not run.calculation_error)
        if self.graphs.count() == 0:
            self.preview.setText(qt("qt.layout_no_graph"))
            return
        if graph is None and self.current is not None:
            self.preview.setText(qt("qt.layout_clear_preview"))
            return
        try:
            if graph == self.CURRENT_PICTURE:
                from analisi.layout_picture import picture_figure
                view = self.parentWidget().project.linked_graph_views.get(self.current_link)
                figure = view.figure if view and view.figure is not None else picture_figure(self.picture)
            elif run is not None and run.result is not None:
                figure = run.result.figure
            else:
                figure = None
            if figure is not None:
                self._show_figure(figure)
        except (ValueError, RuntimeError):
            self.preview.setText(qt("qt.layout_graph_no_preview"))


class ImportedPanelDialog(QDialog):
    """Edit one panel's rectangle in its original layout units."""

    def __init__(self, parent, preview, panels, edits):
        super().__init__(parent)
        self.setWindowTitle(ui("Edit imported layout panel"))
        self.preview, self.panels, self.edits = preview, panels, edits
        self.result = None
        form = QFormLayout(self)
        self.selector = QComboBox()
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setMinimumContentsLength(22)
        for panel in panels:
            self.selector.addItem(f'{panel["id"]} · {panel.get("title") or ui("Panel")}')
        form.addRow(ui("Panel"), self.selector)
        self.fields = []
        for label in ("Left", "Top", "Width", "Height"):
            entry = QLineEdit()
            entry.setMaxLength(12)
            entry.setAccessibleName(ui(label))
            form.addRow(ui(label), entry)
            self.fields.append(entry)
        self.restore = QPushButton(ui("Restore original position"))
        self.restore.clicked.connect(lambda: self.load_bounds(original=True))
        form.addRow(self.restore)
        note = QLabel(ui("Coordinates use the original layout units.\nApply one panel at a time."))
        note.setWordWrap(True)
        form.addRow(note)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ui("Apply"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.selector.currentIndexChanged.connect(lambda _: self.load_bounds())
        self.load_bounds()
        fit_dialog(self, 460, 320)

    def load_bounds(self, *, original=False):
        panel = self.panels[self.selector.currentIndex()]
        left, top, right, bottom = panel["bounds"] if original else self.edits.get(panel["id"], panel["bounds"])
        for entry, value in zip(self.fields, (left, top, right - left, bottom - top), strict=True):
            entry.setText(str(value))
        self.problem.clear()
        self.problem.hide()

    def accept(self):
        values = []
        for entry in self.fields:
            try:
                values.append(int(entry.text()))
            except ValueError:
                self.problem.setText(ui("Enter whole numbers for the position and size."))
                self.problem.show()
                entry.setFocus()
                return
        left, top, width, height = values
        panel = self.panels[self.selector.currentIndex()]
        edits = dict(self.edits)
        bounds = [left, top, left + width, top + height]
        if bounds == panel["bounds"]:
            edits.pop(panel["id"], None)
        else:
            edits[panel["id"]] = bounds
        try:
            edited_layout_preview(self.preview, self.panels, edits)
        except ValueError as error:
            self.problem.setText(ui(str(error)))
            self.problem.show()
            return
        self.result = edits
        super().accept()
