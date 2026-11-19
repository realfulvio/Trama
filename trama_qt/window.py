"""The Trama main window on Qt: command bar, navigator, sheets and background calculations."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QStringListModel, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QCompleter, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QSplitter, QStackedWidget, QTabBar, QTabWidget, QToolBar,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from analisi._version import VERSION
from analisi.analysis_chain import ChainCancelled
from analisi.field_error import FieldError
from analisi.i18n import LANGUAGE_NAMES, config_path, save_language, tr, ui
from analisi.monte_carlo import MonteCarloCancelled
from analisi.prism_restore import SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT, SAVED_BINARY_RESULT
from analisi.text_import import TEXT_SUFFIXES
from analisi.workbench import GRAPH_METHODS, GROUPS

from . import theme
from .analysis_dialog import AnalysisDialog
from .flow import FlowLayout
from .labels import method_label
from .models import WorksheetModel, column_label
from .project import (DATA_SUFFIXES, OPEN_FILTER, PRISM_GRAPH_METHODS, PROJECT_SUFFIXES, CalculationControl, Project,
                      Run, compute, run_view, stored_prism_view)
from .sessions import MAX_PROJECT_TABS, Sessions
from .sheet import FrameView, WorksheetView
from .strings import qt

try:
    from analisi.roc import threshold_text
except Exception:  # pragma: no cover
    threshold_text = None

READ_ONLY_VIEWS = {SAVED_BINARY_GRAPH, SAVED_BINARY_RESULT, SAVED_BINARY_LAYOUT}
GRAPHING = tuple(GROUPS.get("Graphing", ())) + ("Plot a function",)


def preferred_view(run, result):
    """Graph methods open on their graph; analyses open on their tables (the graph is one click away)."""
    if run.method in GRAPH_METHODS or run.method in GRAPHING:
        return "graph"
    if result is not None and result.figure is not None and not result.tables:
        return "graph"
    return run_view(run.method)


def safe_csv(path, frame, index=False):
    """CSV for spreadsheets: text that looks like a formula is quoted, as in the classic export."""
    import pandas as pd

    def plain(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    data = frame.map(plain).rename(columns=plain)
    if index:
        labels = data.index
        if isinstance(labels, pd.MultiIndex):
            data.index = pd.MultiIndex.from_arrays(
                [[plain(value) for value in labels.get_level_values(level)] for level in range(labels.nlevels)],
                names=[plain(name) for name in labels.names])
        else:
            data.index = pd.Index([plain(str(value) if isinstance(value, tuple) else value) for value in labels],
                                  name=plain(labels.name), tupleize_cols=False)
    data.to_csv(path, index=index, encoding="utf-8-sig")


def export_graph(figure, path, settings=None):
    """A graph at its own size, 300 dpi for images unless ``settings`` say otherwise, verified before it
    replaces the file."""
    from analisi.figure_export import export_figure
    if settings is None:
        suffix = Path(path).suffix.lower()
        fmt = {".svg": "svg", ".pdf": "pdf", ".tif": "tiff", ".tiff": "tiff"}.get(suffix, "png")
        settings = {"format": fmt, "dpi": 300} if fmt in {"png", "tiff"} else {"format": fmt}
    export_figure(figure, path, settings)


_KEEP = object()  # ``_ask``: keep the input of the analysis.


class Job:
    def __init__(self, future, control, done, label, session=None):
        self.future, self.control, self.done, self.label = future, control, done, label
        self.session = session  # The project tab that started it: its results never reach another tab.


class Page(QWidget):
    """A sheet: title, subtitle, a row of actions and the content."""

    def __init__(self, title, subtitle=""):
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(20, 16, 20, 16)
        self.layout_.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setWordWrap(True)
        self.layout_.addWidget(heading)
        if subtitle:
            caption = QLabel(subtitle)
            caption.setObjectName("pageSubtitle")
            caption.setWordWrap(True)
            self.layout_.addWidget(caption)
        actions = QWidget()
        self.actions_row = FlowLayout(actions)  # Wraps on narrow windows instead of clipping the buttons.
        self.layout_.addWidget(actions)
        self.canvases = []

    def button(self, text, handler, *, primary=False, icon=None):
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        if icon:
            button.setIcon(theme.icon(icon, theme.T["on_accent"] if primary else None, 16))
        button.clicked.connect(handler)
        self.actions_row.addWidget(button)
        return button

    def notice(self, text, *, error=False):
        label = QLabel(text)
        label.setObjectName("errorBanner" if error else "notice")
        label.setWordWrap(True)
        self.layout_.addWidget(label)
        return label

    def add(self, widget, stretch=1):
        self.layout_.addWidget(widget, stretch)
        return widget

    def finish_actions(self):
        """The row wraps its buttons; nothing to close."""

    def release(self):
        """Detach matplotlib figures from the canvases that are about to be deleted."""
        for canvas in self.canvases:
            figure = canvas.figure
            if figure.canvas is canvas:
                FigureCanvasBase(figure)
        self.canvases.clear()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sessions = Sessions(Project())  # One per project tab; ``project`` and ``selected`` are the active one's.
        self.project_number = 1
        self._queued = []  # Files that arrived (drop, command line) while a calculation ran.
        self._close_pending = False
        self.page = None
        self.sheet = None
        self.result_tabs = None
        self.job = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Trama-Qt")
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._poll)
        self.actions = {}
        self.icons = {}
        self.inspector = None
        self.info_editor = None
        self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(str(theme.ASSETS / "trama.png")))
        self._build()
        self.refresh()
        self.show_home()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            self.resize(min(1280, screen.width() - 40), min(820, screen.height() - 60))
        else:
            self.resize(1180, 760)

    # == the active project tab ===================================================================
    # The window works on the active session; switching tabs swaps these without copying any data.
    @property
    def project(self):
        return self.sessions.active.project

    @project.setter
    def project(self, project):
        self.sessions.active.project = project

    @property
    def selected(self):
        return self.sessions.active.selected

    @selected.setter
    def selected(self, ref):
        self.sessions.active.selected = ref

    @property
    def inspector_wanted(self):
        return self.sessions.active.inspector_wanted

    @inspector_wanted.setter
    def inspector_wanted(self, wanted):
        self.sessions.active.inspector_wanted = wanted

    @property
    def inspector_element(self):
        return self.sessions.active.inspector_element

    @inspector_element.setter
    def inspector_element(self, element):
        self.sessions.active.inspector_element = element

    # == construction =============================================================================
    def _action(self, key, text, handler, *, icon=None, shortcut=None, tip=None):
        action = QAction(text, self)
        if icon:
            action.setIcon(theme.icon(icon))
            self.icons[key] = icon
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        action.triggered.connect(lambda _checked=False: handler())
        self.addAction(action)
        self.actions[key] = action
        return action

    def _build(self):
        a = self._action
        a("new_project", tr("command.new_project"), self.new_project, icon="plus", shortcut="Ctrl+N")
        a("open", tr("command.open"), self.open_dialog, icon="folder-open", shortcut="Ctrl+O")
        a("close_project", tr("command.close_project"), self.close_project, icon="x", shortcut="Ctrl+W",
          tip=qt("qt.close_project_hint"))
        self.actions["close_project"].setShortcuts([QKeySequence("Ctrl+W"), QKeySequence("Ctrl+F4")])
        a("next_project", qt("qt.next_project"), lambda: self.step_project(1), shortcut="Ctrl+Tab")
        a("previous_project", qt("qt.previous_project"), lambda: self.step_project(-1), shortcut="Ctrl+Shift+Tab")
        self.actions["previous_project"].setShortcuts([QKeySequence("Ctrl+Shift+Tab"),
                                                       QKeySequence("Ctrl+Shift+Backtab")])
        a("import", tr("command.import_into_project"), lambda: self.open_dialog(import_data=True), icon="file-up",
          shortcut="Ctrl+I")
        a("save", tr("command.save_project"), self.save, icon="save", shortcut="Ctrl+S")
        a("save_as", tr("command.save_project_as"), lambda: self.save(as_new=True), shortcut="Ctrl+Shift+S")
        a("export", tr("command.export"), self.export, icon="upload", shortcut="Ctrl+E")
        a("export_options", tr("command.export_with_options"), self.export_with_options, icon="download")
        a("export_pdf", tr("command.export_multiple_pdf"), self.export_pdf_bundle, icon="file-down")
        a("classic", qt("qt.classic"), self.open_classic, icon="history", tip=qt("qt.classic_hint"))
        a("language", tr("command.language"), self.choose_language, icon="type")
        a("about", qt("qt.about"), self.about, icon="info")
        a("exit", tr("command.exit"), self.close, shortcut="Ctrl+Q")
        a("undo", tr("command.undo"), self.undo, icon="undo-2", shortcut="Ctrl+Z")
        a("redo", tr("command.redo"), lambda: self.undo(redo=True), icon="redo-2", shortcut="Ctrl+Y")
        a("cut", tr("command.cut_cells"), lambda: self._sheet_call("cut"), icon="scissors")
        a("copy", tr("command.copy_cells"), lambda: self._sheet_call("copy"), icon="copy")
        a("paste", tr("ribbon.paste"), lambda: self._sheet_call("paste"), icon="clipboard-paste")
        a("new_table", tr("command.new_table"), self.new_table, icon="table", shortcut="Ctrl+T")
        a("new_info", tr("command.new_info"), self.new_info, icon="info")
        a("duplicate_family", ui("Duplicate family…"), self.duplicate_family, icon="copy")
        a("save_family", ui("Save family as…"), self.save_family_as, icon="save")
        a("insert_row", qt("qt.insert_row"), self.insert_row, icon="rows-3")
        a("insert_column", qt("qt.insert_column"), self.insert_column, icon="columns-3")
        a("formula", ui("Formula…"), self.edit_formula, icon="sigma")
        a("delete_rows", qt("qt.delete_rows"), self.delete_rows, icon="trash-2")
        a("exclude", tr("ribbon.exclude"), self.toggle_exclusion, icon="filter")
        a("analyze", tr("ribbon.analyze"), self.analyze, icon="sigma", shortcut="Ctrl+Shift+A")
        a("new_graph", tr("command.new_graph"), self.new_graph, icon="chart-line", shortcut="Ctrl+G")
        a("change", tr("command.change_parameters"), self.change_parameters, icon="sliders-horizontal",
          shortcut="Ctrl+P")
        a("format_graph", tr("graph.format.title"), self.format_graph, icon="palette", shortcut="Ctrl+Shift+F")
        a("inspector", tr("graph.inspector.title"), self.toggle_inspector, icon="paintbrush", shortcut="Ctrl+Shift+I")
        a("annotations", tr("command.graph_annotations"), self.edit_annotations, icon="type")
        a("shapes", tr("shape.button"), self.edit_shapes, icon="shapes")
        a("pairwise", tr("command.pairwise"), self.pairwise_comparisons, icon="git-compare")
        a("compact_letters", tr("command.compact_letters"), lambda: self.pairwise_comparisons(letters=True),
          icon="type")
        a("new_layout", tr("command.new_layout"), self.new_layout, icon="layout-grid", shortcut="Ctrl+L")
        a("edit_layout", tr("command.edit_layout"), lambda: self.new_layout(edit=True), icon="layout-grid")
        a("recalculate", qt("qt.recalculate"), self.recalculate, icon="history", shortcut="F9")
        a("use_result", qt("qt.use_as_data"), self.use_result_as_data, icon="table-2")
        a("analyze_result", tr("chain.analyze_result"), self.analyze_result_table, icon="git-compare")
        a("source_analysis", tr("chain.source_analysis"), self.source_analysis, icon="chevron-up")
        a("change_input", tr("chain.change_input"), self.change_input_result, icon="arrow-up-down")
        a("navigator", tr("command.toggle_navigator"), self.toggle_navigator, icon="panel-bottom", shortcut="Ctrl+F1")
        a("search", qt("qt.search"), self.focus_search, shortcut="Ctrl+K")
        for name, method in (("descriptive", "Descriptive statistics"), ("ttest", "t-test"),
                             ("anova", "One-way ANOVA"), ("correlation", "Correlation"),
                             ("linear", "Linear regression"), ("nonlinear", "Nonlinear regression"),
                             ("survival", "Kaplan–Meier survival"), ("contingency", "Contingency table")):
            a(name, method_label(method), lambda method=method: self.analyze(method=method))

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._project_strip())
        root.addWidget(self._command_bar())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setContentsMargins(10, 10, 10, 6)
        body.setHandleWidth(10)
        nav_card = QFrame()
        nav_card.setObjectName("card")
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(8, 10, 8, 10)
        self.navigator = QTreeWidget()
        self.navigator.setObjectName("navigator")
        self.navigator.setHeaderHidden(True)
        self.navigator.setRootIsDecorated(False)
        self.navigator.setIndentation(8)
        self.navigator.setIconSize(theme.icon_size(16))
        self.navigator.itemClicked.connect(self._navigate)
        self.navigator.itemActivated.connect(self._navigate)
        self.navigator.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.navigator.customContextMenuRequested.connect(self._navigator_menu)
        nav_layout.addWidget(self.navigator)
        self.nav_card = nav_card
        body.addWidget(nav_card)
        page_card = QFrame()
        page_card.setObjectName("card")
        self.page_layout = QVBoxLayout(page_card)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        body.addWidget(page_card)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([250, 900])
        root.addWidget(body, 1)
        self.setCentralWidget(central)

        status = self.statusBar()
        status.setSizeGripEnabled(True)
        self.message = QLabel(qt("qt.ready"))
        status.addWidget(self.message, 1)
        self.cell_label = QLabel("")
        status.addPermanentWidget(self.cell_label)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(140)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        status.addPermanentWidget(self.progress)
        self.cancel_button = QToolButton()
        self.cancel_button.setText(tr("bar.cancel_calculation"))
        self.cancel_button.clicked.connect(self.cancel_calculation)
        self.cancel_button.setVisible(False)
        status.addPermanentWidget(self.cancel_button)
        engine = QLabel(f"PySide6 {PYSIDE_VERSION} · Trama {VERSION}")
        engine.setObjectName("muted")
        status.addPermanentWidget(engine)

    def _project_strip(self):
        """One tab per open project, with New beside the last tab; each tab closes its own project."""
        strip = QFrame()
        strip.setObjectName("projectStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(10, 4, 10, 0)
        row.setSpacing(2)
        tabs = self.project_tabs = QTabBar()
        tabs.setObjectName("projectTabs")
        tabs.setAccessibleName(qt("qt.projects"))
        tabs.setDrawBase(False)
        tabs.setExpanding(False)
        tabs.setMovable(False)
        tabs.setTabsClosable(True)
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        tabs.addTab("")
        tabs.currentChanged.connect(self._project_tab_changed)
        tabs.tabCloseRequested.connect(self._project_tab_close)
        row.addWidget(tabs)
        self.new_tab_button = QToolButton()
        self.new_tab_button.setObjectName("newProjectTab")
        self.new_tab_button.setIcon(theme.icon("plus", theme.T["text2"], 16))
        self.new_tab_button.setToolTip(qt("qt.new_project_hint"))
        self.new_tab_button.setAccessibleName(tr("command.new_project"))
        self.new_tab_button.setAutoRaise(True)
        self.new_tab_button.clicked.connect(self.new_project)
        row.addWidget(self.new_tab_button)
        row.addStretch(1)
        return strip

    def _command_bar(self):
        bar = QFrame()
        bar.setObjectName("commandBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 6)
        layout.setSpacing(2)
        top = QHBoxLayout()
        self.ribbon_tabs = QTabBar()
        self.ribbon_tabs.setObjectName("ribbonTabs")
        self.ribbon_tabs.setDrawBase(False)
        self.ribbon_tabs.setExpanding(False)
        top.addWidget(self.ribbon_tabs)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(qt("qt.search"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self.search.addAction(theme.icon("search", theme.T["text3"], 16), QLineEdit.ActionPosition.LeadingPosition)
        self.completer = QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.activated.connect(self._run_search)
        self.search.setCompleter(self.completer)
        self.search.returnPressed.connect(lambda: self._run_search(self.search.text()))
        top.addWidget(self.search)
        layout.addLayout(top)
        self.ribbon = QStackedWidget()
        groups = [
            (tr("ribbon.modern.file"), ["new_project", "open", "import", "save", "save_as", "close_project", "|",
                                         "export", "export_options",
                                         "export_pdf", "|",
                                         "classic", "language", "about"]),
            (tr("ribbon.modern.home"), ["paste", "cut", "copy", "|", "undo", "redo", "|", "new_table", "insert_row",
                                         "insert_column", "formula", "exclude", "|", "*analyze", "new_graph", "|", "recalculate",
                                         "export", "|", "new_info", "duplicate_family", "save_family"]),
            (tr("ribbon.modern.analyze"), ["*analyze", "|", "descriptive", "ttest", "anova", "correlation", "linear",
                                            "nonlinear", "survival", "contingency", "|", "change", "recalculate",
                                            "use_result", "|", "analyze_result", "source_analysis",
                                            "change_input"]),
            (tr("ribbon.modern.graph"), ["*new_graph", "|", "inspector", "format_graph", "annotations", "shapes",
                                          "pairwise", "compact_letters", "change", "recalculate", "|", "new_layout",
                                          "edit_layout", "|", "export", "export_options"]),
            (tr("ribbon.modern.view"), ["navigator", "|", "language", "classic"]),
        ]
        for title, keys in groups:
            self.ribbon_tabs.addTab(title)
            row = QToolBar(title, self.ribbon)
            row.setObjectName("commandTools")
            row.setMovable(False)
            row.setIconSize(theme.icon_size(18))
            row.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            for key in keys:
                if key == "|":
                    row.addSeparator()
                else:
                    action = self.actions[key.lstrip("*")]
                    row.addAction(action)
                    if key.startswith("*"):
                        button = row.widgetForAction(action)
                        button.setObjectName("primary")
                        button.setIcon(theme.icon(self.icons.get(key[1:], "sigma"), theme.T["on_accent"]))
            self.ribbon.addWidget(row)
        self.ribbon_tabs.currentChanged.connect(self.ribbon.setCurrentIndex)
        self.ribbon_tabs.setCurrentIndex(1)
        layout.addWidget(self.ribbon)
        names = [action.text().replace("&", "") for action in self.actions.values() if action.text()]
        self.completer.setModel(QStringListModel(sorted(set(names)), self))
        return bar

    # == small helpers ============================================================================
    def error(self, error):
        QMessageBox.warning(self, "Trama", str(error))

    def status(self, text):
        self.message.setText(str(text))

    def busy(self, *, warn=True):
        if self.job is not None and warn:
            self.status(qt("qt.wait"))
        return self.job is not None

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _run_search(self, text):
        text = (text or "").strip().casefold()
        for action in self.actions.values():
            if action.text().replace("&", "").casefold() == text and action.isEnabled():
                self.search.clear()
                action.trigger()
                return

    def _sheet_call(self, name):
        if self.sheet is not None:
            getattr(self.sheet, name)()

    def toggle_navigator(self):
        self.nav_card.setVisible(not self.nav_card.isVisible())

    def update_title(self):
        title = self.project.title
        if self.selected and self.selected[0] == "data":
            title = f"{self.selected[1]} — {title}"
        marker = "• " if self.project.dirty else ""
        self.setWindowTitle(f"{marker}{title} — Trama")
        self._sync_tabs()

    def _sync_tabs(self):
        """The tab strip as the sessions are: one tab each, captions with the dirty marker, the active one current."""
        bar = getattr(self, "project_tabs", None)
        if bar is None:
            return
        bar.blockSignals(True)
        try:
            while bar.count() > len(self.sessions):
                bar.removeTab(bar.count() - 1)
            while bar.count() < len(self.sessions):
                bar.addTab("")
            for index, (caption, tip) in enumerate(self.sessions.labels()):
                if bar.tabText(index) != caption:
                    bar.setTabText(index, caption)
                bar.setTabToolTip(index, tip)
                bar.setTabData(index, self.sessions[index].key)
            bar.setCurrentIndex(self.sessions.index(self.sessions.active))
        finally:
            bar.blockSignals(False)

    def update_actions(self):
        kind = self.selected[0] if self.selected else None
        on_run = kind in {"result", "graph", "saved-layout"}
        data = kind == "data"
        editable = data and not stored_prism_view(self.project.tables[self.selected[1]])
        idle = self.job is None
        for key in ("cut", "paste", "insert_row", "insert_column", "delete_rows", "exclude", "formula"):
            self.actions[key].setEnabled(editable and idle)
        self.actions["copy"].setEnabled(data)
        for key in ("duplicate_family", "save_family"):
            self.actions[key].setEnabled(kind is not None and idle)
        self.actions["change"].setEnabled(on_run and idle)
        graph = kind == "graph" and self.project.graph_format_problem(self.project.runs[self.selected[1]]) is None
        self.actions["format_graph"].setEnabled(graph and idle)
        self.actions["inspector"].setEnabled(graph and idle)
        self.actions["annotations"].setEnabled(graph and idle and self.project.runs[self.selected[1]].method
                                               not in PRISM_GRAPH_METHODS)
        self.actions["shapes"].setEnabled(self.actions["annotations"].isEnabled())
        for key in ("pairwise", "compact_letters"):
            self.actions[key].setEnabled(graph and idle)
        if self.inspector is not None:
            self.inspector.setEnabled(idle)
        self.actions["new_layout"].setEnabled(idle and bool(self.project.layout_candidates()))
        self.actions["edit_layout"].setEnabled(idle and kind == "layout")
        self.actions["recalculate"].setEnabled((on_run or kind == "layout") and idle)
        self.actions["use_result"].setEnabled(kind == "result" and idle)
        chained = kind in {"result", "graph"} and self.project.runs[self.selected[1]].source is not None
        self.actions["analyze_result"].setEnabled(kind == "result" and idle)
        self.actions["source_analysis"].setEnabled(chained)
        self.actions["change_input"].setEnabled(idle and (kind == "result" or chained))
        has_data = bool(self.project.tables)
        for key in ("analyze", "new_graph", "descriptive", "ttest", "anova", "correlation", "linear", "nonlinear",
                    "survival", "contingency"):
            self.actions[key].setEnabled(has_data and idle)
        self.actions["undo"].setEnabled(idle and self.project.history.can_apply())
        self.actions["redo"].setEnabled(idle and self.project.history.can_apply(redo=True))
        for key in ("open", "import", "new_project", "save", "save_as", "classic", "close_project"):
            self.actions[key].setEnabled(idle)
        for key in ("next_project", "previous_project"):  # Switching waits for the calculation (Cancel stays on).
            self.actions[key].setEnabled(idle and len(self.sessions) > 1)
        self.actions["new_project"].setEnabled(idle and not self.sessions.full())
        self.project_tabs.setEnabled(idle)
        self.new_tab_button.setEnabled(idle and not self.sessions.full())
        self.actions["export"].setEnabled(kind is not None)
        self.actions["export_options"].setEnabled(kind in {"graph", "layout", "saved-layout"})
        self.actions["export_pdf"].setEnabled(idle and (bool(self.project.layouts) or any(
            run.result is not None and run.result.figure is not None for run in self.project.runs)))

    # == navigator ================================================================================
    def _section(self, title):
        item = QTreeWidgetItem([title])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setForeground(0, theme.color("text2"))
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self.navigator.addTopLevelItem(item)
        return item

    def _entry(self, section, text, ref, icon):
        item = QTreeWidgetItem([text])
        item.setData(0, Qt.ItemDataRole.UserRole, ref)
        item.setIcon(0, theme.icon(icon, theme.T["text2"], 16))
        item.setToolTip(0, text)
        section.addChild(item)
        if ref == self.selected:
            self.navigator.setCurrentItem(item)
        return item

    def refresh(self):
        """Rebuild the navigator and the window state after any change of the project."""
        project = self.project
        self.navigator.blockSignals(True)
        self.navigator.clear()
        tables = self._section(tr("nav.data_tables"))
        for title in project.tables:
            self._entry(tables, title, ("data", title), "table")
        if project.info_sheets:
            info = self._section(tr("nav.info"))
            for uid, sheet in project.info_sheets.items():
                self._entry(info, sheet.title, ("info", uid), "info")
        results = [(index, run) for index, run in enumerate(project.runs)
                   if run_view(run.method) == "result" and preferred_view(run, run.result) == "result"]
        graphs = [(index, run) for index, run in enumerate(project.runs)
                  if run_view(run.method) == "graph" or run.method in GRAPH_METHODS
                  or (run.result is not None and run.result.figure is not None
                      and run_view(run.method) == "result")]
        layouts = [(index, run) for index, run in enumerate(project.runs) if run_view(run.method) == "saved-layout"]
        if results:
            section = self._section(tr("nav.results"))
            items = {}
            for index, run in self._chain_order(results):  # Linked analyses nest under their source.
                marker = " ⚠" if run.calculation_error else ""
                owner = items.get(run.source.analysis_id, section) if run.source is not None else section
                items[run.uid] = self._entry(owner, run.name + marker, ("result", index), "sigma")
        if graphs:
            section = self._section(tr("nav.graphs"))
            for index, run in graphs:
                marker = " ⚠" if run.calculation_error else ""
                self._entry(section, run.name + marker, ("graph", index), "chart-line")
        if project.layouts or layouts:
            section = self._section(tr("nav.layouts"))
            for index, layout in enumerate(project.layouts):
                self._entry(section, layout.name, ("layout", index), "layout-grid")
            for index, run in layouts:
                self._entry(section, run.name, ("saved-layout", index), "layout-grid")
        self.navigator.expandAll()
        self.navigator.blockSignals(False)
        self.update_title()
        self.update_actions()

    def _chain_order(self, entries):
        """``entries`` with every source analysis before the analyses that read its results."""
        try:
            order = {uid: position for position, uid in enumerate(self.project.analysis_graph().order)}
        except ValueError:
            return entries
        return sorted(entries, key=lambda entry: order.get(entry[1].uid, len(order)))

    def _navigate(self, item, _column=0):
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if ref:
            self.open_sheet(tuple(ref))

    def _navigator_menu(self, position):
        item = self.navigator.itemAt(position)
        ref = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        menu = QMenu(self)
        if ref and ref[0] in {"result", "graph"}:
            self.open_sheet(tuple(ref))
            menu.addAction(self.actions["change"])
            menu.addAction(self.actions["recalculate"])
            for key in ("analyze_result", "source_analysis", "change_input"):
                if self.actions[key].isEnabled():
                    menu.addAction(self.actions[key])
        if ref and ref[0] == "data":
            self.open_sheet(tuple(ref))
            menu.addAction(self.actions["analyze"])
            menu.addAction(self.actions["new_graph"])
        menu.addAction(self.actions["new_table"])
        if ref:
            menu.addSeparator()
            menu.addAction(self.actions["duplicate_family"])
            menu.addAction(self.actions["save_family"])
        menu.exec(self.navigator.viewport().mapToGlobal(position))

    # == pages ====================================================================================
    def _replace_page(self, page):
        if self.page is not None:
            self.page.release()
            self.page_layout.removeWidget(self.page)
            self.page.hide()
            self.page.setParent(None)
            self.page.deleteLater()
        self.page = page
        self.page_layout.addWidget(page)

    def show_home(self):
        self.dispose_inspector()
        self.flush_info()
        self.info_editor = None
        self.selected = None
        self.sheet = None
        page = Page("Trama", tr("status.welcome"))
        page.button(tr("command.open"), self.open_dialog, primary=True, icon="folder-open")
        page.button(tr("command.new_table"), self.new_table, icon="table")
        page.button(tr("command.import_into_project"), lambda: self.open_dialog(import_data=True), icon="file-up")
        page.finish_actions()
        hint = QLabel(qt("qt.classic_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        page.add(hint, 0)
        page.layout_.addStretch(1)
        self._replace_page(page)
        self.update_title()
        self.update_actions()

    def open_sheet(self, ref):
        kind, key = ref
        self.show_sheet(kind, key)
        if kind in {"result", "graph", "saved-layout"} and self.project.runs[key].result is None and self.job is None:
            self.refresh_runs([self.project.runs[key]])
        elif kind == "layout" and self.job is None:
            runs = [run for run in self.project.layout_runs(self.project.layouts[key]) if run.result is None]
            if runs:
                self.refresh_runs(runs)

    def show_sheet(self, kind, key):
        self.dispose_inspector()  # Before the new page builds its own panel.
        self.flush_info()
        self.info_editor = None
        self.selected = (kind, key)
        self.sheet = None
        self.result_tabs = None
        if kind == "data":
            page = self._data_page(key)
        elif kind == "info":
            page = self._info_page(key)
        elif kind == "layout":
            page = self._layout_page(key)
        else:
            page = self._run_page(kind, key)
        self._replace_page(page)
        self.refresh()
        if self.sheet is not None:
            self.sheet.setFocus()

    def reshow(self):
        if self.selected is None:
            self.show_home()
        elif self.selected[0] == "data" and self.sheet is not None:
            current = self.sheet.currentIndex()
            self.sheet.model().reload()
            if current.isValid():
                self.sheet.setCurrentIndex(self.sheet.model().index(current.row(), current.column()))
            self.refresh()
        else:
            self.show_sheet(*self.selected)

    def _data_page(self, title):
        dataset = self.project.tables[title]
        frame = dataset.raw
        subtitle = qt("qt.rows_columns", rows=len(frame), columns=len(frame.columns) + len(dataset.formulas))
        page = Page(title, f"{dataset.table_format} · {subtitle}")
        read_only = stored_prism_view(dataset)
        page.button(tr("ribbon.analyze"), self.analyze, primary=True, icon="sigma")
        page.button(tr("command.new_graph"), self.new_graph, icon="chart-line")
        linked = [(index, run) for index, run in enumerate(self.project.runs) if run.title == title]
        if linked:
            menu = QMenu(page)
            for index, run in linked:
                menu.addAction(run.name, lambda index=index, run=run: self.open_sheet((preferred_view(run, run.result), index)))
            more = QPushButton(f"{tr('bar.linked_sheets')} ({len(linked)})")
            more.setMenu(menu)
            page.actions_row.addWidget(more)
        page.finish_actions()
        if read_only:
            page.notice(qt("qt.read_only"))
        project = self.project  # Typing reaches this project only, even if it lands after a tab switch.
        model = WorksheetModel(dataset, lambda row, column, text: self.edit_cell(title, row, column, text,
                                                                                 project=project),
                               read_only=read_only)
        self.sheet = page.add(WorksheetView(model, self))
        self.sheet.setCurrentIndex(model.index(0, 0))
        return page

    def _info_page(self, uid):
        from .info_editor import InfoEditor, t
        sheet = self.project.info_sheets[uid]
        page = Page(sheet.title, tr("interface.linked_to", table=sheet.table) if sheet.table else tr("nav.info"))
        page.button(t("Properties…"), self.info_properties, icon="pencil")
        page.button(t("Move sheet up"), lambda: self.move_info(-1), icon="chevron-up")
        page.button(t("Move sheet down"), lambda: self.move_info(1), icon="chevron-down")
        page.button(t("Delete Info sheet…"), self.remove_info, icon="trash-2")
        page.finish_actions()
        project = self.project
        self.info_editor = page.add(InfoEditor(
            sheet, lambda revised: self.change_info(revised) if project is self.project else False, self.error))
        return page

    def flush_info(self):
        if getattr(self, "info_editor", None) is not None:
            editor, self.info_editor = self.info_editor, None
            editor.flush()
            self.info_editor = editor

    def change_info(self, sheet):
        """Store an edit of the open Info sheet; constants read by formulas recalculate their tables."""
        if self.job is not None and (sheet.table, sheet.fields) != (self.project.info_sheets[sheet.uid].table,
                                                                    self.project.info_sheets[sheet.uid].fields):
            self.error(tr("family.wait").split(".")[0] + ".")
            return False
        title = self.project.info_sheets[sheet.uid].title
        try:
            stale = self.project.change_info(sheet)
        except (ValueError, OverflowError) as error:
            self.error(error)
            return False
        if sheet.title != title:
            self.refresh()
        else:
            self.update_title()
        self.refresh_runs([run for run in stale if run.result is not None])
        return True

    def _info_tables(self):
        return [name for name, dataset in self.project.tables.items() if not stored_prism_view(dataset)]

    def new_info(self):
        from analisi.info import MAX_INFO_SHEETS, InfoSheet
        from .info_editor import InfoDetails
        if self.busy():
            return
        if len(self.project.info_sheets) >= MAX_INFO_SHEETS:
            self.error(ui("A project supports up to 500 Info sheets."))
            return
        self.flush_info()
        active = self.selected[1] if self.selected and self.selected[0] == "data" else None
        dialog = InfoDetails(self, f"Project info {len(self.project.info_sheets) + 1}", active, self._info_tables(),
                             creating=True)
        if dialog.exec() != InfoDetails.DialogCode.Accepted or dialog.result is None:
            return
        sheet = InfoSheet.new(*dialog.result)
        try:
            stale = self.project.update_info_sheets({**self.project.info_sheets, sheet.uid: sheet})
        except (ValueError, OverflowError) as error:
            self.error(error)
            return
        self.show_sheet("info", sheet.uid)
        self.refresh_runs([run for run in stale if run.result is not None])

    def info_properties(self):
        from .info_editor import InfoDetails
        if not self.selected or self.selected[0] != "info":
            return
        self.flush_info()
        sheet = self.project.info_sheets[self.selected[1]]
        dialog = InfoDetails(self, sheet.title, sheet.table, self._info_tables())
        if dialog.exec() != InfoDetails.DialogCode.Accepted or dialog.result is None:
            return
        title, table = dialog.result
        if self.info_editor.commit(title=title, table=table):
            self.show_sheet("info", sheet.uid)

    def move_info(self, step):
        if self.selected and self.selected[0] == "info":
            self.flush_info()
            self.project.move_info(self.selected[1], step)
            self.refresh()

    def remove_info(self):
        if self.busy() or not self.selected or self.selected[0] != "info":
            return
        uid = self.selected[1]
        sheet = self.project.info_sheets[uid]
        from .info_editor import t
        answer = QMessageBox.question(self, t("Delete Info sheet…").rstrip("…"), ui(f'Delete "{sheet.title}"?'))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.flush_info()
        try:
            stale = self.project.update_info_sheets({key: value for key, value in self.project.info_sheets.items()
                                                     if key != uid})
        except (ValueError, OverflowError) as error:
            self.error(error)
            return
        self.info_editor = None
        self.show_home() if not self.project.tables else self.show_sheet("data", next(iter(self.project.tables)))
        self.refresh_runs([run for run in stale if run.result is not None])

    def _canvas(self, page, figure, *, toolbar=True, run=None):
        canvas = FigureCanvasQTAgg(figure)
        canvas.setMinimumSize(200, 160)
        page.canvases.append(canvas)
        if toolbar:
            tools = NavigationToolbar2QT(canvas, page)
            tools.setIconSize(theme.icon_size(18))
            page.add(tools, 0)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(canvas, 1)
        page.add(row, 1)
        if run is not None and self.inspector_wanted and self.project.graph_format_problem(run) is None:
            self._open_inspector(run, canvas, line)
        canvas.draw_idle()
        return canvas

    # == inspector =================================================================================
    def _open_inspector(self, run, canvas, line):
        from .inspector import GraphInspector

        def closed():
            self.inspector_wanted = False
            self.dispose_inspector()

        project = self.project
        self.inspector = GraphInspector(run, canvas, confirmed=lambda: run.style,
                                        commit=lambda style: self.commit_style(run, style, project=project),
                                        closed=closed, element=self.inspector_element)
        line.addWidget(self.inspector)

    def dispose_inspector(self):
        inspector, self.inspector = self.inspector, None
        if inspector is not None:
            self.inspector_element = inspector._element_key
            inspector.dispose()
            inspector.hide()
            inspector.setParent(None)
            inspector.deleteLater()
            if self.page is not None:
                for canvas in self.page.canvases:
                    canvas.draw_idle()

    def toggle_inspector(self):
        if self.inspector is not None:
            self.inspector.cancel()
            return
        if self.busy() or not self.selected or self.selected[0] != "graph":
            return
        problem = self.project.graph_format_problem(self.project.runs[self.selected[1]])
        if problem:
            self.error(problem)
            return
        self.inspector_wanted = True
        self.show_sheet(*self.selected)
        if self.inspector is not None:
            self.inspector.selector.setFocus()

    def commit_style(self, run, style, project=None):
        project = self.project if project is None else project  # The run's own project, never another tab's.
        project.commit_style(run, style)
        if project is self.project:
            self.update_title()
            self.status(qt("qt.style_applied"))
        else:
            self._sync_tabs()

    def settle_graph_draft(self):
        """Before leaving the drawn style behind: apply or discard an Inspector draft, or stay."""
        inspector = self.inspector
        if inspector is None or not inspector.has_draft:
            return True
        answer = QMessageBox.question(
            self, tr("graph.inspector.title"), qt("qt.inspector_draft"),
            QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Apply:
            return inspector.apply()
        if answer == QMessageBox.StandardButton.Discard:
            inspector.discard()
            return True
        return False

    def _layout_page(self, index):
        layout = self.project.layouts[index]
        page = Page(layout.name, tr("interface.layout_panels", count=len(layout.panels)))
        page.button(tr("command.edit_layout"), lambda: self.new_layout(edit=True), primary=True, icon="layout-grid")
        page.button(tr("command.export"), self.export, icon="upload")
        page.button(qt("qt.recalculate"), self.recalculate, icon="history")
        page.finish_actions()
        self._stale(page, self.project.layout_runs(layout))
        figure = self.project.layout_figure(layout)
        if figure is None:
            page.notice(qt("qt.layout_missing"))
            page.layout_.addStretch(1)
        else:
            self.layout_figure = figure
            self._canvas(page, figure)
        return page

    def _stale(self, page, runs):
        failures = [run.calculation_error for run in runs if run.calculation_error]
        if failures:
            page.notice(qt("qt.stale", error="; ".join(dict.fromkeys(failures))))

    def _run_page(self, kind, index):
        run = self.project.runs[index]
        subtitle = run.notes or (tr("command.analysis_results") if kind == "result" else tr("ribbon.graph"))
        page = Page(run.name, subtitle)
        result = run.result
        editable = run.method not in READ_ONLY_VIEWS
        if editable and kind != "saved-layout":
            page.button(tr("command.change_parameters"), self.change_parameters, icon="sliders-horizontal")
        page.button(qt("qt.recalculate"), self.recalculate, icon="history")
        if kind == "result" and result is not None:
            page.button(qt("qt.use_as_data"), self.use_result_as_data, icon="table-2")
            page.button(tr("chain.analyze_result"), self.analyze_result_table, icon="git-compare")
            page.button(qt("qt.export_table"), self.export, icon="upload")
        elif result is not None:
            if kind == "graph" and self.project.graph_format_problem(run) is None:
                page.button(tr("graph.inspector.title"), self.toggle_inspector, primary=True, icon="paintbrush")
                page.button(tr("graph.format.title"), self.format_graph, icon="palette")
            page.button(qt("qt.export_graph"), self.export, icon="upload")
        if kind == "result" and result is not None and result.figure is not None:
            page.button(tr("ribbon.graph"), lambda: self.open_sheet(("graph", index)), icon="chart-line")
        if kind == "graph" and run_view(run.method) == "result":
            page.button(tr("command.analysis_results"), lambda: self.open_sheet(("result", index)), icon="sigma")
        if run.source is not None:
            page.button(tr("chain.source_analysis"), self.source_analysis, icon="chevron-up")
        if kind == "result" or run.source is not None:
            page.button(tr("chain.change_input"), self.change_input_result, icon="arrow-up-down")
        page.finish_actions()
        if run.source is not None:
            source = next((other for other in self.project.runs if other.uid == run.source.analysis_id), None)
            name = source.name if source is not None else tr("chain.missing_source")
            caption = QLabel(tr("chain.input_label", analysis=name, table=run.source.table))
            caption.setObjectName("muted")
            caption.setWordWrap(True)
            page.add(caption, 0)
        self._stale(page, [run])
        if result is None:
            text = qt("qt.running", method=method_label(run.method)) if self.job is not None else qt("qt.not_calculated")
            page.notice(text)
            page.layout_.addStretch(1)
            return page
        if result.style_warning:
            page.notice(result.style_warning)
        if kind == "result":
            self.result_tabs = QTabWidget()
            self.result_tabs.setDocumentMode(True)
            for title, frame in result.tables.items():
                formatters = ({"Threshold": threshold_text} if threshold_text and run.method == "ROC curve"
                              and title == "Diagnostic thresholds" else None)
                self.result_tabs.addTab(FrameView(frame, formatters), str(title))
            page.add(self.result_tabs, 1)
        elif result.figure is not None:
            try:
                from analisi.pairwise_graph import pairwise_warning
                warning = pairwise_warning(result.figure)
            except Exception:  # pragma: no cover
                warning = None
            if warning:
                page.notice(warning)
            self._canvas(page, result.figure, run=run if kind == "graph" else None)
        else:
            page.notice(qt("qt.not_calculated"))
            page.layout_.addStretch(1)
        return page

    # == worksheet editing =======================================================================
    def cell_changed(self, current):
        if current.isValid():
            self.cell_label.setText(qt("qt.cell", address=f"{column_label(current.column())}{current.row() + 1}"))

    def _active_table(self):
        if not self.selected or self.selected[0] != "data":
            self.error(qt("qt.no_table"))
            return None
        if self.busy():
            if self.sheet is not None:
                self.sheet.model().reload()
            return None
        return self.selected[1]

    def _apply_edit(self, title, change):
        try:
            affected = change()
        except (ValueError, TypeError, OverflowError) as error:
            if self.sheet is not None:
                self.sheet.model().reload()
            self.error(error)
            return
        if affected is None:
            return
        self.reshow()
        if affected:
            self.refresh_runs(affected)
        else:
            self.status(qt("qt.edited"))

    def edit_cell(self, title, row, column, text, project=None):
        if project is not None and project is not self.project:  # Typed in a tab that is no longer active.
            self.status(qt("qt.edit_elsewhere"))
            return False
        if self._active_table() != title:
            return False
        self._apply_edit(title, lambda: self.project.paste(title, row, column, [[text]], "Edit cell"))
        return True

    def paste_cells(self, row, column, rows):
        title = self._active_table()
        if title is not None:
            self._apply_edit(title, lambda: self.project.paste(title, row, column, rows))

    def clear_cells(self, box):
        title = self._active_table()
        if title is None:
            return
        model = self.sheet.model()
        top, left, bottom, right = box
        bottom = min(bottom, len(model.frame) - 1)
        right = min(right, model.source_columns - 1)
        if bottom < top or right < left:
            return
        self._apply_edit(title, lambda: self.project.clear(title, (top, left, bottom, right)))

    def insert_row(self):
        title = self._active_table()
        if title is not None:
            row = max(0, self.sheet.currentIndex().row())
            self._apply_edit(title, lambda: self.project.insert_rows(title, row))

    def delete_rows(self):
        title = self._active_table()
        if title is None:
            return
        top, _, bottom, _ = self.sheet.box() or (0, 0, -1, 0)
        rows = [row for row in range(top, bottom + 1) if row < len(self.sheet.model().frame)]
        if rows:
            self._apply_edit(title, lambda: self.project.delete_rows(title, rows))

    def insert_column(self):
        title = self._active_table()
        if title is None:
            return
        dataset = self.project.tables[title]
        name, ok = QInputDialog.getText(self, qt("qt.insert_column"), qt("qt.column_name"),
                                        text=f"Column {len(dataset.raw.columns) + 1}")
        if ok and name.strip():
            column = self.sheet.currentIndex().column()
            position = column + 1 if 0 <= column < len(dataset.raw.columns) else len(dataset.raw.columns)
            self._apply_edit(title, lambda: self.project.insert_column(title, position, name.strip()))

    def delete_columns(self):
        title = self._active_table()
        if title is None:
            return
        _, left, _, right = self.sheet.box() or (0, 0, 0, -1)
        columns = list(range(left, right + 1))
        if columns:
            self._apply_edit(title, lambda: self.project.delete_columns(title, columns))

    def rename_column(self, column):
        title = self._active_table()
        if title is None:
            return
        dataset = self.project.tables[title]
        if not 0 <= column < len(dataset.raw.columns):
            formulas = list(dataset.formulas)
            if 0 <= column - len(dataset.raw.columns) < len(formulas):  # A calculated column: change its formula.
                self.edit_formula(formulas[column - len(dataset.raw.columns)])
            return
        name, ok = QInputDialog.getText(self, qt("qt.rename_column"), qt("qt.column_name"),
                                        text=str(dataset.raw.columns[column]))
        if ok:
            self._apply_edit(title, lambda: self.project.rename_column(title, column, name))

    def edit_formula(self, name=None):
        """Formula…: a new calculated column, or the one selected (or double-clicked) to change."""
        title = self._active_table()
        if title is None or self.busy():
            return
        dataset = self.project.tables[title]
        if name is None and self.sheet is not None:
            current = self.sheet.currentIndex()
            formulas = list(dataset.formulas)
            position = current.column() - len(dataset.raw.columns) if current.isValid() else -1
            name = formulas[position] if 0 <= position < len(formulas) else ""
        from .formula import FormulaDialog
        dialog = FormulaDialog(self, dataset, name or "")
        if dialog.exec() != FormulaDialog.DialogCode.Accepted or dialog.result is None:
            return
        column, expression = dialog.result
        self._apply_edit(title, lambda: self.project.set_formula(title, column, expression))

    def toggle_exclusion(self):
        title = self._active_table()
        if title is None:
            return
        box = self.sheet.box()
        if box is None:
            return
        top, left, bottom, right = box
        cells = [(row, column) for row in range(top, bottom + 1) for column in range(left, right + 1)]
        self._apply_edit(title, lambda: self.project.toggle_exclusion(title, cells))

    def undo(self, *, redo=False):
        if self.busy():
            return
        try:
            title, affected = self.project.undo(redo=redo)
        except (ValueError, TypeError, OverflowError) as error:
            self.error(error)
            return
        if title is None:
            return
        self.show_sheet("data", title)
        if affected:
            self.refresh_runs(affected)

    def new_table(self):
        if self.busy():
            return
        name = qt("qt.new_table_name", number=len(self.project.tables) + 1)
        title = self.project.new_table(self.project.unique_title(name))
        self.show_sheet("data", title)

    # == analyses ================================================================================
    def _analysis_input(self):
        if not self.project.tables:
            self.error(qt("qt.no_table"))
            return None, None
        if self.selected and self.selected[0] in {"result", "graph"}:
            run = self.project.runs[self.selected[1]]
            title = run.title
        elif self.selected and self.selected[0] == "data":
            title = self.selected[1]
        else:
            title = next(iter(self.project.tables))
        dataset = self.project.tables[title]
        frame = dataset.frame(mask_excluded=True)
        if frame.empty:
            self.error(qt("qt.empty"))
            return None, None
        return title, frame

    def analyze(self, method=None, only=None):
        if self.busy():
            return
        title, frame = self._analysis_input()
        if title is None:
            return
        current = (method, {}) if method else None
        self._ask(title, frame, current=current, only=only)

    def new_graph(self):
        self.analyze(only=[name for name in GRAPHING])

    def _ask(self, title, frame, *, current=None, only=None, index=None, error=None, error_field=None, source=_KEEP):
        """Ask for the parameters, then calculate. ``source`` sets the result an analysis reads (a new link, or
        Change input result…); by default a new analysis reads its data table and an edit keeps its input."""
        dialog = AnalysisDialog(self, frame, current=current, only=only, error=error, error_field=error_field)
        if dialog.exec() != AnalysisDialog.DialogCode.Accepted or dialog.result is None:
            return
        method, options = dialog.result
        try:
            candidate = self.project.candidate(title, method, options, index=index,
                                               source=None if source is _KEEP else source)
            if index is not None and source is not _KEEP and candidate.source != source:
                candidate.source = source
                self.project.analysis_graph(replacement=(index, candidate))
        except ValueError as error_:
            self.error(error_)
            return
        self.calculate_candidate(candidate, frame, index, only=only)

    def change_parameters(self):
        if self.busy() or not self.selected or self.selected[0] not in {"result", "graph"}:
            return
        if not self.settle_graph_draft():
            return
        index = self.selected[1]
        run = self.project.runs[index]
        try:
            frame = self.project.input_frame(run)
        except ValueError as error:
            self.error(error)
            return
        self._ask(run.title, frame, current=(run.method, run.options), index=index)

    # -- analysis chains ----------------------------------------------------------------------------------
    def analyze_result_table(self):
        """Analyze this result…: a new analysis reading the open result table, recalculated with its source."""
        if self.busy():
            return
        if not self.selected or self.selected[0] != "result" or self.result_tabs is None:
            self.error(tr("chain.select_result"))
            return
        run = self.project.runs[self.selected[1]]
        if run.result is None or run.calculation_error:
            self.error(tr("chain.calculate_source"))
            return
        from analisi.analysis_chain import ResultSource, result_frame
        table = list(run.result.tables)[max(0, self.result_tabs.currentIndex())]
        try:
            frame = result_frame(run.result, table)
        except ValueError as error:
            self.error(error)
            return
        self._ask(run.title, frame, source=ResultSource(run.uid, table))

    def source_analysis(self):
        """Open the analysis (and its result table) that this one reads."""
        if not self.selected or self.selected[0] not in {"result", "graph"}:
            return
        run = self.project.runs[self.selected[1]]
        if run.source is None:
            self.open_sheet(("data", run.title))
            return
        index = next((i for i, parent in enumerate(self.project.runs) if parent.uid == run.source.analysis_id), None)
        if index is None:
            self.error(tr("chain.missing_source"))
            return
        self.open_sheet(("result", index))
        parent = self.project.runs[index]
        if self.result_tabs is not None and parent.result is not None and run.source.table in parent.result.tables:
            self.result_tabs.setCurrentIndex(list(parent.result.tables).index(run.source.table))

    def change_input_result(self):
        """Change input result…: choose another source, then review the parameters for the new input."""
        if self.busy():
            return
        if not self.selected or self.selected[0] not in {"result", "graph"}:
            self.error(tr("chain.select_result"))
            return
        if not self.settle_graph_draft():
            return
        from copy import copy
        from .analysis_source import AnalysisSourceDialog
        index = self.selected[1]
        run = self.project.runs[index]

        def candidate_with(source):
            candidate = copy(run)
            candidate.source = source
            self.project.analysis_graph(replacement=(index, candidate))
            return candidate

        dialog = AnalysisSourceDialog(self, run, self.project.runs, candidate_with)
        if dialog.exec() != AnalysisSourceDialog.DialogCode.Accepted or dialog.result is None:
            return
        source, = dialog.result
        if source == run.source:
            return
        try:
            frame = self.project.input_frame(candidate_with(source))
        except ValueError as error:
            self.error(error)
            return
        self._ask(run.title, frame, current=(run.method, run.options), only=run.method, index=index, source=source)

    def format_graph(self):
        if self.busy() or not self.selected or self.selected[0] != "graph":
            return
        if self.inspector is not None:
            self.inspector.discard()  # The dialog edits the confirmed style, as in the classic window.
        run = self.project.runs[self.selected[1]]
        problem = self.project.graph_format_problem(run)
        if problem:
            self.error(problem)
            return
        from .graph_format import GraphFormatDialog
        style, xy = self.project.format_inputs(run)
        dialog = GraphFormatDialog(self, run.result.figure.axes[0], style, xy=xy)
        if dialog.exec() != GraphFormatDialog.DialogCode.Accepted or dialog.result is None:
            return
        try:
            self.project.apply_format(run, dialog.result, xy_update=dialog.xy_update, xy_result=dialog.xy_result)
        except ValueError as error:
            self.error(error)
            return
        self.show_sheet(*self.selected)
        self.status(qt("qt.style_applied"))

    def new_layout(self, *, edit=False):
        if self.busy():
            return
        key = self.selected[1] if edit and self.selected and self.selected[0] == "layout" else None
        if edit and key is None:
            return
        current = self.project.layouts[key] if key is not None else None
        candidates = self.project.layout_candidates(current)
        if not candidates:
            self.error(ui("Create one or more graphs before composing a layout."))
            return
        from .layout_dialog import LayoutDialog
        dialog = LayoutDialog(self, candidates, current)
        if dialog.exec() != LayoutDialog.DialogCode.Accepted or dialog.result is None or dialog.result == current:
            return
        try:
            key = self.project.put_layout(dialog.result, key)
        except ValueError as error:
            self.error(error)
            return
        self.open_sheet(("layout", key))

    def edit_annotations(self):
        from analisi.graph_annotations import ANNOTATIONS
        from .annotations import GraphAnnotationsDialog
        self._edit_drawings(ANNOTATIONS, GraphAnnotationsDialog, "annotation.native", "annotation.applied")

    def edit_shapes(self):
        from analisi.graph_shapes import SHAPES
        from .shapes import GraphShapesDialog
        self._edit_drawings(SHAPES, GraphShapesDialog, "shape.native", "shape.applied")

    def pairwise_comparisons(self, *, letters=False):
        """Insert → Pairwise Comparisons…: label pairs of a graph with an analysis of the same table."""
        from analisi import pairwise_graph as pg
        from analisi.inference import DUNN_ADJUSTMENT
        from .pairwise import PairwiseDialog

        if self.busy() or not self.selected or self.selected[0] != "graph":
            return
        index = self.selected[1]
        run = self.project.runs[index]
        problem = (pg.graph_problem(run.method, run.options) if run.method not in PRISM_GRAPH_METHODS
                   else "Pairwise comparisons are available on native box, violin and column graphs.")
        if not problem and (run.result is None or run.result.figure is None or not run.result.figure.axes):
            problem = "Calculate the graph first."
        if problem:
            self.error(ui(problem))
            return
        settings, _ = pg.read_section(run.options)
        sources = []
        for other in self.project.runs:
            if (other is run or other.title != run.title
                    or pg.source_problem(run.method, run.options, other.method, other.options)):
                continue
            detail = (f"Post-hoc: {other.options.get('Post-hoc')}" if other.method == pg.ONE_WAY
                      else f"Dunn: {other.options.get(DUNN_ADJUSTMENT, 'Bonferroni')}" if other.method == pg.KRUSKAL
                      else f"{other.options.get('First')} vs {other.options.get('Second')}")
            sources.append((other.slot, other.method,
                            f"{other.name}  ·  {detail}  ·  {ui('analysis')} {other.slot + 1}"))
        if not sources and pg.SECTION not in run.options:
            self.error(ui("Analyze this table first with a one-way ANOVA with multiple comparisons, a Kruskal–Wallis "
                          "test with Dunn comparisons, or a paired t-test of two graphed columns. FDR is not used."))
            return
        if not self.settle_graph_draft():
            return
        try:
            frame = self.project.input_frame(run)
        except ValueError as error:
            self.error(error)
            return
        endpoint = pg.endpoint_resolver(run.method)

        def load_rows(slot):
            source = next(other for other in self.project.runs if other.title == run.title and other.slot == slot)
            if source.result is None:
                source.result = compute(source, frame)
            return pg.comparison_rows(source.method, source.result.tables, source.options, endpoint)

        dialog = PairwiseDialog(self, sources, settings, pg.graph_anchors(run.result.figure.axes[0]), load_rows,
                                display=pg.LETTERS if letters else None)
        if dialog.exec() != PairwiseDialog.DialogCode.Accepted or dialog.result is None:
            return
        action, record = dialog.result
        options = dict(run.options)
        if action == "remove":
            options.pop(pg.SECTION, None)
        else:
            options[pg.SECTION] = record
        if options == run.options:
            self.status(ui("Pairwise comparisons unchanged."))
            return
        candidate = Run(run.method, run.title, options, slot=run.slot, style=run.style, uid=run.uid,
                        source=run.source, label=run.label)
        self.calculate_candidate(candidate, frame, index)

    def _edit_drawings(self, key, dialog_class, native, applied):
        """Annotations or shapes of the selected native graph: a list dialog, then one style change."""
        if self.busy() or not self.selected or self.selected[0] != "graph":
            return
        run = self.project.runs[self.selected[1]]
        problem = self.project.graph_format_problem(run)
        if problem or run.method in PRISM_GRAPH_METHODS:
            self.error(problem or tr(native))
            return
        if not self.settle_graph_draft():
            return
        style = deepcopy(run.style or {})
        dialog = dialog_class(self, run.result.figure.axes[0], style.get(key, []))
        if dialog.exec() != dialog_class.DialogCode.Accepted or dialog.result is None \
                or dialog.result == style.get(key, []):
            return
        if dialog.result:
            style[key] = dialog.result
        else:
            style.pop(key, None)
        try:
            self.project.apply_format(run, style)
        except ValueError as error:
            self.error(error)
            return
        self.show_sheet(*self.selected)
        self.status(tr(applied))

    def calculate_candidate(self, candidate, frame, index, *, only=None):
        pairwise = self.project.pairwise_snapshot(candidate)
        layout_data = self.project.layout_panel_data(candidate)
        control = CalculationControl()

        def done(future, cancelled):
            if cancelled:
                self.status(qt("qt.cancelled"))
                return
            try:
                result = future.result()
            except (MonteCarloCancelled, ChainCancelled):
                self.status(qt("qt.cancelled"))
                return
            except Exception as error:  # Field and data errors reopen the dialog with the message.
                self.status(qt("qt.failed"))
                field = error.field if isinstance(error, FieldError) else None
                self._ask(candidate.title, frame, current=(candidate.method, candidate.options), only=only,
                          index=index, error=str(error), error_field=field, source=candidate.source)
                return
            new_index, dependents = self.project.add_result(candidate, result, index)
            message = qt("qt.complete", method=method_label(candidate.method))
            if result.style_warning:
                message += f" {result.style_warning}"
            keep = index is not None and self.selected is not None and self.selected[0] in {"result", "graph"}
            self.show_sheet(self.selected[0] if keep else preferred_view(candidate, result), new_index)
            self.status(message)
            if dependents:
                self.refresh_runs(dependents)

        future = self.worker.submit(compute, candidate, frame, control, layout_data, pairwise)
        self._start(future, control, done, qt("qt.running", method=method_label(candidate.method)))

    def refresh_runs(self, runs):
        """Recalculate runs and everything linked to them in the background."""
        if not runs:
            return
        try:
            job = self.project.plan_refresh(runs)
        except ValueError as error:
            self.error(error)
            return
        if not job.selected:
            return
        self.project.mark_pending(job, qt("qt.updating", count=len(job.selected)))

        def done(future, cancelled):
            try:
                outcomes = future.result()
            except ChainCancelled:
                self.project.restore_after_cancel(job, qt("qt.cancelled"))
                self.status(qt("qt.cancelled"))
            except Exception as error:
                self.project.restore_after_cancel(job, str(error))
                self.status(str(error))
            else:
                if cancelled:
                    self.project.restore_after_cancel(job, qt("qt.cancelled"))
                    self.status(qt("qt.cancelled"))
                else:
                    errors = self.project.apply_refresh(job, outcomes)
                    self.status(qt("qt.update_failed", count=len(errors), first=errors[0]) if errors
                                else qt("qt.updated", count=len(outcomes)))
            if self.selected and self.selected[0] != "data":
                self.show_sheet(*self.selected)
            else:
                self.refresh()

        future = self.worker.submit(Project.run_refresh, job)
        self._start(future, job.control, done, qt("qt.updating", count=len(job.selected)))
        if self.selected and self.selected[0] != "data":
            self.show_sheet(*self.selected)

    # == families ================================================================================
    def _family_start(self):
        """The selected sheet as the engine names it, after bringing the stored project up to date."""
        from .family import family_ref
        selected = family_ref(self.project, self.selected)
        if selected is None:
            self.error(tr("family.select"))
            return None
        if self.busy(warn=False):
            self.error(tr("family.wait"))
            return None
        if not self.settle_graph_draft():
            return None
        self.project.sync_links(persist=True)
        return selected

    def _family_job(self, job, control, *, running, cancelled, failed, finish, discard_when_cancelled):
        project = self.project

        def done(future, was_cancelled):
            from analisi.family_workflow import FamilyError
            from .family import family_error_text
            try:
                outcome = future.result()
            except ChainCancelled:
                self.status(cancelled)
                return
            except Exception as error:
                message = tr(failed, error=family_error_text(error) if isinstance(error, FamilyError) else error)
                self.status(message)
                self.error(message)
                return
            if (discard_when_cancelled and was_cancelled) or self.project is not project:
                self.status(cancelled)
                return
            try:
                finish(outcome)
            except Exception as error:
                message = tr(failed, error=error)
                self.status(message)
                self.error(message)

        self._start(self.worker.submit(job), control, done, running)

    def duplicate_family(self):
        from analisi.family_workflow import duplicate_family
        from .family import FamilyDialog, family_describer, family_error_text
        selected = self._family_start()
        if selected is None:
            return
        describe = family_describer(self.project, selected, export=False)
        kind, key = selected
        if kind == "data":
            initial = base = tr("family.default_name", title=key)
            number = 2
            while initial in self.project.tables:
                initial, number = f"{base} ({number})", number + 1
        else:
            initial = tr("family.default_prefix")
        error, _ = describe(initial, True)
        if error is not None and error.field != "name":
            self.error(family_error_text(error))
            return
        dialog = FamilyDialog(self, "duplicate", kind, describe, initial=initial)
        if dialog.exec() != FamilyDialog.DialogCode.Accepted or dialog.result is None:
            return
        name, include = dialog.result
        project, control = self.project, CalculationControl()
        tables, layouts, infos = project.tables, project.layouts, tuple(project.info_sheets.values())

        def finish(bundle):
            focus = project.apply_family(bundle)
            self.open_sheet(focus)
            self.status(tr("family.duplicated", tables=len(bundle.tables), analyses=bundle.analysis_count,
                           layouts=len(bundle.layouts), infos=len(bundle.infos)))

        self._family_job(lambda: duplicate_family(tables, layouts, infos, selected, name=name, include_layouts=include,
                                                  cancel=control.cancel),
                         control, running=tr("family.copying"), cancelled=tr("family.cancelled"),
                         failed="family.failed", finish=finish, discard_when_cancelled=True)

    def save_family_as(self):
        from analisi.family_workflow import same_file, save_family
        from .family import FamilyDialog, family_describer, family_error_text
        selected = self._family_start()
        if selected is None:
            return
        describe = family_describer(self.project, selected, export=True)
        error, _ = describe("", True)
        if error is not None:
            self.error(family_error_text(error))
            return
        dialog = FamilyDialog(self, "save", selected[0], describe)
        if dialog.exec() != FamilyDialog.DialogCode.Accepted or dialog.result is None:
            return
        _, include = dialog.result
        path, _ = QFileDialog.getSaveFileName(self, tr("family.save_title"), tr("family.default_file"),
                                              f"{tr('prompt.project_filetype')} (*.alab)")
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() != ".alab":
            self.error(tr("error.alab_name"))
            return
        project, control = self.project, CalculationControl()
        if project.path is not None and same_file(path, project.path):
            self.error(tr("family.error.current-path"))
            return
        if any(other.project.path is not None and same_file(path, other.project.path) for other in self.sessions):
            self.error(qt("qt.save_conflict", name=path.name))  # A project open in another tab.
            return
        tables, layouts, infos = project.tables, project.layouts, tuple(project.info_sheets.values())
        source = project.path

        def finish(bundle):
            self.status(tr("family.saved", name=path.name, tables=len(bundle.tables), analyses=bundle.analysis_count,
                           layouts=len(bundle.layouts), infos=len(bundle.infos)))

        self._family_job(lambda: save_family(path, tables, layouts, infos, selected, include_layouts=include,
                                             source_path=source, cancel=control.cancel),
                         control, running=tr("family.saving"), cancelled=tr("family.save_cancelled"),
                         failed="family.save_failed", finish=finish, discard_when_cancelled=False)

    def recalculate(self):
        if self.busy() or not self.selected or not self.settle_graph_draft():
            return
        kind, key = self.selected
        if kind in {"result", "graph", "saved-layout"}:
            self.refresh_runs([self.project.runs[key]])
        elif kind == "layout":
            self.refresh_runs(self.project.layout_runs(self.project.layouts[key]))

    def use_result_as_data(self):
        if self.busy() or not self.selected or self.selected[0] != "result" or self.result_tabs is None:
            return
        run = self.project.runs[self.selected[1]]
        if run.result is None or run.calculation_error:
            self.error(qt("qt.not_calculated"))
            return
        tables = list(run.result.tables)
        if not tables:
            return
        name = tables[max(0, self.result_tabs.currentIndex())]
        try:
            title = self.project.use_result_as_data(run, name)
        except ValueError as error:
            self.error(error)
            return
        self.show_sheet("data", title)

    # == background calculation ==================================================================
    def _start(self, future, control, done, label):
        self.job = Job(future, control, done, label, self.sessions.active)
        self.status(label)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.update_actions()
        self.timer.start()

    def _poll(self):
        job = self.job
        if job is None:
            self.timer.stop()
            return
        if not job.future.done():
            finished, total = job.control.progress() if job.control is not None else (0, 0)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(finished)
            return
        self.timer.stop()
        self.job = None
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        cancelled = job.control is not None and job.control.cancel.is_set()
        try:
            if job.session is None or job.session is self.sessions.active:
                job.done(job.future, cancelled)
            elif job.session in self.sessions.items:  # Not reachable from the UI (tabs wait): never mix projects.
                self._activate(job.session)
                job.done(job.future, cancelled)
        finally:
            self.update_actions()
        self._after_job()

    def _after_job(self):
        """Run what waited for the calculation: closing the window, then files that arrived meanwhile."""
        if self.job is not None:
            if self._close_pending:
                self.cancel_calculation()
            return
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)
            return
        queued, self._queued = self._queued, []
        for path, import_data in queued:
            self.open_path(path, import_data=import_data)  # Queues again by itself if this one starts a job.

    def cancel_calculation(self):
        if self.job is not None and self.job.control is not None:
            self.job.control.cancel.set()
            self.status(qt("qt.cancelled"))

    # == files ===================================================================================
    def confirm_saved(self):
        """Save, Discard or Cancel for the active project only. True when it may be left behind."""
        self.flush_info()
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self, qt("qt.unsaved_title"), qt("qt.unsaved", name=self.project.title),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    # == project tabs ============================================================================
    def _commit_sheet_edit(self):
        """A cell still being typed is stored in its own project before the tab changes."""
        sheet = self.sheet
        if sheet is None:
            return
        if sheet.state() == QAbstractItemView.State.EditingState:
            editor = sheet.indexWidget(sheet.currentIndex())
            if editor is not None:
                sheet.commitData(editor)
                sheet.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        sheet.model().flush_edits()

    def prepare_project_change(self):
        """Before leaving the active tab: settle the Inspector draft, store typed cells and Info notes, and make
        sure no calculation is running. False keeps the active tab as it is."""
        if self.busy(warn=False):
            self.status(qt("qt.wait_projects"))
            return False
        if not self.settle_graph_draft():
            return False
        self._commit_sheet_edit()
        self.flush_info()
        if self.busy(warn=False):  # The last edit started a recalculation: the tab waits for it.
            self.status(qt("qt.wait_projects"))
            return False
        return True

    def _capture(self):
        """What the active tab shows, kept for when it comes back. Nothing of the project is copied."""
        session = self.sessions.active
        self.dispose_inspector()  # Stores the element the Inspector had selected in this session.
        self.flush_info()
        self.info_editor = None
        view = {"navigator": self.navigator.verticalScrollBar().value()}
        if self.sheet is not None:
            current = self.sheet.currentIndex()
            if current.isValid():
                view["cell"] = (current.row(), current.column())
            view["scroll"] = (self.sheet.horizontalScrollBar().value(), self.sheet.verticalScrollBar().value())
        if self.result_tabs is not None:
            view["result_tab"] = self.result_tabs.currentIndex()
        session.view = view
        session.status = self.message.text()

    def _valid_ref(self, ref):
        if not ref:
            return False
        kind, key = ref
        project = self.project
        if kind == "data":
            return key in project.tables
        if kind == "info":
            return key in project.info_sheets
        count = len(project.layouts) if kind == "layout" else len(project.runs)
        return isinstance(key, int) and 0 <= key < count

    def _install(self):
        """Show the active session as it was left: sheet, cell, scroll, result tab, navigator and status."""
        session = self.sessions.active
        view = dict(session.view)
        ref = session.selected if self._valid_ref(session.selected) else None
        if ref is None:
            self.show_home()
        else:
            self.show_sheet(*ref)  # Never starts a calculation: a tab shows what its project holds.
        sheet = self.sheet
        if sheet is not None and "cell" in view:
            row, column = view["cell"]
            model = sheet.model()
            if row < model.rowCount() and column < model.columnCount():
                sheet.setCurrentIndex(model.index(row, column))
        if self.result_tabs is not None and 0 <= view.get("result_tab", -1) < self.result_tabs.count():
            self.result_tabs.setCurrentIndex(view["result_tab"])
        self.status(session.status or qt("qt.ready"))
        self._sync_tabs()

        def scroll():  # After the layout has given the views their size.
            if self.sessions.active is not session:
                return
            if sheet is not None and sheet is self.sheet and "scroll" in view:
                sheet.horizontalScrollBar().setValue(view["scroll"][0])
                sheet.verticalScrollBar().setValue(view["scroll"][1])
            if "navigator" in view:
                self.navigator.verticalScrollBar().setValue(view["navigator"])

        QTimer.singleShot(0, scroll)

    def _activate(self, session, *, capture=True):
        if capture:
            self._capture()
        else:
            self.dispose_inspector()
            self.info_editor = None
        self.sessions.active = session
        self._install()

    def switch_project(self, session):
        """Make ``session`` the active tab. False (and the tab strip unchanged) when the active tab must stay."""
        if session is self.sessions.active:
            return True
        if session not in self.sessions.items or not self.prepare_project_change():
            self._sync_tabs()
            return False
        self._activate(session)
        return True

    def _project_tab_changed(self, index):
        if 0 <= index < len(self.sessions) and self.sessions[index] is not self.sessions.active:
            self.switch_project(self.sessions[index])

    def _project_tab_close(self, index):
        if 0 <= index < len(self.sessions):
            self.close_project(self.sessions[index])

    def step_project(self, offset):
        if len(self.sessions) > 1:
            self.switch_project(self.sessions.step(offset))

    def new_project(self):
        if self.busy():
            return
        if self.sessions.full():
            self.error(qt("qt.too_many_projects", count=MAX_PROJECT_TABS))
            return
        if not self.prepare_project_change():
            return
        self.project_number += 1
        self._activate(self.sessions.add(Project(self.project_number)))

    def close_project(self, session=None):
        """Close one project tab: Save, Discard or Cancel for that project only. The last tab becomes empty."""
        if session is not None and not self.switch_project(session):
            return False
        if not self.prepare_project_change() or not self.confirm_saved():
            return False
        closing = self.sessions.active
        target = self.sessions.neighbour(closing)
        if target is None:
            self.dispose_inspector()
            self.info_editor = None
            closing.reset(Project(closing.project.number))
            self._install()
        else:
            self._activate(target, capture=False)
            self.sessions.remove(closing)
            self._sync_tabs()
            self.update_actions()
        return True

    def confirm_close(self):
        """Closing the window: a decision for every project with changes before any tab is lost. Cancel (or a
        failed save) keeps the window with all its tabs, on the project asked about."""
        if not self.settle_graph_draft():
            return False
        self._commit_sheet_edit()
        self.flush_info()
        if self.job is not None:  # The last edit started a recalculation: close when it ends.
            self._close_pending = True
            self.status(qt("qt.closing_after_job"))
            return False
        active = self.sessions.active
        for session in [active] + [other for other in self.sessions if other is not active]:
            if not session.project.dirty:
                continue
            if session is not self.sessions.active:
                self._activate(session)
            if not self.confirm_saved():
                return False
        return True

    def open_dialog(self, *, import_data=False):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("command.open"), "",
                                              f"{tr('prompt.data_files')} ({OPEN_FILTER});;{tr('prompt.all_files')} (*)")
        if path:
            self.open_path(path, import_data=import_data)

    def open_path(self, path, *, import_data=False):
        """Open a project in its own tab (the empty tab is reused; a project already open is shown), or bring data
        into the active project. Files that arrive during a calculation open when it ends."""
        path = Path(path)
        if self.job is not None:
            self._queued.append((path, import_data))
            self.status(qt("qt.open_later", name=path.name))
            return
        suffix = path.suffix.lower()
        replace = suffix == ".alab" or (suffix in PROJECT_SUFFIXES and not import_data)
        try:
            if replace:
                existing = self.sessions.find(path)
                if existing is not None:
                    if self.switch_project(existing):
                        self.status(qt("qt.already_open", name=path.name))
                    return
                reuse = self.project.is_empty()
                if not reuse and self.sessions.full():
                    raise ValueError(qt("qt.too_many_projects", count=MAX_PROJECT_TABS))
                if not self.prepare_project_change():
                    return
                number = self.project.number if reuse else self.project_number + 1
                project = Project(number)
                titles = project.load(path)  # Read first: a file that cannot be opened changes no tab.
                if suffix != ".alab":
                    project.origin, project.dirty = path, False
                if reuse:
                    self.dispose_inspector()
                    self.info_editor = None
                    self.sessions.active.reset(project)
                else:
                    self.project_number = number
                    self._activate(self.sessions.add(project))
                self.status(tr("status.opened", name=path.name))
            elif import_data and suffix in TEXT_SUFFIXES:  # Import text data: choose rows, columns and format.
                from .text_import import TextImportDialog
                dialog = TextImportDialog(self, path)
                if dialog.exec() != TextImportDialog.DialogCode.Accepted or dialog.result is None:
                    return
                titles = self.project.add_tables({path.stem: dialog.result})
                self.status(qt("qt.imported", count=len(titles)))
            else:
                titles = self.project.load(path)
                self.status(qt("qt.imported", count=len(titles)))
        except Exception as error:
            self.error(error)
            return
        sheets = [title for title in titles if not stored_prism_view(self.project.tables[title])]
        if sheets:
            self.show_sheet("data", sheets[0])
        elif self.project.runs:
            run = self.project.runs[0]
            self.open_sheet((preferred_view(run, run.result), 0))
        else:
            self.refresh()

    def save(self, *, as_new=False):
        if self.busy() or not self.settle_graph_draft():
            return False
        self.flush_info()
        if not self.project.tables and not self.project.info_sheets:
            return False
        path = self.project.path if not as_new else None
        if path is None:
            suggested = (self.project.origin.with_suffix(".alab").name if self.project.origin else "")
            name, _ = QFileDialog.getSaveFileName(self, tr("command.save_project_as"), suggested,
                                                  f"{tr('prompt.project_filetype')} (*.alab)")
            if not name:
                return False
            path = Path(name)
            if not path.suffix:
                path = path.with_suffix(".alab")
            if self.sessions.holding(path, besides=self.sessions.active) is not None:
                self.error(qt("qt.save_conflict", name=path.name))  # Never overwrite a project open in another tab.
                return False
        try:
            self.project.save(path)
        except (ValueError, OSError, TypeError) as error:
            self.error(error)
            return False
        self.status(tr("status.saved", name=path.name))
        self.refresh()
        return True

    def export(self):
        if not self.selected or not self.settle_graph_draft():
            return
        kind, key = self.selected
        try:
            if kind == "info":
                sheet = self.project.info_sheets[key]
                path, _ = QFileDialog.getSaveFileName(self, tr("command.export"), f"{sheet.title}.txt", "Text (*.txt)")
                if path:
                    lines = [f"Info sheet · {sheet.title}", "", "Constants"]
                    lines += [f"• {name} = {value}" for name, value in sheet.fields]
                    lines += ["", "Notes", *(f"> {line}" for line in sheet.notes.splitlines())]
                    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
            elif kind in {"graph", "layout", "saved-layout"}:
                if kind == "layout":
                    layout = self.project.layouts[key]
                    figure, name = self.project.layout_figure(layout), layout.name
                else:
                    run = self.project.runs[key]
                    figure = run.result.figure if run.result is not None else None
                    name = run.name
                if figure is None:
                    raise ValueError(qt("qt.layout_missing"))
                path, chosen = QFileDialog.getSaveFileName(
                    self, qt("qt.export_graph"), f"{name}.png",
                    "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;TIFF (*.tif *.tiff)")
                if path:
                    if not Path(path).suffix:
                        path += {"SVG": ".svg", "PDF": ".pdf", "TIFF": ".tif"}.get(chosen.split(" ")[0], ".png")
                    if kind == "layout":
                        self.project.export_layout(layout, path)
                    else:
                        export_graph(figure, path)
            else:
                if kind == "data":
                    frame, index = self.project.tables[key].frame(mask_excluded=True), False
                    name = key
                else:
                    run = self.project.runs[key]
                    if run.result is None or not run.result.tables:
                        raise ValueError(qt("qt.not_calculated"))
                    tables = list(run.result.tables.items())
                    position = self.result_tabs.currentIndex() if self.result_tabs is not None else 0
                    name, frame = tables[max(0, position)]
                    index = True
                path, _ = QFileDialog.getSaveFileName(self, qt("qt.export_table"), f"{name}.csv", "CSV (*.csv)")
                if path:
                    if not Path(path).suffix:
                        path += ".csv"
                    safe_csv(path, frame, index=index)
            if path:
                self.status(qt("qt.exported", name=Path(path).name))
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def export_with_options(self):
        """File → Export with options…: size in mm, DPI, transparency and SVG text for a graph or layout."""
        if not self.selected or self.selected[0] not in {"graph", "layout", "saved-layout"}:
            self.error(ui("Select a calculated graph or layout to export with options."))
            return
        if not self.settle_graph_draft():
            return
        from analisi.figure_export import check_destination
        from analisi.layout_geometry import page_size
        from .export_options import FORMAT_NAMES, ExportOptionsDialog
        kind, key = self.selected
        layout = self.project.layouts[key] if kind == "layout" else None
        if layout is not None:
            figure, name = self.project.layout_figure(layout), layout.name
        else:
            run = self.project.runs[key]
            figure = run.result.figure if run.result is not None else None
            name = run.name
            if run.calculation_error:
                self.error(tr("reference.stale_export"))
                return
        if figure is None or not figure.axes:
            self.error(ui("Export with options is available for calculated native graphs and layouts. "
                          "Imported graphs and layouts keep their original export."))
            return
        layout_size = page_size(layout.columns, len(layout.panels), layout.paper) if layout is not None else None
        dialog = ExportOptionsDialog(self, tuple(figure.get_size_inches()), raster_panels=kind == "saved-layout",
                                     layout_size=layout_size)
        if dialog.exec() != ExportOptionsDialog.DialogCode.Accepted or dialog.result is None:
            return
        settings = dialog.result
        fmt = settings["format"]
        label = next(text for text, value in FORMAT_NAMES.items() if value == fmt)
        suffix = ".tif" if fmt == "tiff" else f".{fmt}"
        pattern = "*.tif *.tiff" if fmt == "tiff" else f"*{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, tr("command.export_with_options"), f"{name}{suffix}",
                                              f"{label} ({pattern})")
        if not path:
            return
        if not Path(path).suffix:
            path += suffix
        try:
            check_destination(path, fmt)
            if layout is not None:
                self.project.export_layout(layout, path, settings)
            else:
                export_graph(figure, path, settings)
        except (OSError, ValueError, TypeError) as error:
            self.error(error)
            return
        self.status(tr("interface.exported", name=Path(path).name))

    def export_pdf_bundle(self):
        if self.busy() or not self.settle_graph_draft():
            return
        from .pdf_bundle import PdfBundleDialog, bundle_sheets
        graphs = [index for index, run in enumerate(self.project.runs) if preferred_view(run, run.result) == "graph"
                  or (run.result is not None and run.result.figure is not None)]
        entries, notes = bundle_sheets(self.project, graphs, PRISM_GRAPH_METHODS)
        if not entries:
            self.error(" ".join([tr("pdf.empty"), *notes]))
            return
        dialog = PdfBundleDialog(self, entries, notes)
        if dialog.exec() != PdfBundleDialog.DialogCode.Accepted or dialog.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("pdf.title"), f"{self.project.title}.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        by_ref = {entry.ref: entry for entry in entries}
        chosen = [by_ref[ref] for ref in dialog.result["refs"]]
        try:
            pages = self.project.export_pdf_pages([entry.ref for entry in chosen], path, dialog.result["settings"],
                                                  [entry.label for entry in chosen])
        except (OSError, ValueError, TypeError) as error:
            self.error(error)
            return
        count = tr("pdf.one_page") if pages == 1 else tr("pdf.many_pages", count=pages)
        self.status(tr("pdf.exported", pages=count, name=Path(path).name))

    def open_classic(self):
        if self.busy():
            return
        if self.project.dirty or (self.project.tables and self.project.path is None):
            QMessageBox.information(self, qt("qt.classic"), qt("qt.classic_save"))
            if not self.save():
                return
        arguments = ["--tk"] + ([str(self.project.path)] if self.project.path else [])
        if getattr(sys, "frozen", False):
            command = [sys.executable, *arguments]
        else:
            command = [sys.executable, str(Path(__file__).resolve().parent.parent / "tramastat.py"), *arguments]
        try:
            subprocess.Popen(command, close_fds=True)
        except OSError as error:
            self.error(error)

    def choose_language(self):
        codes = list(LANGUAGE_NAMES)
        names = [LANGUAGE_NAMES[code] for code in codes]
        from analisi.i18n import active_language
        choice, ok = QInputDialog.getItem(self, tr("command.language"), tr("command.language"), names,
                                          codes.index(active_language()), False)
        if ok:
            try:
                save_language(config_path(), codes[names.index(choice)])
            except (OSError, ValueError) as error:
                self.error(error)
                return
            QMessageBox.information(self, tr("command.language"), qt("qt.language_restart"))

    def about(self):
        QMessageBox.about(self, qt("qt.about"), qt("qt.about_text", version=VERSION, qt=PYSIDE_VERSION))

    # == window events ===========================================================================
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in PROJECT_SUFFIXES | DATA_SUFFIXES:
                self.open_path(path)
                break

    def closeEvent(self, event):
        if self.job is not None:  # Stop the calculation first; the window closes (asking as usual) when it ends.
            self._close_pending = True
            self.cancel_calculation()
            self.status(qt("qt.closing_after_job"))
            event.ignore()
            return
        if not self.confirm_close():
            event.ignore()
            return
        self.timer.stop()
        self.worker.shutdown(wait=False, cancel_futures=True)
        event.accept()
