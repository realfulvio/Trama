"""Graph preview and formatting while the source worksheet stays open."""

from copy import deepcopy

from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from analisi.i18n import tr, ui
from analisi.presentation import apply_style, validate_graph_style

from .flow import FlowLayout
from .inspector import GraphInspector
from .strings import qt


class WorksheetPreview(QWidget):
    """Keep the original figure and its canvas independent of the worksheet preview."""

    def __init__(self, window, title, sheet):
        super().__init__()
        self.window, self.project, self.title = window, window.project, title
        self.enabled = False
        self.area = None
        self.canvas = None
        self.run = self.result = None
        self._style = None
        self.graphs = ()
        self.links = ()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.heading = QWidget()
        heading_layout = QVBoxLayout(self.heading)
        heading_layout.setContentsMargins(10, 7, 10, 3)
        heading_layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.title_label.setWordWrap(True)
        heading_layout.addWidget(self.title_label)
        sections = QWidget()
        section_layout = FlowLayout(sections)
        current = QLabel(tr("nav.data_tables"))
        current.setObjectName("sectionTitle")
        section_layout.addWidget(current)
        self.link_buttons = {}
        for kind, key in (("result", "nav.results"), ("graph", "nav.graphs")):
            button = QPushButton(tr(key))
            button.setMenu(QMenu(button))
            button.setEnabled(False)
            self.link_buttons[kind] = button
            section_layout.addWidget(button)
        heading_layout.addWidget(sections)
        root.addWidget(self.heading)
        self.heading.hide()

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(8, 2, 8, 2)
        action = window.actions["worksheet_preview"]
        self.preview_box = QCheckBox(action.text())
        self.preview_box.clicked.connect(lambda: action.trigger())
        action.changed.connect(self._sync_controls)
        row.addWidget(self.preview_box)
        row.addStretch()
        self.format_box = QCheckBox(tr("modern.format"))
        self.format_box.toggled.connect(self._toggle_format)
        self.format_box.hide()
        row.addWidget(self.format_box)
        root.addWidget(controls)
        self._sync_controls()

        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.setChildrenCollapsible(False)
        self.grid = QSplitter(Qt.Orientation.Vertical)
        self.grid.addWidget(sheet)
        self.grid.setChildrenCollapsible(False)
        self.workspace.addWidget(self.grid)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.workspace)
        root.addWidget(self.scroll, 1)

    def _sync_controls(self):
        action = self.window.actions["worksheet_preview"]
        self.preview_box.setEnabled(action.isEnabled())
        self.preview_box.setChecked(action.isChecked())

    def _build(self):
        self.area = QWidget()
        layout = QVBoxLayout(self.area)
        layout.setContentsMargins(8, 4, 8, 0)
        controls = QWidget()
        header = FlowLayout(controls)
        header.addWidget(QLabel(tr("modern.preview")))
        self.choice = QComboBox()
        self.choice.setAccessibleName(tr("modern.preview"))
        self.choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.choice.setMinimumContentsLength(12)
        self.choice.currentIndexChanged.connect(self._choose)
        header.addWidget(self.choice)
        self.open_button = QPushButton(tr("modern.open_graph"))
        self.open_button.clicked.connect(self._open_graph)
        header.addWidget(self.open_button)
        layout.addWidget(controls)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.calculate = QPushButton(tr("modern.calculate"))
        self.calculate.clicked.connect(self._calculate)
        layout.addWidget(self.calculate, 0, Qt.AlignmentFlag.AlignHCenter)
        self.plot = QVBoxLayout()
        self.plot.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.plot, 1)
        self.grid.addWidget(self.area)
        self.grid.setStretchFactor(0, 3)
        self.grid.setStretchFactor(1, 2)
        self.grid.setSizes([360, 235])

        self.sidebar = QWidget()
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(6, 4, 4, 0)
        table = QGroupBox(tr("modern.table"))
        details = QVBoxLayout(table)
        self.table_info = QLabel()
        details.addWidget(self.table_info)
        side.addWidget(table)
        self.format_note = QLabel()
        self.format_note.setWordWrap(True)
        side.addWidget(self.format_note)
        self.inspector_area = QVBoxLayout()
        self.inspector_area.setContentsMargins(0, 0, 0, 0)
        side.addLayout(self.inspector_area, 1)
        self.workspace.addWidget(self.sidebar)
        self.workspace.setStretchFactor(0, 1)
        self.workspace.setStretchFactor(1, 0)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if self.area is None:
            if not enabled:
                return
            self._build()
        self.area.setVisible(enabled)
        self.heading.setVisible(enabled)
        self.format_box.setVisible(enabled)
        if enabled:
            self.refresh()
        else:
            self._format(False)
            self.release()

    def refresh(self):
        if not self.enabled:
            return
        links = tuple((name, (kind, index))
                      for name, (kind, index), _ in self.window.navigator_entries
                      if kind in self.link_buttons and self.project.runs[index].title == self.title)
        if links != self.links:
            self.links = links
            for kind, button in self.link_buttons.items():
                menu = button.menu()
                menu.clear()
                for name, ref in links:
                    if ref[0] == kind:
                        menu.addAction(name, lambda _checked=False, item=ref: self._open_link(item))
                button.setEnabled(bool(menu.actions()))
        graphs = tuple((index, self.project.runs[index].uid, name)
                       for name, (kind, index) in links if kind == "graph")
        if graphs != self.graphs:
            selected = self.choice.currentData()
            self.graphs = graphs
            with QSignalBlocker(self.choice):
                self.choice.clear()
                for _, uid, label in graphs:
                    self.choice.addItem(label, uid)
                previous = self.choice.findData(selected)
                self.choice.setCurrentIndex(previous if previous >= 0 else len(graphs) - 1)
        index = self.choice.currentIndex()
        run = self.project.runs[graphs[index][0]] if 0 <= index < len(graphs) else None
        result = run.result if run is not None else None
        style = deepcopy(run.style) if run is not None else None
        if run is not self.run or result is not self.result or style != self._style:
            self.release()
            self.run, self.result, self._style = run, result, style
            if result is not None and result.figure is not None:
                self._draw(result.figure)
        self._format(self.format_box.isChecked())
        self.set_busy()

    def _draw(self, figure):
        canvas = None
        try:
            canvas = FigureCanvasQTAgg(deepcopy(figure))
            canvas.setMinimumSize(140, 120)
            canvas.draw()
        except Exception as error:
            if canvas is not None:
                FigureCanvasBase(canvas.figure)
                canvas.deleteLater()
            self.window.status(tr("modern.preview_failed", error=error))
            return
        self.canvas = canvas
        self.plot.addWidget(canvas)

    def set_busy(self):
        if not self.enabled:
            return
        busy = self.window.job is not None
        run = self.run
        message = ""
        if run is None:
            message = tr("modern.no_graph")
        elif run.calculation_error:
            message = qt("qt.stale", error=run.calculation_error)
        elif self.canvas is None:
            if busy:
                message = tr("modern.calculating")
            elif self.result is None:
                message = tr("modern.not_calculated")
            else:
                message = tr("modern.preview_unavailable")
        self.notice.setText(message)
        self.notice.setVisible(bool(message))
        self.calculate.setVisible(run is None or self.result is None)
        self.calculate.setText(tr("modern.create_graph" if run is None else "modern.calculate"))
        self.calculate.setEnabled(not busy)
        self.choice.setEnabled(bool(self.graphs) and not busy)
        self.open_button.setEnabled(run is not None and not busy)
        self.format_box.setEnabled(not busy)
        for button in self.link_buttons.values():
            button.setEnabled(not busy and bool(button.menu().actions()))

    def _choose(self):
        if not self.window.settle_graph_draft():
            with QSignalBlocker(self.choice):
                self.choice.setCurrentIndex(self.choice.findData(self.run.uid))
            return
        self.refresh()

    def _open_graph(self):
        index = self.choice.currentIndex()
        if index >= 0:
            self._open_link(("graph", self.graphs[index][0]))

    def _open_link(self, ref):
        if not self.window.busy() and self.window.settle_graph_draft():
            self.window.open_sheet(ref)

    def _calculate(self):
        if self.window.busy():
            return
        if self.run is None:
            self.window.actions["new_graph"].trigger()
        else:
            self.window.refresh_runs([self.run])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.enabled and self.format_box.isChecked():
            self._fit_sidebar()

    def _fit_sidebar(self):
        wide = self.width() >= 700
        self.workspace.setOrientation(Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical)
        self.grid.setMinimumHeight(0 if wide else 285)
        self.sidebar.setMinimumHeight(0 if wide else 280)
        if wide and not self.sidebar.isVisible():
            self.workspace.setSizes([max(360, self.width() - 344), 344])

    def _toggle_format(self, shown):
        self._format(shown)
        if shown and self.workspace.orientation() == Qt.Orientation.Vertical:
            QTimer.singleShot(0, self, self._show_compact_inspector)

    def _show_compact_inspector(self):
        if self.enabled and self.sidebar.isVisible():
            self.scroll.ensureWidgetVisible(self.sidebar, 0, 0)

    def _format(self, shown):
        if shown:
            self._fit_sidebar()
        self.sidebar.setVisible(shown)
        if not shown:
            self.grid.setMinimumHeight(0)
            self._close_inspector()
            return
        dataset = self.project.tables[self.title]
        self.table_info.setText(f'{tr("modern.table_type")}: {ui(dataset.table_format)}\n'
                                f'{tr("modern.table_size", rows=len(dataset.raw), columns=len(dataset.raw.columns))}')
        problem = self.project.graph_format_problem(self.run) if self.run is not None else tr("modern.no_graph")
        self.format_note.setText(problem or "")
        self.format_note.setVisible(bool(problem))
        if self.canvas is None or self.inspector_area.count() or problem:
            return
        run, result = self.run, self.result

        def commit(style):
            if (self.window.job is not None or self.window.project is not self.project
                    or run.result is not result):
                raise ValueError(tr("modern.calculating"))
            figure = result.figure
            validate_graph_style(figure.axes[0], style)
            try:
                apply_style(figure, style)
            except ValueError:
                apply_style(figure, run.style or {})
                raise
            self.window.commit_style(run, style, project=self.project)

        inspector = GraphInspector(run, self.canvas, confirmed=lambda: run.style, commit=commit,
                                   closed=lambda: self.format_box.setChecked(False))
        self.window.inspector = inspector
        self.inspector_area.addWidget(inspector)

    def _close_inspector(self):
        if self.inspector_area.count():
            self.window.dispose_inspector()

    def release(self):
        self.run = self.result = self._style = None
        if self.canvas is None:
            return
        self._close_inspector()
        canvas, self.canvas = self.canvas, None
        self.plot.removeWidget(canvas)
        FigureCanvasBase(canvas.figure)
        canvas.hide()
        canvas.deleteLater()
