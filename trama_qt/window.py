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
from PySide6.QtWidgets import (QCompleter, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QSplitter, QStackedWidget, QTabBar, QTableWidget, QTableWidgetItem, QTabWidget,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QHeaderView)

from analisi._version import VERSION
from analisi.analysis_chain import ChainCancelled
from analisi.field_error import FieldError
from analisi.i18n import LANGUAGE_NAMES, config_path, save_language, tr, ui
from analisi.monte_carlo import MonteCarloCancelled
from analisi.prism_restore import SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT, SAVED_BINARY_RESULT
from analisi.workbench import GRAPH_METHODS, GROUPS

from . import theme
from .analysis_dialog import AnalysisDialog
from .labels import method_label
from .models import WorksheetModel, column_label
from .project import (DATA_SUFFIXES, OPEN_FILTER, PRISM_GRAPH_METHODS, PROJECT_SUFFIXES, CalculationControl, Project,
                      Run, compute, run_view, stored_prism_view)
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


def export_graph(figure, path):
    """A graph at its own size, 300 dpi for images, verified before it replaces the file."""
    from analisi.figure_export import export_figure
    suffix = Path(path).suffix.lower()
    fmt = {".svg": "svg", ".pdf": "pdf", ".tif": "tiff", ".tiff": "tiff"}.get(suffix, "png")
    export_figure(figure, path, {"format": fmt, "dpi": 300} if fmt in {"png", "tiff"} else {"format": fmt})


class Job:
    def __init__(self, future, control, done, label):
        self.future, self.control, self.done, self.label = future, control, done, label


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
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(6)
        self.layout_.addLayout(self.actions_row)
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
        self.actions_row.addStretch(1)

    def release(self):
        """Detach matplotlib figures from the canvases that are about to be deleted."""
        for canvas in self.canvases:
            figure = canvas.figure
            FigureCanvasBase(figure)
        self.canvases.clear()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = Project()
        self.project_number = 1
        self.selected = None
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
        self.inspector_wanted = False
        self.inspector_element = None
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
        a("import", tr("command.import_into_project"), lambda: self.open_dialog(import_data=True), icon="file-up",
          shortcut="Ctrl+I")
        a("save", tr("command.save_project"), self.save, icon="save", shortcut="Ctrl+S")
        a("save_as", tr("command.save_project_as"), lambda: self.save(as_new=True), shortcut="Ctrl+Shift+S")
        a("export", tr("command.export"), self.export, icon="upload", shortcut="Ctrl+E")
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
        a("duplicate_family", ui("Duplicate family…"), self.duplicate_family, icon="copy")
        a("save_family", ui("Save family as…"), self.save_family_as, icon="save")
        a("insert_row", qt("qt.insert_row"), self.insert_row, icon="rows-3")
        a("insert_column", qt("qt.insert_column"), self.insert_column, icon="columns-3")
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

    def _tool(self, key, *, text=True, primary=False):
        button = QToolButton()
        button.setDefaultAction(self.actions[key])
        button.setAutoRaise(True)
        button.setIconSize(theme.icon_size(18))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text
                                  else Qt.ToolButtonStyle.ToolButtonIconOnly)
        if primary:
            button.setObjectName("primary")
            button.setIcon(theme.icon(self.icons.get(key, "sigma"), theme.T["on_accent"]))
        return button

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
            (tr("ribbon.modern.file"), ["new_project", "open", "import", "save", "save_as", "|", "export", "export_pdf", "|",
                                         "classic", "language", "about"]),
            (tr("ribbon.modern.home"), ["paste", "cut", "copy", "|", "undo", "redo", "|", "new_table", "insert_row",
                                         "insert_column", "exclude", "|", "*analyze", "new_graph", "|", "recalculate",
                                         "export", "|", "duplicate_family", "save_family"]),
            (tr("ribbon.modern.analyze"), ["*analyze", "|", "descriptive", "ttest", "anova", "correlation", "linear",
                                            "nonlinear", "survival", "contingency", "|", "change", "recalculate",
                                            "use_result"]),
            (tr("ribbon.modern.graph"), ["*new_graph", "|", "inspector", "format_graph", "annotations", "shapes",
                                          "pairwise", "compact_letters", "change", "recalculate", "|", "new_layout",
                                          "edit_layout", "|", "export"]),
            (tr("ribbon.modern.view"), ["navigator", "|", "language", "classic"]),
        ]
        for title, keys in groups:
            self.ribbon_tabs.addTab(title)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 0)
            row_layout.setSpacing(2)
            for key in keys:
                if key == "|":
                    line = QFrame()
                    line.setFrameShape(QFrame.Shape.VLine)
                    line.setStyleSheet(f"color: {theme.T['border']};")
                    row_layout.addWidget(line)
                    continue
                primary = key.startswith("*")
                key = key.lstrip("*")
                button = self._tool(key, primary=primary)
                row_layout.addWidget(button)
            row_layout.addStretch(1)
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

    def update_actions(self):
        kind = self.selected[0] if self.selected else None
        on_run = kind in {"result", "graph", "saved-layout"}
        data = kind == "data"
        editable = data and not stored_prism_view(self.project.tables[self.selected[1]])
        idle = self.job is None
        for key in ("cut", "paste", "insert_row", "insert_column", "delete_rows", "exclude"):
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
        has_data = bool(self.project.tables)
        for key in ("analyze", "new_graph", "descriptive", "ttest", "anova", "correlation", "linear", "nonlinear",
                    "survival", "contingency"):
            self.actions[key].setEnabled(has_data and idle)
        self.actions["undo"].setEnabled(idle and self.project.history.can_apply())
        self.actions["redo"].setEnabled(idle and self.project.history.can_apply(redo=True))
        for key in ("open", "import", "new_project", "save", "save_as", "classic"):
            self.actions[key].setEnabled(idle)
        self.actions["export"].setEnabled(kind is not None)
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
            for index, run in results:
                marker = " ⚠" if run.calculation_error else ""
                self._entry(section, run.name + marker, ("result", index), "sigma")
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
        model = WorksheetModel(dataset, lambda row, column, text: self.edit_cell(title, row, column, text),
                               read_only=read_only)
        self.sheet = page.add(WorksheetView(model, self))
        self.sheet.setCurrentIndex(model.index(0, 0))
        return page

    def _info_page(self, uid):
        sheet = self.project.info_sheets[uid]
        page = Page(sheet.title, tr("interface.linked_to", table=sheet.table) if sheet.table else tr("nav.info"))
        page.finish_actions()
        caption = QLabel(qt("qt.info_fields"))
        caption.setObjectName("sectionTitle")
        page.add(caption, 0)
        table = QTableWidget(len(sheet.fields), 2)
        table.setHorizontalHeaderLabels(["", ""])
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (name, value) in enumerate(sheet.fields):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(value))
        page.add(table, 1)
        caption = QLabel(qt("qt.info_notes"))
        caption.setObjectName("sectionTitle")
        page.add(caption, 0)
        notes = QPlainTextEdit(sheet.notes)
        notes.setReadOnly(True)
        page.add(notes, 2)
        return page

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

        self.inspector = GraphInspector(run, canvas, confirmed=lambda: run.style,
                                        commit=lambda style: self.commit_style(run, style), closed=closed,
                                        element=self.inspector_element)
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

    def commit_style(self, run, style):
        self.project.commit_style(run, style)
        self.update_title()
        self.status(qt("qt.style_applied"))

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

    def edit_cell(self, title, row, column, text):
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
            if column >= len(dataset.raw.columns) and column < len(dataset.raw.columns) + len(dataset.formulas):
                self.error(qt("qt.formula_column"))
            return
        name, ok = QInputDialog.getText(self, qt("qt.rename_column"), qt("qt.column_name"),
                                        text=str(dataset.raw.columns[column]))
        if ok:
            self._apply_edit(title, lambda: self.project.rename_column(title, column, name))

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

    def _ask(self, title, frame, *, current=None, only=None, index=None, error=None, error_field=None):
        dialog = AnalysisDialog(self, frame, current=current, only=only, error=error, error_field=error_field)
        if dialog.exec() != AnalysisDialog.DialogCode.Accepted or dialog.result is None:
            return
        method, options = dialog.result
        try:
            candidate = self.project.candidate(title, method, options, index=index)
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
                          index=index, error=str(error), error_field=field)
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
        self.job = Job(future, control, done, label)
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
            job.done(job.future, cancelled)
        finally:
            self.update_actions()

    def cancel_calculation(self):
        if self.job is not None and self.job.control is not None:
            self.job.control.cancel.set()
            self.status(qt("qt.cancelled"))

    # == files ===================================================================================
    def confirm_saved(self):
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self, qt("qt.unsaved_title"), qt("qt.unsaved", name=self.project.title),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self):
        if self.busy() or not self.confirm_saved():
            return
        self.project_number += 1
        self.project = Project(self.project_number)
        self.show_home()
        self.refresh()

    def open_dialog(self, *, import_data=False):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("command.open"), "",
                                              f"{tr('prompt.data_files')} ({OPEN_FILTER});;{tr('prompt.all_files')} (*)")
        if path:
            self.open_path(path, import_data=import_data)

    def open_path(self, path, *, import_data=False):
        path = Path(path)
        suffix = path.suffix.lower()
        replace = suffix == ".alab" or (suffix in PROJECT_SUFFIXES and not import_data)
        try:
            if replace:
                if not self.project.is_empty() and not self.confirm_saved():
                    return
                project = Project(self.project_number)
                titles = project.load(path)
                if suffix != ".alab":
                    project.origin, project.dirty = path, False
                self.project = project
                self.status(tr("status.opened", name=path.name))
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
        if self.job is not None and self.job.control is not None:
            self.job.control.cancel.set()
        if not self.confirm_saved():
            event.ignore()
            return
        self.timer.stop()
        self.worker.shutdown(wait=False, cancel_futures=True)
        event.accept()
