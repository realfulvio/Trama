"""Graph preview and formatting while the source worksheet stays open."""

from copy import deepcopy

from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QLabel, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from analisi.i18n import tr, ui
from analisi.presentation import apply_style, validate_graph_style

from .flow import FlowLayout
from .inspector import GraphInspector
from .strings import qt


class WorksheetPreview(QSplitter):
    """Keep the original figure and its canvas independent of the worksheet preview."""

    def __init__(self, window, title, sheet):
        super().__init__(Qt.Orientation.Horizontal)
        self.window, self.project, self.title = window, window.project, title
        self.enabled = False
        self.area = None
        self.canvas = None
        self.run = self.result = None
        self.graphs = ()
        self.grid = QSplitter(Qt.Orientation.Vertical)
        self.grid.addWidget(sheet)
        self.grid.setChildrenCollapsible(False)
        self.addWidget(self.grid)
        self.setChildrenCollapsible(False)

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
        self.format_box = QCheckBox(tr("modern.format"))
        self.format_box.toggled.connect(self._format)
        header.addWidget(self.format_box)
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
        self.addWidget(self.sidebar)
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 0)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if self.area is None:
            if not enabled:
                return
            self._build()
        self.area.setVisible(enabled)
        if enabled:
            self.refresh()
        else:
            self.sidebar.hide()
            self.release()

    def refresh(self):
        if not self.enabled:
            return
        graphs = tuple((index, self.project.runs[index].uid, name)
                       for name, (kind, index), _ in self.window.navigator_entries
                       if kind == "graph" and self.project.runs[index].title == self.title)
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
        if run is not self.run or result is not self.result:
            self.release()
            self.run, self.result = run, result
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

    def _choose(self):
        if not self.window.settle_graph_draft():
            with QSignalBlocker(self.choice):
                self.choice.setCurrentIndex(self.choice.findData(self.run.uid))
            return
        self.refresh()

    def _open_graph(self):
        index = self.choice.currentIndex()
        if index >= 0 and not self.window.busy() and self.window.settle_graph_draft():
            self.window.open_sheet(("graph", self.graphs[index][0]))

    def _calculate(self):
        if self.window.busy():
            return
        if self.run is None:
            self.window.actions["new_graph"].trigger()
        else:
            self.window.refresh_runs([self.run])

    def _format(self, shown):
        self.sidebar.setVisible(shown)
        if not shown:
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
        self.run = self.result = None
        if self.canvas is None:
            return
        self._close_inspector()
        canvas, self.canvas = self.canvas, None
        self.plot.removeWidget(canvas)
        FigureCanvasBase(canvas.figure)
        canvas.hide()
        canvas.deleteLater()
