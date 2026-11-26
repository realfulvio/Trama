"""The Trama main window on Qt: command bar, navigator, sheets and background calculations."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from weakref import WeakKeyDictionary

from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSplitter, QTabBar, QToolBar,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from analisi import cohen_kappa as kappa, cox_exact, cox_outputs, mcnemar_power, mean_permutation, parallel, power_plan, rmst
from analisi import anova_comparison_plot, anova_diagnostics, anova_grouped_plot, result_display
from analisi._version import VERSION
from analisi.analysis_chain import ChainCancelled
from analisi.axis_breaks import AXIS_BREAKS
from analisi.field_error import FieldError
from analisi.i18n import LANGUAGE_NAMES, config_path, save_language, tr, translate_message, ui
from analisi.kmeans_options import METHODS as KMEANS_METHODS
from analisi.kmeans_reports import FIT_DIAGNOSTICS_TABLE, FIT_REASON, FIT_SOURCE
from analisi.correlation_matrix import CORRELATION_MATRIX
from analisi.monte_carlo import MONTE_CARLO, MonteCarloCancelled
from analisi.weighted_logrank import WeightedComparisonCancelled
from analisi.plot_function import CURVES as FUNCTION_CURVES, PLOT_FUNCTION
from analisi.transpose_xy import TRANSPOSE_XY
from analisi.presentation import apply_style, validate_graph_style
from analisi.legacy_binary_range import BINARY_XY_RANGE
from analisi.legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_EDITS
from analisi.legacy_fit_graph import FIT_GRAPH
from analisi.legacy_mv_scatter import CLUSTERED_SCATTER
from analisi.legacy_restore import (LEGACY_PREVIEW, SAVED_AXES, SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT,
                                   SAVED_EDITABLE_GRAPH, SAVED_XY, initial_sheet_reference, layout_panel_sources,
                                   linked_curve_view, paired_graph_index)
from analisi.legacy_zip_layout import ZIP_LAYOUT, imported_paper
from analisi.legacy_zip_column import ZIP_COLUMN
from analisi.legacy_xml_xy import XML_ERROR_BARS
from analisi.legacy_xml_generated import XML_GENERATED_XY
from analisi.legacy_xml_qc import XML_QC
from analisi.legacy_xml_binding_layout import XML_BINDING_XY
from analisi.legacy_zip_xy import ZIP_SPARSE_XY
from analisi.survival_plot import SURVIVAL_GRAPH
from analisi.text_import import TEXT_SUFFIXES
from analisi.ordinal_logit import GRAPH as ORDINAL_GRAPH, ORDINAL_LOGIT
from analisi.tolerance_intervals import SHOW_GRAPH as TOLERANCE_GRAPH, TOLERANCE
from analisi.weibull_aft import METHOD as WEIBULL_AFT, SHOW_GRAPH as WEIBULL_GRAPH
from analisi.workbench import GRAPH_METHODS
from analisi.sheet_metadata import HIGHLIGHTS, RUN_KINDS, validate_sheet_title
from analisi.numeric_series import validate_series_target
from analisi.worksheet_appearance import font_preference, save_font_preference, zoom_step
from analisi.worksheet_row_identity import moved_row_bounds
from analisi.worksheet_sort import (ASCENDING, plan_row_sort, remap_selection_after_sort,
                                    row_title_sort_column, sort_text, sortable_columns, x_sort_column)
from analisi.worksheet_text import TextStyles
from analisi.paired_graphs import paired_plot_options
from analisi.rank_graphs import RANK_PLOT, rank_plot_options
from analisi.rank_tests import MANN_WHITNEY, WILCOXON

from . import global_catalog
from . import gui_gc, office, theme
from .analysis_dialog import AnalysisDialog
from .classic_bar import ClassicToolbar, build_menus
from .flow import FlowLayout
from .gallery import GalleryPage, g as gallery_text
from .labels import method_label
from .report_dialog import text as report_text
from .result_tabs import ResultTabs, result_labels
from .models import WorksheetModel, column_label
from .printing import FIGURE_KINDS, PrintCommands
from .recovery import RecoveryDialog, RecoverySettingsDialog, r as recovery_text
from .project import (DATA_SUFFIXES, GRAPHING, GRAPH_TYPE_METHODS, LEGACY_GRAPH_METHODS, OPEN_FILTER, PROJECT_SUFFIXES,
                      SAVED_VIEWS, CalculationControl, Project, Run, compute, result_as_table, run_view,
                      stored_legacy_view)
from .sessions import MAX_PROJECT_TABS, Sessions, remember_project
from .templates import sync_actions as sync_template_actions, t as template_text
from analisi.repeat_analysis_text import t as repeat_text
from .linked_table_canvas import LinkedTableCanvas
from .shape_canvas import GraphDrawing
from .sheet import FrameView, WorksheetView, selection_box, set_table_appearance
from .text_format import TextFormat
from .batch_export import safe_stem
from .batch_export_dialog import text as batch_text
from .status_label import StatusLabel
from .strings import qt
from .excel_workbook import t as excel_text

try:
    from analisi.roc import threshold_text
except Exception:  # pragma: no cover
    threshold_text = None

ANALYSIS_GRAPH_OPTIONS = {
    WEIBULL_AFT: (WEIBULL_GRAPH, False),
    ORDINAL_LOGIT: (ORDINAL_GRAPH, False),
    rmst.METHOD: (rmst.SHOW_GRAPH, rmst.DEFAULTS[rmst.SHOW_GRAPH]),
    kappa.METHOD: (kappa.SHOW_GRAPH, kappa.DEFAULTS[kappa.SHOW_GRAPH]),
    mean_permutation.METHOD: (mean_permutation.SHOW_GRAPH, mean_permutation.OPTIONS[mean_permutation.SHOW_GRAPH]),
}
SOURCE_XY = {BINARY_XY_RANGE, XML_ERROR_BARS, XML_BINDING_XY, XML_GENERATED_XY, XML_QC, ZIP_SPARSE_XY, ZIP_COLUMN,
             CLUSTERED_SCATTER, FIT_GRAPH, SAVED_AXES, SURVIVAL_GRAPH}


def _saved_recipe(run):
    return (run.method in SAVED_VIEWS
            or run.method in {anova_comparison_plot.METHOD, anova_diagnostics.METHOD, anova_grouped_plot.METHOD}
            or (run.method == SAVED_XY and not SOURCE_XY.isdisjoint(run.options)))


def preferred_view(run, result):
    """Graph methods open on their graph; analyses open on their tables (the graph is one click away)."""
    view = run_view(run.method)
    if view == "saved-layout":
        return view
    if run.method in ANALYSIS_GRAPH_OPTIONS:
        return "result"
    if run.method in GRAPH_METHODS or run.method in GRAPHING:
        return "graph"
    if result is not None and result.figure is not None and not result.tables:
        return "graph"
    return view


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


def export_graph(figure, path, settings=None, *, size_inches=None):
    """A graph at its own size, 300 dpi for images unless ``settings`` say otherwise, verified before it
    replaces the file."""
    from analisi.figure_export import MAX_MM, MM, export_figure
    if settings is None:
        suffix = Path(path).suffix.lower()
        fmt = {".svg": "svg", ".pdf": "pdf", ".tif": "tiff", ".tiff": "tiff"}.get(suffix, "png")
        settings = {"format": fmt, "dpi": 300} if fmt in {"png", "tiff"} else {"format": fmt}
        if size_inches is None:
            width, height = figure.get_size_inches()
            longest_mm = max(width, height) * MM
            if longest_mm > MAX_MM:
                # The interactive canvas can grow past the export limit on a wide display.
                scale = MAX_MM / longest_mm
                size_inches = (width * scale, height * scale)
    export_figure(figure, path, settings, size_inches=size_inches)


_KEEP = object()  # ``_ask``: keep the input of the analysis.


class SheetCanvas(FigureCanvasQTAgg):
    """The canvas of a page: it renders only once it has a size.

    A page builds its canvas, toolbar and inspector before Qt lays them out, and some of them ask for a redraw
    while doing so. Rendered at once, the figure was drawn at a size the canvas never has and drawn again when
    the page was shown: two full renders for every sheet opened (0.05 s each for an ordinary graph, more than a
    second for a million points). A request made before the first resize is dropped; that resize asks for the
    one draw, at the real size.
    """

    _laid_out = False

    def resizeEvent(self, event):
        self._laid_out = True
        super().resizeEvent(event)

    def draw_idle(self, *args, **kwargs):
        if self._laid_out:
            super().draw_idle(*args, **kwargs)


class PaperCanvas(SheetCanvas):
    """Change preview resolution while keeping the saved paper size."""

    def __init__(self, figure, paper):
        self.paper = tuple(paper)
        super().__init__(figure)

    def resizeEvent(self, event):
        size = event.size()
        if self.figure is None or size.isEmpty():
            return
        width, height = self.paper
        ratio = self.device_pixel_ratio
        # Cover the last pixel even when the physical canvas dimensions round up.
        self.figure.dpi = max((size.width() * ratio + 1) / width, (size.height() * ratio + 1) / height)
        super().resizeEvent(event)
        self.figure.set_size_inches(self.paper, forward=False)


class PaperPreview(QWidget):
    """Fit a page to the viewport without distorting its saved aspect ratio."""

    def __init__(self, canvas, paper):
        super().__init__()
        self.canvas = canvas
        self.canvas.setParent(self)
        self.canvas.setMinimumSize(0, 0)
        self.aspect = paper[0] / paper[1]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = min(self.width(), int(self.height() * self.aspect))
        height = int(width / self.aspect)
        self.canvas.setGeometry((self.width() - width) // 2, (self.height() - height) // 2, width, height)


class ImportedPaperPreview(QScrollArea):
    """Make long imported pages readable, with a choice to see the entire page."""

    def __init__(self, canvas, paper):
        super().__init__()
        self.canvas = canvas
        self.aspect = paper[0] / paper[1]
        self.fit_page = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumSize(0, 0)
        self.setWidget(canvas)
        self.canvas.installEventFilter(self)

    def set_fit_page(self, fit):
        self.fit_page = fit
        self.resize_paper()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_paper()

    def resize_paper(self):
        area = self.maximumViewportSize()
        # Bound the render size even for unusual page proportions.
        height_limit = area.height() if self.fit_page else 3 * area.height()
        width = min(area.width(), int(height_limit * self.aspect))
        if int(width / self.aspect) > area.height():
            width = min(width, area.width() - self.verticalScrollBar().sizeHint().width())
        self.canvas.resize(max(1, width), max(1, int(width / self.aspect)))

    def eventFilter(self, watched, event):
        if watched is self.canvas and event.type() == QEvent.Type.Wheel and self.verticalScrollBar().isVisible():
            self.wheelEvent(event)
            return event.isAccepted()
        return super().eventFilter(watched, event)


class Job:
    def __init__(self, future, control, done, label, session=None):
        self.future, self.control, self.done, self.label = future, control, done, label
        self.session = session  # The project tab that started it: its results never reach another tab.


class PlotNavigation(NavigationToolbar2QT):
    """Tools for the visible area of the plot. Trama handles styles and exports."""

    toolitems = tuple(item for item in NavigationToolbar2QT.toolitems
                      if item[3] in {"home", "back", "forward", "pan", "zoom"})
    _fit_views = WeakKeyDictionary()

    def __init__(self, canvas, parent):
        super().__init__(canvas, parent)
        self._first_draw = canvas.mpl_connect("draw_event", self._store_first_view)

    def _store_first_view(self, _event):
        self.canvas.mpl_disconnect(self._first_draw)
        self._remember_fit_view()

    def _remember_fit_view(self):
        # The same graph figure can be reopened in a new Qt canvas. Keep its original bounds until its
        # axis settings change, so a zoomed figure still has a full view to return to.
        figure = self.canvas.figure
        keys = ("axis", "xscale", "yscale", AXIS_BREAKS)
        signature = tuple((id(ax), *(getattr(ax, "_tramastat_style", {}).get(key) for key in keys))
                          for ax in figure.axes)
        entry = self._fit_views.get(figure)
        if entry is None or entry[0] != signature:
            self.update()
            self.push_current()
            self._fit_views[figure] = (signature, self._nav_stack())
        elif self._nav_stack() is None:
            self._nav_stack.push(entry[1])
            self.set_history_buttons()

    def home(self, *args):
        self._remember_fit_view()
        super().home(*args)

    def release(self):
        for cid in ("_id_press", "_id_release", "_id_drag", "_first_draw"):
            handle = getattr(self, cid, None)
            if handle is not None:
                self.canvas.mpl_disconnect(handle)
                setattr(self, cid, None)
        if getattr(self.canvas, "toolbar", None) is self:
            self.canvas.toolbar = None

    def configure_fit(self, *, layout, preview):
        if isinstance(preview, ImportedPaperPreview):
            self.fit_action = self.addAction(qt("qt.fit_entire_page"))
            self.fit_action.setCheckable(True)
            self.fit_action.toggled.connect(preview.set_fit_page)
            self.fit_action.triggered.connect(lambda checked: self.home() if checked else None)
        else:
            self.fit_action = self._actions["home"]
            label = qt("qt.fit_entire_page" if layout else "qt.fit_graph")
            self.fit_action.setText(label)
            self.fit_action.setToolTip(label)


class Page(QWidget):
    """A sheet: title, subtitle, a row of actions and the content."""

    def __init__(self, title, subtitle=""):
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(10, 8, 10, 8)
        self.layout_.setSpacing(5)
        if title:
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
        self.worksheet_preview = None

    def button(self, text, handler, *, primary=False, icon=None):
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        if icon:
            button.setIcon(theme.icon(icon, "on_accent" if primary else None, 16))
        button.clicked.connect(handler)
        self.actions_row.addWidget(button)
        return button

    def command(self, action):
        button = QToolButton()
        button.setObjectName("pageAction")
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        if action.menu() is not None:
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
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
        self.actions_row.parentWidget().setVisible(self.actions_row.count() > 0)

    def release(self):
        """Detach matplotlib figures from the canvases that are about to be deleted."""
        if self.worksheet_preview is not None:
            self.worksheet_preview.release()
        for toolbar in self.findChildren(PlotNavigation):
            toolbar.release()
        for canvas in self.canvases:
            figure = canvas.figure
            if figure.canvas is canvas:
                FigureCanvasBase(figure)
        self.canvases.clear()


class MainWindow(QMainWindow):
    def __init__(self, *, recovery=None):
        super().__init__()
        self._release_gc = gui_gc.attach(self)
        self.recovery = recovery  # Recovery copies (trama_qt/recovery.py); None in tests and smoke runs.
        self.sessions = Sessions(Project())  # One per project tab; ``project`` and ``selected`` are the active one's.
        self.project_number = 1
        self._queued = []  # Files that arrived (drop, command line) while a calculation ran.
        self._deferred = []  # Tab changes that wait for the recalculation a just-typed edit started.
        self._close_pending = False
        self.page = None
        self.plot_tools = None
        self.sheet = None
        self.formula_editor = None
        self.result_tabs = None
        self.table_font = font_preference(config_path())
        self.table_zoom = 100
        self.job = None
        self.repeat_dialog = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Trama-Qt")
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._poll)
        self.actions = {}
        self.icons = {}
        self.printing = PrintCommands(self)
        self.inspector = None
        self.gallery = None  # The open gallery of graphs and layouts, in place of the page (trama_qt/gallery.py).
        self.gallery_view = {"kind": None, "text": ""}  # Its filters: a state of the view, never saved.
        self.info_editor = None
        self.worksheet_notes = None
        self.navigator_width = 244
        self.navigator_open = True
        self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(str(theme.ASSETS / "trama.png")))
        self._build()
        self.show_home()
        theme.SIGNALS.changed.connect(self._theme_changed)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            self.resize(min(1280, screen.width() - 40), min(820, screen.height() - 60))
        else:
            self.resize(1180, 760)
        if self.recovery is not None:
            self.recovery.attach(self)

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
        self.actions["new_project"].setShortcuts([QKeySequence("Ctrl+N"), QKeySequence("Ctrl+Shift+N")])
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
        a("recover", recovery_text("recover"), self.recover_projects, icon="history", tip=recovery_text("recover_tip"))
        a("recovery_settings", recovery_text("settings"), self.recovery_settings, icon="save",
          tip=recovery_text("settings_tip"))
        a("save_template", template_text("save_action"), self.save_template, icon="file-down",
          tip=template_text("save_tip"))
        a("new_from_template", template_text("new_action"), self.new_from_template, icon="sparkles",
          tip=template_text("new_tip"))
        for key in ("save_template", "new_from_template"):  # Short ribbon captions; menus and search keep the full text.
            self.actions[key].setIconText(template_text(f"{key}_short"))
        a("export", tr("command.export"), self.export, icon="upload", shortcut="Ctrl+Shift+E")
        a("export_options", tr("command.export_with_options"), self.export_with_options, icon="download")
        a("export_pdf", tr("command.export_multiple_pdf"), self.export_pdf_bundle, icon="file-down")
        a("export_batch", batch_text("command"), self.export_batch, icon="copy")
        a("export_report", report_text("command"), self.export_report, icon="book-open")
        a("print", qt("qt.print_action"), self.printing.print_sheet, shortcut="Ctrl+P")
        a("print_preview", qt("qt.print_preview"), self.printing.preview)
        a("page_setup", qt("qt.page_setup"), self.printing.page_setup)
        for app in ("Word", "PowerPoint"):
            a(f"send_{app.lower()}", qt("qt.office_action", app=app), lambda app=app: self.printing.send(app),
              tip=qt("qt.office_tip" if office.ON_WINDOWS else "qt.office_windows", app=app))
        a("import_excel", excel_text("Import Excel workbook…"), self.import_excel_workbook, icon="table-2")
        from . import source_link as linked_source
        a("refresh_source", linked_source.t("Update from file…"), lambda: linked_source.update_from_file(self),
          icon="git-compare", shortcut="Ctrl+Shift+U",
          tip=linked_source.t("Read the linked CSV or TSV file again and review the changes before applying them"))
        a("source_link", linked_source.t("Source link…"), lambda: linked_source.manage(self), icon="sliders-horizontal",
          tip=linked_source.t("Show, change or remove the file this worksheet is linked to"))
        a("export_excel", excel_text("Export Excel workbook…"), self.export_excel_workbook, icon="sheet")
        a("language", tr("command.language"), self.choose_language, icon="type")
        a("processes", tr("processes.command"), self.choose_processes, icon="sliders-horizontal")
        a("about", qt("qt.about"), self.about, icon="info")
        a("help_shortcuts", qt("qt.shortcuts"), self.show_shortcuts, shortcut="F1")
        a("exit", tr("command.exit"), self.close, icon="x", shortcut="Ctrl+Q")
        a("undo", tr("command.undo"), self.undo, icon="undo-2", shortcut="Ctrl+Z")
        a("redo", tr("command.redo"), lambda: self.undo(redo=True), icon="redo-2", shortcut="Ctrl+Y")
        a("cut", tr("command.cut_cells"), lambda: self._sheet_call("cut"), icon="scissors")
        a("copy", tr("command.copy_cells"), lambda: self._workspace_clipboard("copy"), icon="copy")
        a("paste", tr("ribbon.paste"), lambda: self._workspace_clipboard("paste"), icon="clipboard-paste")
        a("paste_special", tr("command.paste_special"), lambda: self._sheet_call("paste", special=True),
          icon="clipboard-paste", shortcut="Ctrl+Shift+V")
        a("paste_transpose", tr("command.paste_transpose"), lambda: self._sheet_call("paste", transpose=True),
          icon="arrow-up-down", shortcut="Ctrl+Shift+T")
        a("paste_table", tr("command.paste_as_new_table"), self.paste_table, icon="table-2")
        a("clear_cells", tr("command.clear_selected_cells"), lambda: self._sheet_call("clear"), icon="trash-2")
        a("new_table", tr("command.new_table"), self.choose_table, icon="table", shortcut="Ctrl+T")
        a("category_order", tr("command.category_order"), self.edit_category_order, icon="arrow-up-down")
        a("variable_properties", tr("command.variable_properties"), self.edit_variable_properties,
          icon="sliders-horizontal")
        a("delete_columns", qt("qt.delete_columns"), self.delete_columns, icon="trash-2")
        a("new_info", tr("command.new_info"), self.new_info, icon="info")
        a("info_properties", tr("command.info_properties"), self.info_properties, icon="sliders-horizontal")
        from .info_editor import t as info_text

        for key, label, kind, icon in (("family_data", "source_table", "data", "table"),
                                        ("family_info", "linked_info", "info", "info"),
                                        ("family_results", "family_results", "result", "sigma"),
                                        ("family_graphs", "graphs", "graph", "chart-line"),
                                        ("family_gallery", "family_gallery", None, "gallery-thumbnails")):
            a(key, tr(f"command.{label}"), lambda kind=kind: self.browse_family(kind), icon=icon)
        a("duplicate_family", ui("Duplicate family…"), self.duplicate_family, icon="copy")
        a("save_family", ui("Save family as…"), self.save_family_as, icon="save")
        a("insert_row", qt("qt.insert_row"), self.insert_row, icon="rows-3")
        a("insert_column", qt("qt.insert_column"), self.insert_column, icon="columns-3")
        a("create_numeric_series", qt("qt.create_numeric_series"), self.create_numeric_series, icon="hash")
        a("formula", ui("Formula…"), self.edit_formula, icon="sigma")
        a("delete_rows", qt("qt.delete_rows"), self.delete_rows, icon="trash-2")
        a("move_rows_up", qt("qt.move_rows_up"), self.move_rows_up, icon="chevron-up", shortcut="Alt+Up")
        a("move_rows_down", qt("qt.move_rows_down"), self.move_rows_down, icon="chevron-down", shortcut="Alt+Down")
        a("move_rows_first", qt("qt.move_rows_first"), lambda: self.move_rows_to_edge(first=True))
        a("move_rows_last", qt("qt.move_rows_last"), lambda: self.move_rows_to_edge(first=False))
        a("sort_rows", qt("qt.sort_rows"), self.sort_rows, icon="arrow-up-down")
        a("sort_by_x", qt("qt.sort_by_x"), self.sort_by_x)
        a("sort_by_row_title", qt("qt.sort_by_row_title"), self.sort_by_row_title)
        a("reverse_rows", qt("qt.reverse_rows"), self.reverse_rows)
        a("reset_row_height", qt("qt.reset_row_height"), self.reset_row_height, shortcut="Alt+0")
        a("exclude", tr("ribbon.exclude"), self.toggle_exclusion, icon="filter", shortcut="Ctrl+E")
        a("analyze", tr("ribbon.analyze"), self.analyze, icon="sigma", shortcut="Ctrl+Shift+A")
        a("power", tr("command.power"), lambda: self.analyze(method=power_plan.METHOD, only=power_plan.METHOD),
          icon="chart-line")
        a("paired_power", tr("command.paired_power"),
          lambda: self.analyze(method=mcnemar_power.METHOD, only=mcnemar_power.METHOD), icon="chart-line")
        a("simulate", tr("command.simulate"), self.simulate_data, icon="table-2")
        a("monte_carlo", tr("command.monte_carlo"), lambda: self.analyze(method=MONTE_CARLO, only=MONTE_CARLO),
          icon="sigma")
        a("transpose_xy", tr("command.transpose_xy"), lambda: self.analyze(method=TRANSPOSE_XY, only=TRANSPOSE_XY),
          icon="arrow-up-down")
        a("plot_function", tr("command.plot_function"), lambda: self.analyze(method=PLOT_FUNCTION, only=PLOT_FUNCTION),
          icon="chart-line")
        a("load_example", tr("command.load_example"), self.load_example, icon="sparkles")
        a("new_graph", tr("command.new_graph"), self.new_graph, icon="chart-line", shortcut="Ctrl+G")
        a("change", tr("command.change_parameters"), self.change_parameters, icon="sliders-horizontal",
          shortcut="Ctrl+Shift+P")
        a("change_graph_type", qt("qt.change_graph_type"), self.change_graph_type, icon="chart-column")
        a("format_graph", tr("graph.format.title"), self.format_graph, icon="palette", shortcut="Ctrl+Shift+F")
        from .graph_style_preset_dialog import t as preset_text
        a("graph_style_presets", preset_text("action"), self.graph_style_presets, icon="sparkles")
        from .batch_figure_styles_dialog import t as batch_style_text
        a("batch_figure_styles", batch_style_text("action"), self.batch_figure_styles, icon="sparkles")
        a("inspector", tr("graph.inspector.title"), self.toggle_inspector, icon="paintbrush", shortcut="Ctrl+Shift+I")
        a("annotations", tr("command.graph_annotations"), self.edit_annotations, icon="type")
        a("shapes", tr("shape.button"), self.edit_shapes, icon="shapes")
        a("linked_table", tr("command.linked_table"), self.edit_linked_tables, icon="table-2")
        a("linked_table_selection", tr("command.linked_table_selection"), self.insert_linked_table_from_selection,
          icon="table-2")
        a("arrange_shapes", tr("command.arrange_shapes"), self.arrange_shapes, icon="shapes")
        a("pairwise", tr("command.pairwise"), self.pairwise_comparisons, icon="git-compare")
        a("compact_letters", tr("command.compact_letters"), lambda: self.pairwise_comparisons(letters=True),
          icon="type")
        a("new_layout", tr("command.new_layout"), self.new_layout, icon="layout-grid", shortcut="Ctrl+L")
        a("edit_layout", tr("command.edit_layout"), lambda: self.new_layout(edit=True), icon="layout-grid")
        a("recalculate", qt("qt.recalculate"), self.recalculate, icon="history", shortcut="F9")
        a("use_result", qt("qt.use_as_data"), self.use_result_as_data, icon="table-2")
        a("analysis_graph", qt("qt.show_analysis_graph"), lambda: self.switch_run_view("graph"), icon="chart-line")
        a("analysis_tables", tr("command.analysis_results"), lambda: self.switch_run_view("result"), icon="sigma")
        a("fit_graph", qt("qt.fit_graph"), self.fit_preview, icon="house")
        a("fit_layout_page", qt("qt.fit_entire_page"), self.fit_preview, icon="layout-grid")
        a("plot_margins", qt("qt.plot_margins"), self.adjust_plot_margins, icon="sliders-horizontal")
        a("analyze_result", tr("chain.analyze_result"), self.analyze_result_table, icon="git-compare")
        a("source_analysis", tr("chain.source_analysis"), self.source_analysis, icon="chevron-up")
        a("change_input", tr("chain.change_input"), self.change_input_result, icon="arrow-up-down")
        a("repeat_analysis", repeat_text("command"), self.repeat_analysis, icon="copy", tip=repeat_text("tip"))
        self.actions["repeat_analysis"].setIconText(repeat_text("short"))
        a("navigator", tr("command.toggle_navigator"), self.toggle_navigator, icon="panel-bottom", shortcut="Ctrl+F1")
        for command, icon in (("duplicate", "copy"), ("rename", "type"), ("delete", "trash-2"),
                              ("move_up", "chevron-up"), ("move_down", "chevron-down"),
                              ("freeze", "lock")):
            a(f"sheet_{command}", qt(f"qt.sheet_{command}"),
              lambda command=command: self._worksheet_command(self.selected, command), icon=icon)
        a("sheet_notes", qt("qt.sheet_notes"), self.open_worksheet_notes, icon="book-open")
        a("find_sheet", tr("nav.search"), self.focus_sheet_search, icon="search", shortcut="Ctrl+F")
        a("combined_navigator", tr("command.toggle_data_results"), self.toggle_combined_navigator,
          icon="panel-bottom").setCheckable(True)
        a("previous_sheet", tr("command.previous_sheet"), lambda: self.step_sheet(-1), icon="arrow-left",
          shortcut="Alt+Left").setShortcuts([QKeySequence("Alt+Left"), QKeySequence("Ctrl+PgUp")])
        a("next_sheet", tr("command.next_sheet"), lambda: self.step_sheet(1), icon="arrow-right",
          shortcut="Alt+Right").setShortcuts([QKeySequence("Alt+Right"), QKeySequence("Ctrl+PgDown")])
        themes = QActionGroup(self)
        for mode, icon in (("system", "monitor"), ("light", "sun"), ("dark", "moon")):
            action = a(f"theme_{mode}", qt(f"qt.theme_{mode}"), lambda mode=mode: theme.set_mode(mode), icon=icon,
                       tip=qt("qt.theme_hint"))
            action.setCheckable(True)
            action.setChecked(theme.STATE["mode"] == mode)
            themes.addAction(action)
        a("gallery", gallery_text("action"), self.toggle_gallery, icon="gallery-thumbnails", shortcut="Ctrl+Shift+G",
          tip=gallery_text("tip"))
        a("table_font", tr("command.table_font"), self.choose_table_font)
        a("cell_background", tr("command.cell_background"), self.change_cell_background)
        a("clear_cell_background", tr("command.clear_cell_background"), lambda: self.change_cell_background(clear=True))
        a("number_format", tr("command.number_format"), self.change_number_format, icon="hash")
        for key, step, shortcut in (("sheet_zoom_in", 1, "Ctrl+="), ("sheet_zoom_out", -1, "Ctrl+-"),
                                    ("sheet_zoom_reset", 0, "Ctrl+0")):
            a(key, tr(f"command.{key}"), lambda step=step: self.zoom_table(step), shortcut=shortcut)
        a("worksheet_preview", tr("modern.preview"), self.toggle_worksheet_preview).setCheckable(True)
        a("search", qt("qt.search_command"), self.focus_search, shortcut="Ctrl+K")
        for name, method in (("descriptive", "Descriptive statistics"), ("ttest", "t-test"),
                             ("anova", "One-way ANOVA"), ("correlation", "Correlation"),
                             ("correlation_matrix", CORRELATION_MATRIX),
                             ("linear", "Linear regression"), ("nonlinear", "Nonlinear regression"),
                             ("survival", "Kaplan–Meier survival"), ("contingency", "Contingency table")):
            a(name, method_label(method), lambda method=method: self.analyze(method=method))
        self.drawing = GraphDrawing(self)  # Pointer tools of the graph canvas: actions before the ribbon.
        self.drawing.create_actions()
        self.table_move = LinkedTableCanvas(self)
        self.table_move.create_actions()
        self.text_format = TextFormat(self)  # The Text group: font, size, colour, bold, italic, underline, alignment.
        self.text_format.create_actions()
        self.command_menus = build_menus(self)
        self.search_dialog = None

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.toolbar = ClassicToolbar(self.actions, self.text_format)
        root.addWidget(self.toolbar)
        self.project_strip = self._project_strip()
        root.addWidget(self.project_strip)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setContentsMargins(0, 0, 0, 0)
        body.setHandleWidth(4)
        self.body = body
        nav_card = QFrame()
        nav_card.setObjectName("classicNavigator")
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(2, 2, 2, 2)
        nav_layout.setSpacing(2)
        self.sheet_search = QLineEdit(nav_card)
        self.sheet_search.setPlaceholderText(tr("nav.search"))
        self.sheet_search.setAccessibleName(tr("nav.search"))
        self.sheet_search.setClearButtonEnabled(True)
        self.sheet_search.addAction(theme.classic_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.sheet_search.textChanged.connect(self.filter_sheets)
        nav_layout.addWidget(self.sheet_search)
        self.navigator = QTreeWidget()
        self.navigator.setObjectName("navigator")
        self.navigator.setHeaderHidden(True)
        self.navigator.setRootIsDecorated(True)
        self.navigator.setIndentation(16)
        self.navigator.setIconSize(theme.icon_size(16))
        self.navigator.itemClicked.connect(self._navigate)
        self.navigator.itemActivated.connect(self._navigate)
        self.navigator.itemExpanded.connect(lambda item: self._remember_folder(item, True))
        self.navigator.itemCollapsed.connect(lambda item: self._remember_folder(item, False))
        self.navigator.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.navigator.customContextMenuRequested.connect(self._navigator_menu)
        nav_layout.addWidget(self.navigator)
        self.nav_card = nav_card
        body.addWidget(nav_card)
        page_card = QFrame()
        page_card.setObjectName("classicSheet")
        self.page_layout = QVBoxLayout(page_card)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        body.addWidget(page_card)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([self.navigator_width, 900])
        root.addWidget(body, 1)
        self.setCentralWidget(central)

        status = self.statusBar()
        status.setSizeGripEnabled(True)
        self.sheet_previous = QToolButton()
        self.sheet_next = QToolButton()
        self.sheet_picker = QComboBox()
        self.sheet_picker.setAccessibleName(qt("qt.sheet_picker"))
        self.sheet_picker.setMinimumContentsLength(9)
        self.sheet_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sheet_picker.setMaximumWidth(210)
        self.sheet_picker.activated.connect(self._pick_sheet)
        self.gallery_button = QToolButton()
        for button, key, icon in ((QToolButton(), "navigator", "navigator"), (self.gallery_button, "gallery", "gallery"),
                                  (self.sheet_previous, "previous_sheet", "prev"), (self.sheet_next, "next_sheet", "next"),
                                  (QToolButton(), "family_gallery", "link")):
            button.setProperty("statusTool", True)
            button.setDefaultAction(self.actions[key])
            button.setIcon(theme.classic_icon(icon))
            button.setAccessibleName(self.actions[key].text())
            status.addWidget(button)
        status.addWidget(self._status_divider())
        self.section_buttons = {}
        for kind, key, icon in (("data", "data_tables", "data"), ("info", "info_sheets", "info"),
                                ("result", "results", "result"), ("graph", "graphs", "graph"),
                                ("layout", "layouts", "layout")):
            button = self.section_buttons[kind] = QToolButton()
            button.setProperty("statusTool", True)
            button.setIcon(theme.classic_icon(icon))
            label = tr("nav.graphs") if kind == "graph" else tr(f"bar.{key}")
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(lambda _checked=False, kind=kind: self.open_section(kind))
            status.addWidget(button)
        status.addWidget(self._status_divider())
        status.addWidget(self.sheet_picker)
        status.addWidget(self._status_divider())
        self.cell_label = QLabel("")
        status.addWidget(self.cell_label)
        self.message = StatusLabel(qt("qt.ready"))
        self.message.setObjectName("statusMessage")
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._message_expired)
        status.addWidget(self.message, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(100)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        status.addPermanentWidget(self.progress)
        self.cancel_button = QToolButton()
        self.cancel_button.setText(tr("bar.cancel_calculation"))
        self.cancel_button.clicked.connect(self.cancel_calculation)
        self.cancel_button.setVisible(False)
        self.cancel_button.ensurePolished()
        self.cancel_button.setMinimumWidth(self.cancel_button.minimumSizeHint().width())
        status.addPermanentWidget(self.cancel_button)

    @staticmethod
    def _status_divider():
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setObjectName("statusDivider")
        divider.setFixedHeight(16)
        return divider

    def _project_strip(self):
        """One tab per open project, with New beside the last tab; each tab closes its own project."""
        strip = QFrame()
        strip.setObjectName("projectStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(2)
        tabs = self.project_tabs = QTabBar()
        tabs.setObjectName("projectTabs")
        tabs.setAccessibleName(qt("qt.projects"))
        tabs.setDrawBase(False)
        tabs.setExpanding(False)
        tabs.setMovable(False)
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        tabs.addTab("")
        tabs.currentChanged.connect(self._project_tab_changed)
        tabs.tabCloseRequested.connect(self._project_tab_close)  # Also reached by the × of each tab.
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

    def _theme_changed(self):
        """Colours that are not in the style sheet (navigator headings) are redrawn in the new theme."""
        for mode in theme.MODES:
            self.actions[f"theme_{mode}"].setChecked(theme.STATE["mode"] == mode)
        self.refresh()

    # == small helpers ============================================================================
    def error(self, error):
        QMessageBox.warning(self, "Trama", str(error))

    def status(self, text):
        self.message.setText(str(text))
        self.message.setProperty("fresh", bool(text))
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self._message_timer.start(6000)  # A message fades back to "Ready" after six seconds.

    def _message_expired(self):
        if self.job is not None:  # A calculation is still running: its message stays until it ends.
            self._message_timer.start(6000)
            return
        self.message.setText(qt("qt.ready"))
        self.message.setProperty("fresh", False)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    def busy(self, *, warn=True):
        if self.job is not None and warn:
            self.status(qt("qt.wait"))
        return self.job is not None

    def focus_sheet_search(self):
        if self.gallery is not None:
            self.gallery.focus_search()
            return
        if not self.navigator_open:
            self.toggle_navigator()
        self.sheet_search.setFocus()
        self.sheet_search.selectAll()

    def filter_sheets(self, text):
        self.sessions.active.sheet_filter = text
        needle = text.strip().casefold()
        with QSignalBlocker(self.navigator):
            self.search_results.takeChildren()
            if needle:
                for title, ref, icon in self.navigator_entries:
                    if needle in title.casefold():
                        self._entry(self.search_results, title, ref, icon)
            self.search_results.setExpanded(True)
            for index in range(self.navigator.topLevelItemCount()):
                item = self.navigator.topLevelItem(index)
                item.setHidden(bool(needle) and item is not self.search_results)

    def focus_search(self):
        if self.search_dialog is None:
            from .command_search import CommandSearchDialog
            self.search_dialog = CommandSearchDialog(self)
        self.search_dialog.open_search()

    def _sheet_call(self, name, **options):
        if self.sheet is not None:
            getattr(self.sheet, name)(**options)

    def _workspace_clipboard(self, operation):
        if self.selected and self.selected[0] == "graph":
            self.drawing.clipboard_action(operation)
        elif operation == "copy" and self.result_tabs is not None:
            self.result_tabs.currentWidget().copy()
        else:
            self._sheet_call(operation)

    def toggle_combined_navigator(self):
        self.sessions.active.combined_navigator = self.actions["combined_navigator"].isChecked()
        self.refresh()

    def toggle_navigator(self):
        if self.navigator_open:
            self.navigator_width = self.body.sizes()[0] or self.navigator_width
            self.nav_card.hide()
        else:
            self.nav_card.show()
            self.body.setSizes([self.navigator_width, max(0, self.body.width() - self.navigator_width)])
        self.navigator_open = not self.navigator_open

    def update_title(self):
        title = self.project.title
        if self.selected and self.selected[0] == "data":
            title = f"{self.selected[1]} — {title}"
        marker = "• " if self.project.dirty else ""
        self.setWindowTitle(f"{marker}{title} — Trama beta")
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
            for index in range(bar.count()):
                if bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is None:
                    bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, self._tab_close_button())
            for index, (caption, tip) in enumerate(self.sessions.labels()):
                if bar.tabText(index) != caption:
                    bar.setTabText(index, caption)
                bar.setTabToolTip(index, tip)
                bar.setTabData(index, self.sessions[index].key)
            bar.setCurrentIndex(self.sessions.index(self.sessions.active))
        finally:
            bar.blockSignals(False)

    def update_actions(self):
        kind = self.selected[0] if self.selected and self.gallery is None else None  # The gallery shows no sheet.
        on_run = kind in RUN_KINDS
        data = kind == "data"
        locked = bool(kind and self.project.sheet_locked(self.selected))
        editable = data and not locked and not stored_legacy_view(self.project.tables[self.selected[1]])
        idle = self.job is None
        self.actions["sheet_notes"].setEnabled(kind is not None and idle)
        for command in ("duplicate", "rename", "delete", "move_up", "move_down", "freeze"):
            action = self.actions[f"sheet_{command}"]
            action.setEnabled(bool(kind and idle and self._worksheet_command_available(self.selected, command)))
            if command == "freeze":
                action.setText(qt("qt.sheet_unfreeze" if locked else "qt.sheet_freeze"))
        if self.formula_editor is not None:
            self.formula_editor.apply_button.setEnabled(idle)
        self.gallery_button.setVisible(self.gallery is None)
        self.sheet_picker.setEnabled(idle and self.sheet_picker.count() > 0)
        sections = {kind for kind, _ in self.sheet_refs.values()}
        if "saved-layout" in sections:
            sections.add("layout")
        for section_kind, button in self.section_buttons.items():
            button.setEnabled(idle and section_kind in sections)
        self.actions["previous_sheet"].setEnabled(idle and self._sheet_history_target(-1) is not None)
        self.actions["next_sheet"].setEnabled(idle and self._sheet_history_target(1) is not None)
        self.actions["combined_navigator"].setChecked(self.sessions.active.combined_navigator)
        for key in ("cut", "paste_special", "paste_transpose", "clear_cells", "insert_row",
                    "insert_column", "create_numeric_series", "delete_rows", "delete_columns",
                    "exclude", "formula", "category_order"):
            self.actions[key].setEnabled(editable and idle)
        self._update_row_actions(data, editable, idle)
        self.actions["variable_properties"].setEnabled(
            editable and idle and self.project.tables[self.selected[1]].table_format == "multivariable")
        has_table = (data and self.sheet is not None) or (kind == "result" and self.result_tabs is not None)
        for key in ("sheet_zoom_in", "sheet_zoom_out", "sheet_zoom_reset"):
            self.actions[key].setEnabled(has_table)
        for key in ("cell_background", "clear_cell_background", "number_format"):
            self.actions[key].setEnabled(has_table and idle and not locked)
        self.text_format.update()
        graph_clipboard = kind == "graph" and self.drawing.problem() is None
        self.actions["copy"].setEnabled(has_table or graph_clipboard)
        self.actions["paste"].setEnabled((editable and idle) or graph_clipboard)
        for key in ("duplicate_family", "save_family", "family_data", "family_info", "family_results",
                    "family_graphs", "family_gallery"):
            self.actions[key].setEnabled(kind is not None and idle)
        self.actions["info_properties"].setEnabled(kind == "info" and idle)
        changeable = kind in {"result", "graph"} and not locked and not _saved_recipe(self.project.runs[self.selected[1]])
        self.actions["change"].setEnabled(changeable and idle)
        type_problem = self.project.graph_type_problem(self.project.runs[self.selected[1]]) if kind == "graph" else None
        change_type = self.actions["change_graph_type"]
        change_type.setEnabled(kind == "graph" and idle and type_problem is None)
        change_type.setToolTip(type_problem or change_type.text())
        graph = kind == "graph" and self.project.graph_format_problem(self.project.runs[self.selected[1]]) is None
        self.actions["format_graph"].setEnabled(graph and idle)
        self.actions["graph_style_presets"].setEnabled(graph and idle)
        from .gallery_catalog import graph_runs
        self.actions["batch_figure_styles"].setEnabled(idle and bool(graph_runs(self.project)))
        self.actions["inspector"].setEnabled(graph and idle)
        self.actions["worksheet_preview"].setEnabled(data and idle)
        if data and self.page is not None and self.page.worksheet_preview is not None:
            self.page.worksheet_preview.set_busy()
        self.actions["annotations"].setEnabled(graph and idle and self.project.runs[self.selected[1]].method
                                               not in LEGACY_GRAPH_METHODS)
        self.actions["shapes"].setEnabled(self.actions["annotations"].isEnabled())
        self.actions["linked_table"].setEnabled(idle and (self.actions["annotations"].isEnabled() or kind == "layout"))
        self.actions["arrange_shapes"].setEnabled(idle and self.drawing.can_arrange())
        for key in ("pairwise", "compact_letters"):
            self.actions[key].setEnabled(graph and idle)
        if self.inspector is not None:
            self.inspector.setEnabled(idle)
        self.actions["new_layout"].setEnabled(idle and bool(self.project.layout_candidates()))
        self.actions["edit_layout"].setEnabled(idle and kind == "layout")
        self.actions["recalculate"].setEnabled((on_run and not locked or kind == "layout") and idle)
        self.actions["use_result"].setEnabled(kind == "result" and idle)
        run = self.project.runs[self.selected[1]] if kind in {"result", "graph"} else None
        result = run.result if run is not None else None
        self.actions["analysis_graph"].setEnabled(idle and kind == "result" and result is not None
                                                   and result.figure is not None and not self.project.sheet_state(("graph", self.selected[1])).get("hidden"))
        self.actions["analysis_tables"].setEnabled(idle and kind == "graph" and (
            (run_view(run.method) == "result" or XML_GENERATED_XY in run.options)
            and not self.project.sheet_state(("result", self.selected[1])).get("hidden")))
        plot = idle and self.gallery is None and self.plot_tools is not None
        layout_plot = plot and kind in {"layout", "saved-layout"}
        self.actions["fit_graph"].setEnabled(plot and kind == "graph")
        fit_page = self.actions["fit_layout_page"]
        fit_page.setEnabled(layout_plot)
        fit_page.setCheckable(layout_plot and self.plot_tools.fit_action.isCheckable())
        fit_page.setChecked(layout_plot and self.plot_tools.fit_action.isChecked())
        self.actions["plot_margins"].setEnabled(plot and not locked)
        chained = kind in {"result", "graph"} and self.project.runs[self.selected[1]].source is not None
        self.actions["analyze_result"].setEnabled(kind == "result" and idle)
        self.actions["source_analysis"].setEnabled(chained)
        self.actions["change_input"].setEnabled(changeable and idle and (kind == "result" or chained))
        self.actions["repeat_analysis"].setEnabled(changeable and idle and self.project.runs[self.selected[1]].slot >= 0)
        has_data = bool(self.project.tables)
        for key in ("analyze", "new_graph", "descriptive", "ttest", "anova", "correlation", "linear", "nonlinear",
                    "survival", "contingency", "correlation_matrix", "monte_carlo", "transpose_xy"):
            self.actions[key].setEnabled(has_data and idle)
        for key in ("power", "paired_power", "simulate", "plot_function", "paste_table", "load_example",
                    "new_table", "new_info"):
            self.actions[key].setEnabled(idle)
        if kind == "info" and self.info_editor is not None:
            doc = self.info_editor.notes.document()
            self.actions["undo"].setEnabled(idle and doc.isUndoAvailable())
            self.actions["redo"].setEnabled(idle and doc.isRedoAvailable())
        else:
            undo_source = self._history_target(redo=False)
            redo_source = self._history_target(redo=True)
            self.actions["undo"].setEnabled(idle and self.gallery is None and undo_source is not None)
            self.actions["redo"].setEnabled(idle and self.gallery is None and redo_source is not None)
        for key in ("open", "import", "new_project", "save", "save_as", "close_project", "import_excel"):
            self.actions[key].setEnabled(idle)
        linked = editable and self.project.tables[self.selected[1]].source_link is not None
        self.actions["refresh_source"].setEnabled(linked and idle)
        self.actions["source_link"].setEnabled(idle and editable and (
            linked or self.project.tables[self.selected[1]].table_format == "multivariable"))
        self.actions["export_excel"].setEnabled(idle and bool(self.project.tables or self.project.runs))
        for key in ("next_project", "previous_project"):  # Switching waits for the calculation (Cancel stays on).
            self.actions[key].setEnabled(idle and len(self.sessions) > 1)
        self.actions["new_project"].setEnabled(idle and not self.sessions.full())
        self.actions["recover"].setEnabled(idle and self.recovery is not None)
        self.actions["recovery_settings"].setEnabled(self.recovery is not None)
        sync_template_actions(self)
        self.project_tabs.setEnabled(idle)
        self.new_tab_button.setEnabled(idle and not self.sessions.full())
        self.actions["export"].setEnabled(kind is not None)
        self.actions["export_options"].setEnabled(kind in {"graph", "layout", "saved-layout"})
        for key in ("print", "print_preview"):
            self.actions[key].setEnabled(kind is not None and idle)
        for key in ("send_word", "send_powerpoint"):
            self.actions[key].setEnabled(office.ON_WINDOWS and kind in FIGURE_KINDS and idle)
        self.actions["export_pdf"].setEnabled(idle and (bool(self.project.layouts) or any(
            run.result is not None and run.result.figure is not None for run in self.project.runs)))
        self.actions["export_batch"].setEnabled(self.actions["export_pdf"].isEnabled())
        self.actions["export_report"].setEnabled(idle and bool(self.project.runs or self.project.layouts))
        self.drawing.sync()
        self.table_move.sync()

    # == navigator ================================================================================
    def _navigator_folders(self):
        iterator = QTreeWidgetItemIterator(self.navigator, QTreeWidgetItemIterator.IteratorFlag.HasChildren)
        while (item := iterator.value()) is not None:
            yield item
            iterator += 1

    def _folder_key(self, item):
        path = []
        while item is not None:
            ref = item.data(0, Qt.ItemDataRole.UserRole)
            path.append(self._sheet_identity(tuple(ref)) if ref else item.text(0))
            item = item.parent()
        return tuple(reversed(path))

    def _remember_folder(self, item, expanded):
        if item is not self.search_results:
            collapsed = self.sessions.active.collapsed_folders
            key = self._folder_key(item)
            if expanded:
                collapsed.discard(key)
            else:
                collapsed.add(key)

    def expand_navigator(self, expanded):
        collapsed = self.sessions.active.collapsed_folders
        with QSignalBlocker(self.navigator):
            if expanded:
                collapsed.clear()
                self.navigator.expandAll()
            else:
                for item in self._navigator_folders():
                    self._remember_folder(item, False)
                self.navigator.collapseAll()

    def _section(self, title):
        item = QTreeWidgetItem([title])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        icon = {tr("nav.family"): "link", tr("nav.search_results"): "search"}.get(title, "open")
        item.setIcon(0, theme.classic_icon(icon))
        item.setBackground(0, theme.color("header"))
        item.setForeground(0, theme.color("text2"))
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self.navigator.addTopLevelItem(item)
        return item

    def _entry(self, section, text, ref, icon):
        item = QTreeWidgetItem([text])
        item.setData(0, Qt.ItemDataRole.UserRole, ref)
        item.setIcon(0, theme.classic_icon(icon, {"data": "kind_data", "result": "kind_result", "graph": "kind_graph"}.get(ref[0])))
        markers = [text]
        state = self.project.sheet_state(ref)
        if color := state.get("highlight"):
            from PySide6.QtGui import QBrush
            light = {"amber": "#fff0cd", "green": "#def1df", "blue": "#ddecfb", "purple": "#ebdff9"}
            dark = {"amber": "#483717", "green": "#263d2d", "blue": "#23394d", "purple": "#3c294d"}
            item.setBackground(0, QBrush(QColor((dark if theme.T["bg"] == theme.DARK["bg"]
                                               else light)[color])))
            markers.append(qt(f"qt.sheet_highlight_{color}"))
        if self.project.sheet_locked(ref):
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
            markers.append(qt("qt.sheet_frozen_notice"))
        item.setToolTip(0, "\n".join(markers))
        section.addChild(item)
        current = self.navigator.currentItem()
        if ref == self.selected and (current is None or current.data(0, Qt.ItemDataRole.UserRole) != ref):
            self.navigator.setCurrentItem(item)
        return item

    def _new_sheet_entry(self, parent, label, action):
        item = QTreeWidgetItem(parent, [tr(f"nav.{label}")])
        item.setIcon(0, theme.classic_icon("plus"))
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, action)

    def _family_entries(self, parent, entries):
        from analisi.family_workflow import FamilyError, plan_family
        from .family import family_ref

        project = self.project
        ref = family_ref(project, self.selected)
        if ref is None:
            return
        try:
            plan = plan_family(project.tables, project.layouts, project.info_sheets.values(), ref)
        except FamilyError:
            return
        owners, results = {}, {}
        for title, ref, icon in entries:
            kind, key = ref
            if kind == "data":
                belongs = key in plan.tables
            elif kind == "info":
                belongs = key in plan.infos or key in plan.global_infos
            elif kind == "layout":
                belongs = key in plan.layouts
            else:
                belongs = project.runs[key].reference in plan.members
            if belongs:
                if kind in {"graph", "result", "saved-layout"}:
                    run = project.runs[key]
                    owner = owners.get(run.title, parent)
                    if run.source is not None:
                        owner = results.get(run.source.analysis_id, owner)
                else:
                    owner = owners.get(project.info_sheets[key].table if kind == "info" else plan.start_table, parent)
                item = self._entry(owner if kind != "data" else parent, title, ref, icon)
                if kind == "data":
                    owners[key] = item
                elif kind == "result":
                    results[run.uid] = item

    def refresh(self):
        """Rebuild the navigator and the window state after any change of the project."""
        project = self.project
        self.navigator.blockSignals(True)
        self.navigator.clear()
        family = self._section(tr("nav.family"))
        self.search_results = self._section(tr("nav.search_results"))
        combined = self._section(tr("nav.data_results")) if self.sessions.active.combined_navigator else None
        tables = self._section(tr("nav.data_tables"))
        info = self._section(tr("nav.info"))
        report = self._section(tr("nav.results"))
        graph = self._section(tr("nav.graphs"))
        layout = self._section(tr("nav.layouts"))
        results = [(index, run) for index, run in enumerate(project.runs)
                   if run_view(run.method) == "result" and
                   (run.result is None or run.result.tables or preferred_view(run, run.result) == "result")]
        graphs = [(index, run) for index, run in enumerate(project.runs)
                  if run_view(run.method) == "graph" or (run.method not in ANALYSIS_GRAPH_OPTIONS and run.method in GRAPH_METHODS)
                  or (run.result is None and run.method == power_plan.METHOD and run.options.get(power_plan.SHOW_CURVE))
                  or (run.result is None and run.method == mcnemar_power.METHOD and run.options.get(mcnemar_power.GRAPH))
                  or (run.result is None and run.method == TOLERANCE and run.options.get(TOLERANCE_GRAPH))
                  or (run.result is None and paired_plot_options(run.method, run.options))
                  or (run.result is None and rank_plot_options(run.method, run.options))
                  or (run.result is None and run.method in ANALYSIS_GRAPH_OPTIONS
                      and run.options.get(*ANALYSIS_GRAPH_OPTIONS[run.method]))
                  or (run.result is None and run.method == cox_outputs.METHOD and not cox_exact.is_exact(run.options)
                      and any(run.options.get(name) for name in cox_outputs.OUTPUT_FIELDS))
                  or (run.result is not None and run.result.figure is not None
                      and run_view(run.method) == "result")]
        layouts = [(index, run) for index, run in enumerate(project.runs) if run_view(run.method) == "saved-layout"]
        entries = [
            (tables, [(title, ("data", title), "data") for title in project.tables]),
            (info, [(sheet.title, ("info", uid), "info") for uid, sheet in project.info_sheets.items()]),
            (report, [(run.name + (" ⚠" if run.calculation_error else ""), ("result", index), "result")
                      for index, run in self._chain_order(results)]),
            (graph, [(run.name + (" ⚠" if run.calculation_error else ""), ("graph", index), "graph")
                     for index, run in graphs]),
            (layout, [(item.name, ("layout", index), "layout") for index, item in enumerate(project.layouts)]
             + [(run.name, ("saved-layout", index), "layout") for index, run in layouts]),
        ]
        entries = [(section, project.ordered_sheets([
            (project.sheet_title(ref) + (" ⚠" if caption.endswith(" ⚠") else ""), ref, icon)
            for caption, ref, icon in group if not project.sheet_state(ref).get("hidden")
        ])) for section, group in entries]
        self.navigator_entries = [entry for _, group in entries for entry in group]
        self._family_entries(family, self.navigator_entries)
        if combined is not None:
            owners = {title: self._entry(combined, title, ref, icon) for title, ref, icon in entries[0][1]}
            linked = {}
            for title, ref, icon in entries[2][1]:
                run = project.runs[ref[1]]
                owner = owners.get(run.title, combined)
                if run.source is not None:
                    owner = linked.get(run.source.analysis_id, owner)
                linked[run.uid] = self._entry(owner, title, ref, icon)
            self._new_sheet_entry(combined, "new_data_table", "new_table")
            self._new_sheet_entry(combined, "new_analysis", "analyze")
        for parent, group in entries:
            for title, ref, icon in group:
                self._entry(parent, title, ref, icon)
        for parent, label, action in ((tables, "new_data_table", "new_table"), (info, "new_info_sheet", "new_info"),
                                      (report, "new_analysis", "analyze"), (graph, "new_graph", "new_graph"),
                                      (layout, "new_layout", "new_layout")):
            self._new_sheet_entry(parent, label, action)
        collapsed = self.sessions.active.collapsed_folders
        if collapsed:
            for item in self._navigator_folders():
                item.setExpanded(self._folder_key(item) not in collapsed)
        else:
            self.navigator.expandAll()
        self.navigator.blockSignals(False)
        with QSignalBlocker(self.sheet_search):
            self.sheet_search.setText(self.sessions.active.sheet_filter)
        self.filter_sheets(self.sheet_search.text())
        self._refresh_sheet_picker()
        self.update_title()
        if self.page is not None and self.page.worksheet_preview is not None:
            preview = self.page.worksheet_preview
            enabled = self.actions["worksheet_preview"].isChecked()
            if enabled != preview.enabled:
                preview.set_enabled(enabled)
            else:
                preview.refresh()
        self.update_actions()
        if self.gallery is not None:
            self.gallery.sync()

    def _refresh_sheet_picker(self):
        self.sheet_refs = {}
        selected = -1
        with QSignalBlocker(self.sheet_picker):
            self.sheet_picker.clear()
            for title, ref, icon in self.navigator_entries:
                if ref == self.selected:
                    selected = self.sheet_picker.count()
                self.sheet_refs[self._sheet_identity(ref)] = ref
                self.sheet_picker.addItem(theme.classic_icon(icon), title, ref)
            self.sheet_picker.setCurrentIndex(selected)

    def _pick_sheet(self, index):
        if not 0 <= index < self.sheet_picker.count() or self.busy():
            return
        ref = tuple(self.sheet_picker.itemData(index))
        if ref != self.selected or self.gallery is not None:
            self.open_sheet(ref)

    def open_section(self, kind):
        if self.busy() or not self.settle_graph_draft():
            return
        kinds = {"layout", "saved-layout"} if kind == "layout" else {kind}
        first = next((ref for ref in self.sheet_refs.values() if ref[0] in kinds), None)
        if first is not None:
            ref = self.selected
            if kind == "data" and ref and ref[0] in {"result", "graph", "saved-layout"}:
                first = ("data", self.project.runs[ref[1]].title)
            if ref != first or self.gallery is not None:
                self.open_sheet(first)

    def _sheet_identity(self, ref):
        return self.project.sheet_identity(ref)

    def _sheet_history_target(self, step):
        session = self.sessions.active
        position = session.sheet_position + step
        while 0 <= position < len(session.sheet_history):
            ref = self.sheet_refs.get(session.sheet_history[position])
            if ref is not None and (ref != self.selected or self.gallery is not None):
                return position, ref
            position += step
        return None

    def step_sheet(self, step):
        if self.busy() or not self.settle_graph_draft():
            return
        target = self._sheet_history_target(step)
        if target is not None:
            self.sessions.active.sheet_position, ref = target
            self.open_sheet(ref)

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
        elif action := item.data(0, Qt.ItemDataRole.UserRole + 1):
            self.actions[action].trigger()

    def _worksheet_group(self, ref):
        kinds = {"layout", "saved-layout"} if ref[0] in {"layout", "saved-layout"} else {ref[0]}
        return [other for _, other, _ in self.navigator_entries if other[0] in kinds]

    def _worksheet_peer(self, ref):
        other = {"result": "graph", "graph": "result"}.get(ref[0])
        return bool(other and any(item == (other, ref[1]) for _, item, _ in self.navigator_entries))

    def _worksheet_command_available(self, ref, command):
        if command in {"move_up", "move_down"}:
            group = self._worksheet_group(ref)
            return ref in group and 0 <= group.index(ref) + (-1 if command == "move_up" else 1) < len(group)
        if command == "freeze":
            if ref[0] == "data":
                return not stored_legacy_view(self.project.tables[ref[1]])
            if ref[0] in RUN_KINDS:
                run = self.project.runs[ref[1]]
                return run.result is not None and not run.calculation_error
            return False
        return True

    def _worksheet_command(self, ref, command, argument=None):
        if ref is None or self.busy() or not self._has_sheet(ref) or not self.prepare_project_change():
            return
        project = self.project
        restore = self._sheet_identity(self.selected) if self.selected is not None else None
        try:
            if command == "duplicate":
                self.open_sheet(project.duplicate_sheet(ref))
                return
            if command == "rename":
                title, ok = QInputDialog.getText(self, qt("qt.sheet_rename"), qt("qt.sheet_name"),
                                                 text=project.sheet_title(ref))
                if not ok:
                    return
                try:
                    title = validate_sheet_title(title)
                except ValueError as error:
                    raise ValueError(qt("qt.sheet_name_invalid")) from error
                renamed = project.rename_sheet(ref, title)
                if renamed != ref:
                    session = self.sessions.active
                    session.sheet_history = [renamed if item == ref else item for item in session.sheet_history]
                if self.selected == ref:
                    self.close_worksheet_notes()
                    self.show_sheet(*renamed)
                else:
                    self.refresh()
                return
            if command in {"move_up", "move_down"}:
                project.move_sheet(ref, self._worksheet_group(ref), -1 if command == "move_up" else 1)
            elif command == "highlight":
                project.highlight_sheet(ref, argument)
            elif command == "freeze":
                locked = project.sheet_locked(ref)
                if ref[0] in RUN_KINDS and not locked and self._worksheet_peer(ref):
                    answer = QMessageBox.question(self, qt("qt.sheet_freeze"), qt("qt.sheet_freeze_linked"))
                    if answer != QMessageBox.StandardButton.Yes:
                        return
                affected = project.set_sheet_frozen(ref, not locked)
                if self.selected == ref or (self.selected and self.selected[0] in RUN_KINDS
                                            and ref[0] in RUN_KINDS and self.selected[1] == ref[1]):
                    self.show_sheet(*self.selected)
                self.refresh_runs(affected)
            elif command == "delete":
                peer = self._worksheet_peer(ref)
                if problem := project.sheet_delete_problem(ref, peer_visible=peer):
                    raise ValueError(problem)
                answer = QMessageBox.question(self, qt("qt.sheet_delete"),
                                               qt("qt.sheet_confirm_delete", name=project.sheet_title(ref)))
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self.close_worksheet_notes()
                if self.selected == ref and ref[0] == "info":
                    self.info_editor = None
                identity = self._sheet_identity(ref)
                stale = project.delete_sheet(ref, peer_visible=peer)
                session = self.sessions.active
                history = session.sheet_history
                session.sheet_position -= history[:session.sheet_position + 1].count(identity)
                session.sheet_history = [other for other in history if other != identity]
                if ref[0] == "layout":
                    def reindex(other):
                        kind, key = other
                        return ("layout", key - 1) if kind == "layout" and key > ref[1] else other
                    session.sheet_history = [reindex(other) for other in session.sheet_history]
                    if restore and restore != identity:
                        restore = reindex(restore)
                if restore == identity:
                    restore = None
                self.selected = None
                self.refresh()
                target = self.sheet_refs.get(restore, next(iter(self.sheet_refs.values()), None))
                seeds = [run for run in stale if run.result is not None]
                if target is None:
                    self.show_home()
                else:
                    self.show_sheet(*target)
                    kind, key = target
                    if kind in RUN_KINDS and project.runs[key].result is None:
                        seeds.append(project.runs[key])
                    elif kind == "layout":
                        seeds.extend(run for run in project.layout_runs(project.layouts[key]) if run.result is None)
                self.refresh_runs(seeds)
                return
            self.refresh()
        except (ValueError, TypeError, OSError, OverflowError) as error:
            self.error(error)

    def _navigator_action(self, ref, key):
        if self._has_sheet(ref) and self.prepare_project_change():
            if self.selected != ref:
                self.show_sheet(*ref)
            self.actions[key].trigger()

    def _navigator_menu(self, position):
        item = self.navigator.itemAt(position)
        raw = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        ref = tuple(raw) if raw else None
        menu = QMenu(self)
        if ref is not None:
            kind, key = ref
            idle = not self.busy(warn=False)
            for command in ("duplicate", "rename", "delete", "move_up", "move_down", "freeze"):
                if not self._worksheet_command_available(ref, command):
                    continue
                label = "unfreeze" if command == "freeze" and self.project.sheet_locked(ref) else command
                action = menu.addAction(qt(f"qt.sheet_{label}"),
                                        lambda _checked=False, command=command: self._worksheet_command(ref, command))
                action.setEnabled(idle)
            palette = menu.addMenu(qt("qt.sheet_highlight"))
            palette.setEnabled(idle)
            for color in (*HIGHLIGHTS, None):
                choice = palette.addAction(qt(f"qt.sheet_highlight_{color or 'none'}"),
                                           lambda _checked=False, color=color: self._worksheet_command(ref, "highlight", color))
                choice.setCheckable(True)
                choice.setChecked(self.project.sheet_state(ref).get("highlight") == color)
            commands = []
            if kind in {"result", "graph"}:
                run = self.project.runs[key]
                if not self.project.frozen(run):
                    if not _saved_recipe(run):
                        commands.extend(("change", "repeat_analysis"))
                    commands.append("recalculate")
                    if kind == "graph" and self.project.graph_type_problem(run) is None:
                        commands.append("change_graph_type")
                if kind == "result":
                    commands.extend(("analyze_result", "change_input") if not self.project.frozen(run)
                                    else ("analyze_result",))
                if run.source is not None:
                    commands.append("source_analysis")
            elif kind == "data":
                commands.extend(("analyze", "new_graph"))
            elif kind == "info":
                commands.append("info_properties")
            elif kind == "layout":
                commands.append("edit_layout")
            menu.addSeparator()
            for command in (*commands, "sheet_notes", "duplicate_family", "save_family"):
                action = menu.addAction(self.actions[command].text(),
                                        lambda _checked=False, command=command: self._navigator_action(ref, command))
                action.setEnabled(idle)
            menu.addSeparator()
        menu.addAction(self.actions["new_table"])
        menu.addSeparator()
        menu.addAction(tr("nav.expand_all"), lambda: self.expand_navigator(True))
        menu.addAction(tr("nav.collapse_all"), lambda: self.expand_navigator(False))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.navigator.viewport().mapToGlobal(position))

    # == gallery ==================================================================================
    def toggle_gallery(self):
        """View → Gallery: every graph and layout as cards. Back (Esc) returns to the sheet it came from."""
        if self.gallery is not None:
            self.close_gallery()
        else:
            self.open_gallery()

    def open_gallery(self):
        if self.gallery is not None or not self.settle_graph_draft():
            return
        origin = self.selected
        self.dispose_inspector()
        self.close_worksheet_notes()
        self.flush_info()
        try:
            gallery = GalleryPage(lambda: self.project, lambda: self.job is not None, self.gallery_view, origin)
        except Exception as error:  # noqa: BLE001 - the sheet stays where it was.
            self.error(error)
            return
        gallery.opened.connect(self._gallery_open)
        gallery.closed.connect(self.close_gallery)
        if self.page is not None:
            self.page.hide()  # Kept (not rebuilt) so that a worksheet returns with its selection and scroll.
        self.page_layout.addWidget(gallery)
        self.gallery = gallery
        self.update_actions()
        gallery.focus_first()

    def _drop_gallery(self):
        """Remove the gallery and let go of its previews. The page it covered shows again."""
        gallery, self.gallery = self.gallery, None
        if gallery is None:
            return False
        gallery.dispose()
        self.page_layout.removeWidget(gallery)
        gallery.hide()
        gallery.setParent(None)
        gallery.deleteLater()
        if self.page is not None:
            self.page.show()
        return True

    def _has_sheet(self, ref):
        kind, key = ref
        project = self.project
        return ((kind == "data" and key in project.tables) or (kind == "info" and key in project.info_sheets)
                or (kind == "layout" and 0 <= key < len(project.layouts))
                or (kind in {"result", "graph", "saved-layout"} and 0 <= key < len(project.runs)))

    def close_gallery(self):
        """Back to the sheet the gallery was opened from, with the focus on its content."""
        if not self._drop_gallery():
            return
        origin = self.selected
        if origin is not None and origin[0] == "data" and self.sheet is not None and self._has_sheet(origin):
            self.update_actions()
            self.sheet.setFocus()
            return
        if origin is None:
            self.update_actions()
        elif self._has_sheet(origin):
            self.show_sheet(*origin)
            target = self.sheet or self.result_tabs or next(iter(self.page.canvases), None)
            (target or self.navigator).setFocus()
        else:
            self.show_home()

    def _gallery_open(self, ref):
        """Open a card with the standard navigation: the sheet's own calculation, errors and Cancel apply."""
        self._drop_gallery()
        if self._has_sheet(ref):
            self.open_sheet(ref)
        else:
            self.refresh()

    # == pages ====================================================================================
    def _replace_page(self, page):
        self._drop_gallery()
        self.formula_editor = None  # The editor belongs to the old worksheet page.
        if self.page is not None:
            self.page.release()
            self.page_layout.removeWidget(self.page)
            self.page.hide()
            self.page.setParent(None)
            self.page.deleteLater()
        self.page = page
        self.page_layout.addWidget(page)

    def show_home(self):
        from .table_setup import TableSetup

        self.close_worksheet_notes()

        self.plot_tools = None
        self.drawing.detach()
        self.table_move.detach()
        self.dispose_inspector()
        self.flush_info()
        self.info_editor = None
        self.selected = None
        self.sheet = None
        self.result_tabs = None
        self.toolbar.hide()
        self.nav_card.hide()
        self.statusBar().hide()
        page = Page("")
        page.layout_.setContentsMargins(0, 0, 0, 0)
        page.finish_actions()
        chooser = page.add(TableSetup(page, open_project=self.open_dialog, open_path=self.open_path,
                                      create_info=self.new_info, recover=self.actions["recover"]))
        page.canvases.append(chooser.chart)
        chooser.bind_create(lambda: self.create_worksheet(*chooser.selection()))
        self._replace_page(page)
        self.refresh()

    def open_sheet(self, ref):
        if self.formula_editor is not None and self.gallery is None and ref == self.selected:
            self.sheet.setFocus()
            return
        kind, key = ref
        self.show_sheet(kind, key)
        if kind in {"result", "graph", "saved-layout"} and self.project.runs[key].result is None and self.job is None:
            self.refresh_runs([self.project.runs[key]])
        elif kind == "layout" and self.job is None:
            runs = [run for run in self.project.layout_runs(self.project.layouts[key]) if run.result is None]
            if runs:
                self.refresh_runs(runs)

    def show_sheet(self, kind, key):
        if self.worksheet_notes is not None and self.project.sheet_key((kind, key)) != self.worksheet_notes.sheet_key:
            self.close_worksheet_notes()
        self.plot_tools = None
        self.drawing.detach()  # Closes a pointer preview; the new graph page attaches its own canvas.
        self.table_move.detach()
        self.dispose_inspector()  # Before the new page builds its own panel.
        self.flush_info()
        self.info_editor = None
        self.selected = (kind, key)
        self.sessions.active.visit(self._sheet_identity(self.selected))
        self.cell_label.clear()
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
        self.page_layout.activate()
        self.body.refresh()
        self.toolbar.show()
        self.nav_card.setVisible(self.navigator_open)
        self.statusBar().show()
        self.refresh()
        if self.sheet is not None:
            self.sheet.setFocus()

    def reshow(self):
        if self.selected is None:
            self.show_home()
        elif self.selected[0] == "data" and self.sheet is not None:
            current = self.sheet.currentIndex()
            self.sheet.model().reload()
            self.sheet.refresh_text(self.project.tables[self.selected[1]].text_styles)
            if current.isValid():
                self.sheet.setCurrentIndex(self.sheet.model().index(current.row(), current.column()))
            if self.formula_editor is not None:
                self._highlight_formula_references()
            self.refresh()
        else:
            self.show_sheet(*self.selected)

    def _data_page(self, title):
        from .worksheet_preview import WorksheetPreview

        dataset = self.project.tables[title]
        page = Page("")
        page.layout_.setContentsMargins(0, 0, 0, 0)
        page.layout_.setSpacing(0)
        locked = self.project.sheet_locked(("data", title))
        read_only = locked or stored_legacy_view(dataset)
        page.finish_actions()
        if read_only:
            page.notice(qt("qt.sheet_frozen_notice" if locked else "qt.read_only"))
        project = self.project  # Typing reaches this project only, even if it lands after a tab switch.
        model = WorksheetModel(dataset, lambda row, column, text: self.edit_cell(title, row, column, text,
                                                                                 project=project),
                               read_only=read_only)
        self.sheet = WorksheetView(model, self)
        self.text_format.watch(self.sheet)
        if self.table_font != ("", None) or self.table_zoom != 100:
            set_table_appearance(self.sheet, self.table_font, self.table_zoom)
        else:
            self.sheet.apply_row_heights(self.table_zoom)
        page.worksheet_split = page.add(QSplitter(Qt.Orientation.Horizontal))
        page.worksheet_split.setChildrenCollapsible(False)
        page.worksheet_preview = WorksheetPreview(self, title, self.sheet)
        page.worksheet_split.addWidget(page.worksheet_preview)
        page.worksheet_split.setStretchFactor(0, 1)
        self.sheet.setCurrentIndex(model.index(0, 0))
        return page

    def _resize_tables(self):
        if self.sheet is not None:
            set_table_appearance(self.sheet, self.table_font, self.table_zoom)
        if self.result_tabs is not None:
            for index in range(self.result_tabs.count()):
                set_table_appearance(self.result_tabs.widget(index), self.table_font, self.table_zoom)

    def choose_table_font(self):
        from .worksheet_appearance import TableFontDialog
        dialog = TableFontDialog(self, self.table_font)
        if dialog.exec() == dialog.DialogCode.Accepted:
            preference = dialog.preference()
            try:
                save_font_preference(config_path(), *preference)
            except OSError as error:
                self.error(error)
                return
            self.table_font = preference
            self._resize_tables()

    def zoom_table(self, step):
        self.table_zoom = zoom_step(self.table_zoom, step)
        self._resize_tables()
        self.status(tr("worksheet.zoom_status", percent=self.table_zoom))

    def _refresh_result_backgrounds(self, run):
        if self.result_tabs is None or run.result is None:
            return
        dataset = self.project.tables[run.title]
        sheets = dataset.result_backgrounds.get(run.slot, {})
        formats = dataset.result_number_formats.get(run.slot, {})
        texts = dataset.result_text_styles.get(run.slot, {})
        for index, name in enumerate(run.result.tables):
            view = self.result_tabs.widget(index)
            view.set_backgrounds(sheets.get(name, {}))
            view.set_number_formats(formats.get(name, {}))
            view.set_text_styles(texts.get(name) or TextStyles())

    def change_number_format(self):
        """Change → Number format…: what the selected numeric columns show; the stored values do not change."""
        from analisi.worksheet_number_format import format_target, result_columns, worksheet_columns
        from .worksheet_number_format import NumberFormatDialog
        if self.busy() or self.gallery is not None:
            return
        result = self.result_tabs is not None
        view = self.result_tabs.currentWidget() if result else self.sheet
        if view is None or (box := selection_box(view)) is None:
            return
        model = view.model()
        frame = model.frame
        current = view.currentIndex()
        active = (current.row(), current.column()) if current.isValid() else None
        if result:
            run = self.project.runs[self.selected[1]]
            title, name = run.title, tuple(run.result.tables)[self.result_tabs.currentIndex()]
            columns = result_columns(frame, model.index_title, set(model.formatters))
            formats = self.project.tables[title].result_number_formats.get(run.slot, {}).get(name, {})
            value_at = lambda row, position: frame.iat[row, position - 1]
        else:
            title = self.selected[1]
            dataset = self.project.tables[title]
            columns = worksheet_columns(dataset, frame)
            formats = dataset.displayed_number_formats
            value_at = lambda row, position: frame.iat[row, position]
        try:
            target = format_target(columns, box, formats, active=active, value_at=value_at, rows=len(frame))
        except ValueError as error:
            self.error(error)
            return
        dialog = NumberFormatDialog(self, target)
        try:
            if dialog.exec() != dialog.DialogCode.Accepted or dialog.choice is None:
                return
            _, spec = dialog.choice
        finally:
            dialog.deleteLater()
        if result:
            if self.project.set_result_number_format(title, run.slot, name, target.keys, spec):
                self._refresh_result_backgrounds(run)
        else:
            names = [frame.columns[position] for position in target.keys]
            if self.project.set_table_number_format(title, names, spec):
                self.sheet.model().refresh_formats()
        self.update_title()
        self.update_actions()

    def change_cell_background(self, *, clear=False):
        if self.busy() or self.gallery is not None:
            return
        result = self.result_tabs is not None
        view = self.result_tabs.currentWidget() if result else self.sheet
        if view is None or (box := selection_box(view)) is None:
            return
        color = None
        if not clear:
            from PySide6.QtWidgets import QColorDialog
            brush = view.model().data(view.model().index(box[0], box[1]), Qt.ItemDataRole.BackgroundRole)
            chosen = QColorDialog.getColor(brush.color() if brush else QColor("#ffe385"), self,
                                          tr("command.cell_background").rstrip("…"))
            if not chosen.isValid():
                return
            color = chosen.name()
        if result:
            run = self.project.runs[self.selected[1]]
            name = tuple(run.result.tables)[self.result_tabs.currentIndex()]
            model = view.model()
            if self.project.set_result_background(run.title, run.slot, name, box,
                                                  (model.rowCount(), model.columnCount()), color):
                self._refresh_result_backgrounds(run)
        elif self.project.set_table_background(self.selected[1], box, color):
            self.sheet.model().refresh_backgrounds()
        self.update_title()
        self.update_actions()

    def toggle_worksheet_preview(self):
        if self.page is None or self.page.worksheet_preview is None:
            return
        action = self.actions["worksheet_preview"]
        if not action.isChecked() and not self.settle_graph_draft():
            action.setChecked(True)
            return
        self.page.worksheet_preview.set_enabled(action.isChecked())

    def _info_page(self, uid):
        from .info_editor import InfoEditor
        sheet = self.project.info_sheets[uid]
        page = Page(sheet.title, tr("interface.linked_to", table=sheet.table) if sheet.table else tr("nav.info"))
        page.finish_actions()
        project = self.project
        self.info_editor = page.add(InfoEditor(
            sheet, lambda revised: self.change_info(revised) if project is self.project else False, self.error))
        self.info_editor.notes.undoAvailable.connect(self.update_actions)
        self.info_editor.notes.redoAvailable.connect(self.update_actions)
        return page

    def open_worksheet_notes(self):
        if self.selected is None or self.gallery is not None or self.busy():
            return
        from .worksheet_notes import WorksheetNotes

        if self.worksheet_notes is None:
            dialog = self.worksheet_notes = WorksheetNotes(self, self.selected)
            dialog.finished.connect(lambda _code: self._notes_closed(dialog))
        self.worksheet_notes.show()
        self.worksheet_notes.raise_()
        self.worksheet_notes.activateWindow()

    def _notes_closed(self, dialog):
        if self.worksheet_notes is dialog:
            dialog.flush()
            self.worksheet_notes = None

    def close_worksheet_notes(self):
        if self.worksheet_notes is not None:
            self.worksheet_notes.close()

    def flush_info(self):
        if self.worksheet_notes is not None:
            self.worksheet_notes.flush()
        if getattr(self, "info_editor", None) is not None:
            editor, self.info_editor = self.info_editor, None
            editor.flush()
            self.info_editor = editor

    def change_info(self, sheet):
        """Store an edit of the open Info sheet; constants read by formulas recalculate their tables."""
        current = self.project.info_sheets[sheet.uid]
        if self.job is not None and (sheet.table, sheet.fields, sheet.use_constants) != (
                current.table, current.fields, current.use_constants):
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
        return [name for name, dataset in self.project.tables.items() if not stored_legacy_view(dataset)]

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
        dialog = InfoDetails(self, sheet.title, sheet.table, self._info_tables(), use_constants=sheet.use_constants)
        if dialog.exec() != InfoDetails.DialogCode.Accepted or dialog.result is None:
            return
        title, table = dialog.result
        if self.info_editor.commit(title=title, table=table, use_constants=dialog.use_constants.isChecked()):
            self.show_sheet("info", sheet.uid)

    def remove_info(self):
        if self.selected and self.selected[0] == "info":
            self._worksheet_command(self.selected, "delete")

    def _canvas(self, page, figure, *, toolbar=True, run=None, paper=None, imported_layout=False, reference=None):
        canvas = SheetCanvas(figure) if paper is None else PaperCanvas(figure, paper)
        canvas.setMinimumSize(200, 160)
        page.canvases.append(canvas)
        if toolbar:
            tools = self.plot_tools = PlotNavigation(canvas, page)
            tools.setIconSize(theme.icon_size(18))
            theme.plot_toolbar(tools)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        preview = canvas
        if paper is not None:
            preview = ImportedPaperPreview(canvas, paper) if imported_layout else PaperPreview(canvas, paper)
        line.addWidget(preview, 1)
        page.add(row, 1)
        if toolbar:
            tools.addSeparator()
            tools.configure_fit(layout=paper is not None and run is None, preview=preview)
            if tools.fit_action.isCheckable():
                tools.fit_action.toggled.connect(self.actions["fit_layout_page"].setChecked)
            tools.addAction(self.actions["plot_margins"])
            page.add(tools, 0)
        if run is not None:
            self.drawing.attach(page, canvas, tools if toolbar else None, run)
        if reference is not None:
            self.table_move.attach(page, canvas, tools if toolbar else None, reference, figure)
        if run is not None and self.inspector_wanted and self.project.graph_format_problem(run) is None:
            self._open_inspector(run, canvas, line)
        return canvas  # No draw_idle(): showing the page resizes the canvas, which draws it once (SheetCanvas).

    def fit_preview(self):
        if self.plot_tools is not None and self.gallery is None and not self.busy():
            self.plot_tools.fit_action.trigger()

    def adjust_plot_margins(self):
        if self.plot_tools is not None and self.gallery is None and not self.busy():
            self.plot_tools.configure_subplots()

    def switch_run_view(self, kind):
        if self.selected and self.selected[0] in {"result", "graph"} and not self.busy() and self.settle_graph_draft():
            self.open_sheet((kind, self.selected[1]))

    # == inspector =================================================================================
    def _open_inspector(self, run, canvas, line):
        from .inspector import GraphInspector

        def closed():
            self.inspector_wanted = False
            self.dispose_inspector()

        project = self.project
        self.inspector = GraphInspector(run, canvas, confirmed=lambda: run.style,
                                        commit=lambda style: self.commit_style(run, style, project=project, record_history=True),
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

    def commit_style(self, run, style, project=None, *, record_history=False):
        project = self.project if project is None else project  # The run's own project, never another tab's.
        project.commit_style(run, style, record_history=record_history)
        if project is self.project:
            self.update_title()
            self.update_actions()
            self.status(qt("qt.style_applied"))
        else:
            self._sync_tabs()

    def arrange_shapes(self):
        if self.drawing.can_arrange() and self.settle_graph_draft():
            self.drawing.arrange()

    def settle_graph_draft(self):
        """Before leaving the drawn style behind: apply or discard an Inspector draft, or stay."""
        self.drawing.cancel()  # A pointer preview is never saved, exported or recalculated.
        self.table_move.cancel()
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
        page.command(self.actions["edit_layout"])
        page.command(self.actions["linked_table"])
        page.command(self.actions["linked_table_move"])
        page.finish_actions()
        self._stale(page, self.project.layout_runs(layout))
        figure = self.project.layout_figure(layout)
        if figure is None:
            page.notice(qt("qt.layout_missing"))
            page.layout_.addStretch(1)
        else:
            self.layout_figure = figure
            self._canvas(page, figure, paper=figure.get_size_inches(), reference=("layout", index))
        return page

    def _stale(self, page, runs):
        failures = [run.calculation_error for run in runs if run.calculation_error]
        if failures:
            page.notice(qt("qt.stale", error="; ".join(dict.fromkeys(failures))))

    def _imported_graph_actions(self, page, run):
        if run.method == SAVED_EDITABLE_GRAPH or linked_curve_view(run):
            page.button(ui("Edit graph data"), lambda: self.open_sheet(("data", run.title)),
                        primary=True, icon="table")
        if (related := paired_graph_index(run, self.project.runs)) is not None:
            label = "Open editable graph" if run.method == SAVED_BINARY_GRAPH else "View original"
            page.button(ui(label), lambda: self.open_sheet(("graph", related)), icon="chart-line")

    def _imported_layout_actions(self, page, run, index):
        graphs = self.project.layout_panel_graphs(run)
        panels = run.options.get(LEGACY_EDITABLE_PANELS)
        if self.project.imported_vector_format(run) == "emf":
            if isinstance(panels, list) and panels:
                button = page.button(ui("Edit panel…"), lambda: self.edit_imported_panel(index),
                                     icon="sliders-horizontal")
                button.setObjectName("importedPanelGeometry")
            if graphs or run.options.get(LEGACY_PANEL_EDITS):
                page.button(tr("layout.export_current_emf"), lambda: self.export_current_layout_emf(run), icon="upload")
        entries = layout_panel_sources(run, graphs)
        if not entries:
            return
        choice = QComboBox()
        choice.setAccessibleName(ui("Edit panel data…"))
        choice.setObjectName("importedPanelSource")
        choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        choice.setMinimumContentsLength(18)
        for caption, table in entries:
            choice.addItem(caption, table)
        page.actions_row.addWidget(choice)
        page.button(ui("Edit panel data…"), lambda: self.open_sheet(("data", choice.currentData())),
                    primary=True, icon="table")

    def _run_page(self, kind, index):
        run = self.project.runs[index]
        subtitle = run.notes or (tr("command.analysis_results") if kind == "result" else tr("ribbon.graph"))
        page = Page(self.project.sheet_title((kind, index)), subtitle)
        result = run.result
        if kind == "graph" and (run.method in {SAVED_BINARY_GRAPH, SAVED_EDITABLE_GRAPH} or linked_curve_view(run)
                                or (run.method == SAVED_XY and SAVED_AXES in run.options)):
            self._imported_graph_actions(page, run)
        elif kind == "graph" and run.method == SAVED_XY and not SOURCE_XY.isdisjoint(run.options):
            button = page.button(ui("Edit graph data"), lambda: self.open_sheet(("data", run.title)),
                                 primary=True, icon="table")
            button.setObjectName("importedGraphSource")
        elif kind == "saved-layout":
            self._imported_layout_actions(page, run, index)
        if kind == "graph" and run.method not in LEGACY_GRAPH_METHODS:
            page.command(self.actions["annotations"]).setText(tr("annotation.button"))
            page.command(self.actions["draw"]).setText(tr("shape.button"))
            page.command(self.actions["linked_table"])
            page.command(self.actions["linked_table_move"])
        if kind == "graph":
            page.command(self.actions["inspector"])
        elif kind == "result":
            page.command(self.actions["analyze_result"])
            if run.source is None:
                page.command(self.actions["change_input"])
        page.finish_actions()
        if run.source is not None:
            source = next((other for other in self.project.runs if other.uid == run.source.analysis_id), None)
            name = source.name if source is not None else tr("chain.missing_source")
            caption = QLabel(tr("chain.input_label", analysis=name, table=run.source.table))
            caption.setObjectName("muted")
            caption.setWordWrap(True)
            page.add(caption, 0)
        self._stale(page, [run])
        if self.project.frozen(run):
            page.notice(qt("qt.sheet_frozen_notice"))
        if result is None:
            text = qt("qt.running", method=method_label(run.method)) if self.job is not None else qt("qt.not_calculated")
            page.notice(text)
            page.layout_.addStretch(1)
            return page
        if result.style_warning:
            page.notice(result.style_warning)
        if kind == "result":
            results = ResultTabs()
            self.result_tabs = results.tabs
            presentation = result_display.renderer(run.method, run.options)
            for title, frame in result.tables.items():
                formatters = ({"Threshold": threshold_text} if threshold_text and run.method == "ROC curve"
                              and title == "Diagnostic thresholds" else None)
                if run.method == "Multiple regression" and title == "Lack of fit on replicates":
                    from analisi.ols_diagnostics import show_component, show_note
                    formatters = {"Component": show_component, "Note": show_note}
                if run.method == "Kaplan–Meier survival":
                    from analisi.weighted_logrank import cell_formatters
                    formatters = cell_formatters(title) or formatters
                if run.method in KMEANS_METHODS and title == FIT_DIAGNOSTICS_TABLE:
                    formatters = {FIT_REASON: ui, FIT_SOURCE: ui}
                backgrounds = self.project.tables[run.title].result_backgrounds.get(run.slot, {}).get(title, {})
                number_formats = self.project.tables[run.title].result_number_formats.get(run.slot, {}).get(title, {})
                text_styles = self.project.tables[run.title].result_text_styles.get(run.slot, {}).get(title)
                caption, headers = result_labels(run.method, title)
                view = FrameView(frame, formatters, backgrounds=backgrounds, number_formats=number_formats,
                                 text_styles=text_styles, host=self, header_labels=headers,
                                 result_display=presentation)
                if self.table_font != ("", None) or self.table_zoom != 100:
                    set_table_appearance(view, self.table_font, self.table_zoom)
                self.text_format.watch(view)
                results.add_table(view, caption)
            page.add(results, 1)
        elif result.figure is not None:
            try:
                from analisi.pairwise_graph import pairwise_warning
                warning = pairwise_warning(result.figure)
            except Exception:  # pragma: no cover
                warning = None
            if warning:
                page.notice(warning)
            paper = imported_paper(run)
            saved_layout = kind == "saved-layout"
            reference = (kind, index) if kind == "graph" and run.method not in LEGACY_GRAPH_METHODS else None
            self._canvas(page, result.figure, run=run if kind == "graph" else None,
                         paper=paper if paper is not None or not saved_layout else result.figure.get_size_inches(),
                         imported_layout=saved_layout and paper is not None, reference=reference)
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
        if self.inspector is not None and not self.settle_graph_draft():
            self.sheet.model().reload()
            return
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
            self.refresh_runs(affected, reopen_analysis_field_error=True)
        else:
            self.status(qt("qt.edited"))

    def edit_cell(self, title, row, column, text, project=None):
        if project is not None and project is not self.project:  # Typed in a tab that is no longer active.
            self.status(qt("qt.edit_elsewhere"))
            return False
        if self._active_table() != title:
            return False
        self._apply_edit(title, lambda: self.project.edit_cell(title, row, column, text))
        return True

    def paste_cells(self, row, column, rows, *, label="Paste"):
        title = self._active_table()
        if title is not None:
            self._apply_edit(title, lambda: self.project.paste(title, row, column, rows, label))

    def clear_cells(self, box):
        title = self._active_table()
        if title is None:
            return
        model = self.sheet.model()
        top, left, bottom, right = box
        bottom = min(bottom, len(model.frame) - 1)
        if model.dataset.column_order is None:
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

    def can_reorder_active_rows(self):
        return bool(self.selected and self.selected[0] == "data" and self.job is None
                    and self.project.can_reorder_rows(self.selected[1]))

    def _update_row_actions(self, data, editable, idle):
        box = self.sheet.box() if data and self.sheet is not None else None
        dataset = self.project.tables[self.selected[1]] if data else None
        data_rows = len(dataset.raw) if dataset is not None else 0
        can_reorder = bool(editable and idle and dataset is not None and self.project.can_reorder_rows(self.selected[1]))
        reorder = bool(can_reorder and box is not None and 0 <= box[0] <= box[2] < data_rows)
        self.actions["move_rows_up"].setEnabled(reorder and box[0] > 0)
        self.actions["move_rows_down"].setEnabled(reorder and box[2] + 1 < data_rows)
        self.actions["move_rows_first"].setEnabled(reorder and box[0] > 0)
        self.actions["move_rows_last"].setEnabled(reorder and box[2] + 1 < data_rows)
        self.actions["sort_rows"].setEnabled(can_reorder and bool(sortable_columns(dataset)))
        self.actions["sort_by_x"].setEnabled(can_reorder and x_sort_column(dataset) is not None)
        self.actions["sort_by_row_title"].setEnabled(can_reorder and row_title_sort_column(dataset) is not None)
        self.actions["reverse_rows"].setEnabled(can_reorder and data_rows > 1)
        has_custom = bool(editable and idle and dataset is not None and box is not None and dataset.row_heights
                          and any(row in dataset.row_heights for row in range(box[0], min(box[2] + 1, data_rows))))
        self.actions["reset_row_height"].setEnabled(has_custom)

    def sort_rows(self, column=None):
        from .sort_rows_dialog import SortRowsDialog

        title = self._active_table()
        if title is None or self.sheet is None or self.busy():
            return
        dataset = self.project.tables[title]
        if not self.project.can_reorder_rows(title):
            self.error(ValueError(qt("qt.rows_reorder_unavailable")))
            return
        if not sortable_columns(dataset):
            self.error(ValueError(sort_text("err.empty")))
            return
        if column is None:
            current = self.sheet.currentIndex()
            column = current.column() if current.isValid() else None
        dialog = SortRowsDialog(self, self.project, title, dataset, initial_column=column)
        initial_revision = dialog.initial_revision
        initial_raw = dialog.initial_raw
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.plan is None:
                return
            plan = dialog.plan
        finally:
            dialog.deleteLater()
        self._apply_row_sort(title, plan=plan, expected_revision=initial_revision, expected_raw=initial_raw)

    def sort_by_x(self):
        title = self._active_table()
        if title is None or self.sheet is None or self.busy():
            return
        key = x_sort_column(self.project.tables[title])
        if key is None:
            self.error(ValueError(sort_text("err.unknown_key")))
            return
        self._apply_row_sort(title, key=key, direction=ASCENDING)

    def sort_by_row_title(self):
        title = self._active_table()
        if title is None or self.sheet is None or self.busy():
            return
        key = row_title_sort_column(self.project.tables[title])
        if key is None:
            self.error(ValueError(sort_text("err.unknown_key")))
            return
        self._apply_row_sort(title, key=key, direction=ASCENDING)

    def _apply_row_sort(self, title, *, key=None, direction=ASCENDING, plan=None,
                        expected_revision=None, expected_raw=None):
        if expected_revision is not None:
            if (self.project.revision != expected_revision or title not in self.project.tables
                    or self.project.tables[title].raw is not expected_raw):
                self.error(ValueError(sort_text("err.stale")))
                return
        if self._active_table() != title or self.sheet is None:
            self.error(ValueError(sort_text("err.stale")))
            return
        dataset = self.project.tables[title]
        locked = self.project.sheet_locked(("data", title))
        reorder_allowed = title in self.project.tables and not locked and self.project.can_reorder_rows(title)
        if plan is None:
            try:
                plan = plan_row_sort(dataset, key, direction, locked=locked,
                                     reorder_allowed=reorder_allowed or self.project.can_reorder_rows(title))
            except ValueError as error:
                self.error(error)
                return
        if not plan.changed:
            self.status(sort_text("already_sorted", key=plan.key_name, direction=sort_text(plan.direction).lower()))
            return
        if self._apply_row_permutation(
            title, plan.inverse,
            lambda: self.project.sort_rows(
                title, plan.key_name, plan.direction, plan=plan,
                expected_revision=expected_revision, expected_raw=expected_raw,
            ),
        ) and not self.project.table_runs(title):
            self.status(sort_text("done", rows=plan.row_count, key=plan.key_name,
                                  direction=sort_text(plan.direction).lower()))

    def reverse_rows(self):
        if not self.can_reorder_active_rows() or self.sheet is None:
            return
        title = self.selected[1]
        length = len(self.project.tables[title].raw)
        if length > 1 and self._apply_row_permutation(
            title, range(length - 1, -1, -1), lambda: self.project.reverse_rows(title),
        ) and not self.project.table_runs(title):
            self.status(qt("qt.rows_reversed"))

    def _apply_row_permutation(self, title, inverse, change):
        box = self.sheet.box()
        current = self.sheet.currentIndex()
        current_row = current.row() if current.isValid() else None
        current_col = current.column() if current.isValid() else (box[1] if box is not None else 0)
        length = len(inverse)
        before_revision = self.project.revision
        self._apply_edit(title, change)
        if self.project.revision != before_revision and self.selected == ("data", title) and self.sheet is not None:
            restored = remap_selection_after_sort(inverse, length, box, current_row, current_col)
            if restored is not None:
                top, left, bottom, right, active_row, active_col = restored
                self.sheet.select_block(top, left, bottom, right, current_row=active_row, current_col=active_col)
                self.sheet.scrollTo(self.sheet.model().index(active_row, active_col))
            self.update_actions()
            return True
        return False

    def move_rows(self, start, stop, destination):
        title = self._active_table()
        if title is None or self.sheet is None:
            return
        box = self.sheet.box()
        current = self.sheet.currentIndex()
        left = box[1] if box is not None else 0
        right = box[3] if box is not None else max(0, self.sheet.model().columnCount() - 1)
        row_offset = (current.row() - start) if current.isValid() and start <= current.row() < stop else 0
        col_cur = current.column() if current.isValid() else left
        before_revision = self.project.revision
        self._apply_edit(title, lambda: self.project.move_rows(title, start, stop, destination))
        if self.project.revision != before_revision and self.selected == ("data", title) and self.sheet is not None:
            new_start, new_stop = moved_row_bounds(start, stop, destination)
            self.sheet.select_block(new_start, left, new_stop - 1, right,
                                    current_row=new_start + row_offset, current_col=col_cur)
            self.sheet.scrollTo(self.sheet.model().index(new_start + row_offset, col_cur))
            self.update_actions()

    def move_rows_up(self):
        if self.sheet is None or (box := self.sheet.box()) is None:
            return
        top, _, bottom, _ = box
        if top > 0:
            self.move_rows(top, bottom + 1, top - 1)

    def move_rows_down(self):
        if self.sheet is None or (box := self.sheet.box()) is None:
            return
        top, _, bottom, _ = box
        if bottom + 1 < len(self.sheet.model().frame):
            self.move_rows(top, bottom + 1, bottom + 2)

    def move_rows_to_edge(self, *, first):
        if not self.can_reorder_active_rows() or self.sheet is None or (box := self.sheet.box()) is None:
            return
        top, _, bottom, _ = box
        length = len(self.project.tables[self.selected[1]].raw)
        if 0 <= top <= bottom < length:
            self.move_rows(top, bottom + 1, 0 if first else length)

    def set_row_height(self, row, height):
        title = self._active_table()
        if title is None or self.sheet is None:
            return
        try:
            changed = self.project.set_row_heights(title, (row,), height)
        except (ValueError, TypeError, OverflowError) as error:
            self.sheet.apply_row_heights(self.table_zoom)
            self.error(error)
            return
        if changed:
            self.sheet.apply_row_heights(self.table_zoom)
            self.update_title()
            self.update_actions()
            self.status(qt("qt.edited"))

    def reset_row_height(self):
        title = self._active_table()
        if title is None or self.sheet is None or (box := self.sheet.box()) is None:
            return
        data_rows = len(self.sheet.model().frame)
        rows = [row for row in range(box[0], box[2] + 1) if row < data_rows]
        if not rows:
            return
        try:
            changed = self.project.set_row_heights(title, rows, None)
        except (ValueError, TypeError, OverflowError) as error:
            self.error(error)
            return
        if changed:
            self.sheet.apply_row_heights(self.table_zoom)
            self.update_title()
            self.update_actions()
            self.status(qt("qt.edited"))

    def insert_column(self):
        title = self._active_table()
        if title is None:
            return
        dataset = self.project.tables[title]
        name, ok = QInputDialog.getText(self, qt("qt.insert_column"), qt("qt.column_name"),
                                        text=f"Column {len(dataset.raw.columns) + 1}")
        if ok and name.strip():
            column = self.sheet.currentIndex().column()
            size = len(dataset.raw.columns) if dataset.column_order is None else len(dataset.columns)
            position = column + 1 if 0 <= column < size else size
            self._apply_edit(title, lambda: self.project.insert_column(title, position, name.strip()))

    def create_numeric_series(self, column=None, start_row=None, *, full_column=False):
        from .numeric_series_dialog import NumericSeriesDialog

        title = self._active_table()
        if title is None or self.sheet is None:
            return
        dataset = self.project.tables[title]
        if column is None:
            box = self.sheet.box()
            if (box is not None and box[0] == 0 and box[2] == self.sheet.model().rowCount() - 1
                    and len(dataset.raw) > 0):
                full_column = True
        else:
            row = 0 if start_row is None else start_row
            box = (row, column, row, column)
        try:
            target = validate_series_target(
                dataset,
                box,
                locked=self.project.sheet_locked(("data", title)),
                read_only=stored_legacy_view(dataset),
                full_column=full_column,
            )
        except ValueError as error:
            self.error(error)
            return
        dialog = NumericSeriesDialog(self, dataset, target)
        try:
            if dialog.exec() != dialog.DialogCode.Accepted or dialog.plan is None:
                return
            plan = dialog.plan
        finally:
            dialog.deleteLater()
        self._apply_edit(title, lambda: self.project.create_numeric_series(title, plan, confirm_replace=True))
        if self.selected == ("data", title) and self.sheet is not None:
            self.sheet.select_block(plan.start_row, plan.column, plan.start_row + plan.count - 1, plan.column)
            self.update_actions()

    def delete_columns(self):
        title = self._active_table()
        if title is None:
            return
        _, left, _, right = self.sheet.box() or (0, 0, 0, -1)
        columns = list(range(left, right + 1))
        if columns:
            self._apply_edit(title, lambda: self.project.delete_columns(title, columns))

    def edit_variable_properties(self, column=None):
        from .variables import VariablesDialog

        if not self.prepare_project_change(self.edit_variable_properties):
            return
        title = self._active_table()
        if title is None or not self.actions["variable_properties"].isEnabled():
            return
        if column is None:
            column = self.sheet.currentIndex().column() if self.sheet is not None else -1
        project = self.project
        dialog = VariablesDialog(self, project.tables[title],
                                 lambda changes: project.change_variables(title, changes), column=column)
        try:
            if dialog.exec() == VariablesDialog.DialogCode.Accepted:
                self._apply_edit(title, lambda: dialog.affected)
        finally:
            dialog.deleteLater()

    def edit_category_order(self):
        from analisi.category_levels import LevelEditDraft
        from .category_order import CategoryOrderDialog

        if not self.prepare_project_change(self.edit_category_order):
            return
        title = self._active_table()
        if title is None:
            return
        dataset = self.project.tables[title]
        index = self.sheet.currentIndex().column() if self.sheet is not None else -1
        if not 0 <= index < len(dataset.columns) or dataset.source_indices[index] is None:
            self.error(tr("worksheet_order.select"))
            return
        column = dataset.columns[index]
        try:
            draft = LevelEditDraft(dataset, column)
        except ValueError as error:
            self.error(error)
            return
        if draft.can_rename and not draft.levels and not draft.saved:
            self.error(tr("category_levels.error.no_levels"))
            return
        if not draft.can_rename and len(draft.levels) < 2 and not draft.saved:
            self.error(tr("worksheet_order.empty"))
            return
        dialog = CategoryOrderDialog(
            self,
            column,
            draft,
            check_recipes=lambda plan: self.project.category_level_blockers(title, plan),
        )
        try:
            if dialog.exec() == CategoryOrderDialog.DialogCode.Accepted:
                plan = dialog.plan if dialog.plan is not None else draft.validate()
                if plan.has_changes:
                    self._apply_edit(title, lambda: self.project.apply_category_levels(title, plan))
        finally:
            dialog.deleteLater()

    def rename_column(self, column):
        title = self._active_table()
        if title is None:
            return
        dataset = self.project.tables[title]
        columns = dataset.columns
        if not 0 <= column < len(columns):
            return
        current = columns[column]
        if current in dataset.formulas:
            self.edit_formula(current)
            return
        name, ok = QInputDialog.getText(self, qt("qt.rename_column"), qt("qt.column_name"),
                                        text=str(current))
        if ok:
            self._apply_edit(title, lambda: self.project.rename_column(title, column, name))

    def edit_formula(self, name=None):
        """Formula…: a new calculated column, or the one selected (or double-clicked) to change."""
        title = self._active_table()
        if title is None or self.sheet is None or self.sheet.model().read_only:
            return
        dataset = self.project.tables[title]
        if name is None and self.sheet is not None:
            current = self.sheet.currentIndex()
            columns = dataset.columns
            if current.isValid() and current.column() < len(columns):
                selected = columns[current.column()]
                if selected in dataset.formulas:
                    name = selected
        self._open_formula_editor(title, dataset, name or "")

    def edit_formula_in_column(self, column):
        title = self._active_table()
        if title is None or self.sheet is None or self.sheet.model().read_only:
            return True
        dataset = self.project.tables[title]
        if not dataset.can_enter_formula(column):
            return False
        self._open_formula_editor(title, dataset, column=column)
        return True

    def _open_formula_editor(self, title, dataset, name="", *, column=None):
        from .formula import FormulaEditor

        if self.formula_editor is not None:
            self.formula_editor.focus_input()
            return
        panel = self.formula_editor = FormulaEditor(dataset, name, column=column)
        split = self.page.worksheet_split
        compact = split.width() < 560
        split.setOrientation(Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal)
        split.addWidget(panel)
        split.setStretchFactor(1, 0)
        if compact:
            split.setSizes([max(96, split.height() // 3), split.height() * 2 // 3])
        else:
            split.setSizes([split.width() - 318, 318])
        panel.expression.textChanged.connect(self._highlight_formula_references)
        panel.apply_requested.connect(lambda: self._apply_formula_editor(title, panel))
        panel.cancelled.connect(self._close_formula_editor)
        self._highlight_formula_references()
        panel.focus_input()

    def _highlight_formula_references(self):
        self.sheet.highlight_formula_columns(self.formula_editor.referenced_columns())

    def _close_formula_editor(self):
        panel, self.formula_editor = self.formula_editor, None
        panel.hide()
        panel.setParent(None)
        panel.deleteLater()
        self.sheet.highlight_formula_columns(())
        self.sheet.setFocus()

    def _apply_formula_editor(self, title, panel):
        if (self.formula_editor is not panel or self.gallery is not None or self.selected != ("data", title)
                or self.project.tables.get(title) is not panel.dataset or self.busy()):
            return
        values = panel.validated_formula()
        if values is None:
            return
        name, expression = values
        self._close_formula_editor()
        if panel.column is None:
            self._apply_edit(title, lambda: self.project.set_formula(title, name, expression))
        else:
            self._apply_edit(title, lambda: self.project.edit(
                title, "Edit formula", lambda table: table.set_worksheet_formula(
                    panel.column, expression, replace_values=panel.replace_values)))

    def freeze_worksheet_formula(self, column):
        title = self._active_table()
        if title is None or not self.project.tables[title].can_freeze_worksheet_formula(column):
            return
        self._apply_edit(title, lambda: self.project.edit(
            title, tr("worksheet.formula.freeze"), lambda table: table.freeze_worksheet_formula(column)))

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

    def _history_target(self, *, redo=False):
        """Return ``('shape', run)`` or ``('project', None)`` for Undo/Redo, or ``None`` if unavailable."""
        from .project import FormatChange, LayoutChange, StyleBatchChange

        shape_run = self.drawing.history_run()
        proj_change = self.project.history.next_change(redo=redo)
        if not self.project.can_apply_history(proj_change):
            proj_change = None
        if shape_run is not None:
            shape_hist = shape_run.shape_history
            shape_can = shape_hist.can_apply(redo=redo)
            if isinstance(proj_change, (FormatChange, LayoutChange, StyleBatchChange)):
                if not shape_can:
                    return ("project", None)
                seqs = getattr(shape_hist, "_trama_seqs", ())
                idx = shape_hist.position if redo else shape_hist.position - 1
                shape_seq = seqs[idx] if 0 <= idx < len(seqs) else 0
                if (proj_change.seq <= shape_seq) if redo else (proj_change.seq > shape_seq):
                    return ("project", None)
            return ("shape", shape_run) if shape_can else None
        return ("project", None) if proj_change is not None else None

    def undo(self, *, redo=False):
        if self.gallery is not None or self.busy():
            return
        if self.selected and self.selected[0] == "info" and self.info_editor is not None:
            if redo:
                self.info_editor.notes.redo()
            else:
                self.info_editor.notes.undo()
            self.info_editor.flush()
            return
        target = self._history_target(redo=redo)
        if target is None:
            return
        source, shape_run = target
        if source == "shape":
            self.drawing.apply_history(shape_run, redo=redo)
            return
        from .project import FormatChange, LayoutChange, StyleBatchChange
        next_change = self.project.history.next_change(redo=redo)
        if isinstance(next_change, (FormatChange, LayoutChange, StyleBatchChange)):
            if not self.settle_graph_draft():
                return
        was_moving = self.table_move.active
        selected_table = self.table_move.selected_id
        prev_selected = self.selected
        try:
            title, affected = self.project.undo(redo=redo)
        except (ValueError, TypeError, OverflowError) as error:
            self.error(error)
            return
        if self.project.undo_layout_index is not None:
            self.open_sheet(("layout", self.project.undo_layout_index))
            if (was_moving and prev_selected == ("layout", self.project.undo_layout_index)
                    and self.table_move.problem() is None):
                self.table_move.start(True, selected=selected_table)
            return
        if self.project.undo_style_uids:
            from .batch_figure_styles_dialog import t as batch_style_text
            status_text = (
                tr("command.redo") if redo else tr("command.undo")
                if isinstance(next_change, FormatChange)
                else batch_style_text("redone" if redo else "undone", count=len(self.project.undo_style_uids))
            )
            self._after_style_batch(
                self.project.undo_style_uids,
                status_text,
            )
            if (was_moving and prev_selected is not None and prev_selected[0] == "graph"
                    and self.selected == prev_selected and self.table_move.problem() is None):
                self.table_move.start(True, selected=selected_table)
            return
        if title is None:
            return
        if not affected and self.selected and self.selected[0] == "result":
            run = self.project.runs[self.selected[1]]
            if run.title == title:
                self._refresh_result_backgrounds(run)
                self.update_title()
                self.update_actions()
                return
        if (not affected and not self.project.undo_changed_data and self.selected == ("data", title)
                and self.sheet is not None):
            # Presentation-only changes keep the selection, current cell and scrolling.
            model = self.sheet.model()
            model.refresh_backgrounds()
            model.refresh_formats()
            self.sheet.refresh_text(self.project.tables[title].text_styles)
            self.update_title()
            self.update_actions()
            return
        self.show_sheet("data", title)
        if affected:
            self.refresh_runs(affected)

    def choose_table(self, *, sample=False):
        from PySide6.QtWidgets import QDialog
        from .table_setup import TableSetup, TableSetupDialog

        if self.busy():
            return
        setup = self.page.findChild(TableSetup) if self.selected is None and self.gallery is None else None
        if setup is not None:
            if sample:
                setup.sample.setChecked(True)
            setup.types.setFocus()
            return
        chooser = TableSetupDialog(self, sample=sample)
        try:
            if chooser.exec() == QDialog.DialogCode.Accepted:
                self.create_worksheet(*chooser.setup.selection())
        finally:
            chooser.deleteLater()

    def create_worksheet(self, template, sample):
        from analisi.table_templates import table_frame

        if self.busy():
            return
        title = f"{template.name} example" if sample else template.name
        try:
            title, = self.project.add_tables({title: table_frame(template, sample)})
        except ValueError as error:
            self.error(error)
            return
        self.show_sheet("data", title)
        if template.kind.casefold().startswith("xy") and template.columns[0] == "Row title":
            self.sheet.setCurrentIndex(self.sheet.model().index(0, 1))

    def new_table(self):
        if self.busy():
            return
        name = qt("qt.new_table_name", number=len(self.project.tables) + 1)
        title = self.project.new_table(self.project.unique_title(name))
        self.show_sheet("data", title)

    def paste_table(self):
        from analisi.data import _table
        from analisi.grid_data import clipboard_decimal_mark, clipboard_rows

        if self.busy():
            return
        try:
            headers, *rows = clipboard_rows(QGuiApplication.clipboard().text())
            if not rows:
                raise ValueError(qt("qt.paste_table_header"))
            table = _table(headers, rows, decimal_mark=clipboard_decimal_mark())
            title, = self.project.add_tables({qt("qt.pasted_data"): table})
        except ValueError as error:
            self.error(error)
            return
        self.show_sheet("data", title)

    def load_example(self):
        self.choose_table(sample=True)

    # == analyses ================================================================================
    def _analysis_input(self, *, allow_empty=False):
        if not self.project.tables:
            if allow_empty:
                import pandas as pd
                return None, pd.DataFrame({"A": pd.Series(dtype=float)})
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
        if frame.empty and not allow_empty:
            self.error(qt("qt.empty"))
            return None, None
        return title, frame

    def analyze(self, method=None, only=None):
        if self.busy():
            return
        title, frame = self._analysis_input(allow_empty=method in {power_plan.METHOD, mcnemar_power.METHOD,
                                                                  PLOT_FUNCTION})
        if frame is None:
            return
        current = (method, {}) if method else None
        self._ask(title, frame, current=current, only=only)

    def simulate_data(self):
        import pandas as pd

        if not self.busy():
            self._ask(None, pd.DataFrame(), current=("Simulate data", {}), only="Simulate data")

    def new_graph(self):
        self.analyze(only=GRAPHING)

    def _ask(self, title, frame, *, current=None, only=None, index=None, error=None, error_field=None, source=_KEEP,
             initial_field=None, graph_type=False):
        """Ask for the parameters, then calculate. ``source`` sets the result an analysis reads (a new link, or
        Change input result…); by default a new analysis reads its data table and an edit keeps its input."""
        run = self.project.runs[index] if index is not None else None
        reads = (run.source if run is not None else None) if source is _KEEP else source
        style = run.style if run is not None else None
        graph_type_source = (run.method, run.options) if graph_type else None
        dialog = AnalysisDialog(self, frame, current=current, only=only, error=error, error_field=error_field,
                                join_sources=self.project.join_sources(title, reads), join_left=title,
                                xy_left_scale=(style or {}).get("yscale", "linear"), graph_type_source=graph_type_source)
        if initial_field and error_field is None:
            dialog.focus_field(initial_field)
        if dialog.exec() != AnalysisDialog.DialogCode.Accepted or dialog.result is None:
            return
        method, options = dialog.result
        try:
            if title is None:
                if method == power_plan.METHOD:
                    name = tr("power.sheet")
                elif method == mcnemar_power.METHOD:
                    name = tr("mcnemar.power.sheet")
                else:
                    name = method_label(method)
                candidate = Run(method, self.project.unique_title(name), options)
            else:
                candidate = self.project.candidate(title, method, options, index=index, graph_type=graph_type,
                                                   source=None if source is _KEEP else source)
            if index is not None and source is not _KEEP and candidate.source != source:
                candidate.source = source
                self.project.analysis_graph(replacement=(index, candidate))
        except ValueError as error_:
            self.error(error_)
            return
        self.calculate_candidate(candidate, frame, index, only=only, create_table=title is None, graph_type=graph_type)

    def change_graph_type(self):
        if self.busy() or self.gallery is not None or not self.selected or self.selected[0] != "graph":
            return
        index = self.selected[1]
        run = self.project.runs[index]
        problem = self.project.graph_type_problem(run)
        if problem:
            self.error(problem)
            return
        if not self.settle_graph_draft():
            return
        try:
            frame = self.project.input_frame(run)
        except ValueError as error:
            self.error(error)
            return
        self._ask(run.title, frame, current=(run.method, run.options), only=GRAPH_TYPE_METHODS, index=index,
                  graph_type=True)

    def change_parameters(self):
        if self.busy() or not self.selected or self.selected[0] not in {"result", "graph"}:
            return
        if not self.settle_graph_draft():
            return
        index = self.selected[1]
        run = self.project.runs[index]
        if _saved_recipe(run):
            return
        try:
            frame = self.project.input_frame(run)
        except ValueError as error:
            self.error(error)
            return
        initial_field = None
        if self.selected[0] == "graph":
            initial_field = {PLOT_FUNCTION: FUNCTION_CURVES,
                             global_catalog.METHOD: global_catalog.PARAMETERS}.get(
                                 run.method, ANALYSIS_GRAPH_OPTIONS.get(run.method, (None,))[0])
            if initial_field is None and run.method in (MANN_WHITNEY, WILCOXON):
                active_plots = rank_plot_options(run.method, run.options)
                initial_field = active_plots[0] if active_plots else RANK_PLOT
        self._ask(run.title, frame, current=(run.method, run.options), index=index, initial_field=initial_field)

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
        if _saved_recipe(run):
            return

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
        grouped = self.project.grouped_format_inputs(run)
        dialog = GraphFormatDialog(self, run.result.figure.axes[0], style, xy=xy, grouped=grouped)
        if dialog.exec() != GraphFormatDialog.DialogCode.Accepted or dialog.result is None:
            return
        try:
            self.project.apply_format(
                run,
                dialog.result,
                xy_update=dialog.xy_update,
                xy_result=dialog.xy_result,
                grouped_update=dialog.grouped_update,
                grouped_result=dialog.grouped_result,
            )
        except ValueError as error:
            self.error(error)
            return
        self.show_sheet(*self.selected)
        self.update_actions()
        self.status(qt("qt.style_applied"))

    def graph_style_presets(self):
        """Graph → Figure styles…: preview a saved style on the graph on screen and commit it once."""
        from .graph_style_preset_dialog import GraphStylePresetDialog, message as preset_message, t as preset_text
        from .graph_style_presets import PresetLibrary

        if self.busy() or not self.selected or self.selected[0] != "graph":
            return
        index = self.selected[1]
        run = self.project.runs[index]
        problem = self.project.graph_format_problem(run)
        if problem:
            self.error(problem)
            return
        if not self.settle_graph_draft():
            return
        figure = run.result.figure
        confirmed = deepcopy(run.style or {})
        dialog = GraphStylePresetDialog(self, figure, self._figure_canvas(figure), confirmed, PresetLibrary())
        accepted = dialog.exec() == GraphStylePresetDialog.DialogCode.Accepted and dialog.result is not None
        style = dialog.result
        dialog.deleteLater()
        if not accepted:
            return
        # The dialog was modal, but the graph is read again before anything is stored.
        current = self.project.runs[index] if index < len(self.project.runs) else None
        if (self.selected != ("graph", index) or current is not run or run.result is None
                or run.result.figure is not figure or (run.style or {}) != confirmed):
            self.error(preset_text("changed"))
            return
        try:
            validate_graph_style(figure.axes[0], style)
            apply_style(figure, style)
        except ValueError as error:
            try:
                apply_style(figure, confirmed)
            except ValueError:
                pass
            self.error(preset_message(error))
            return
        self.commit_style(run, style)
        self.show_sheet(*self.selected)
        self.status(preset_text("applied"))

    def _after_style_batch(self, changed_uids, status_text):
        """Refresh the visible sheet, Inspector, gallery or layout after a batch style commit/undo/redo."""
        if self.gallery is not None:
            self.gallery.sync()
        elif self.selected is not None and self.selected[0] in {"graph", "layout"}:
            self.show_sheet(*self.selected)
        elif (self.selected is not None and self.selected[0] == "data" and self.page is not None
              and self.page.worksheet_preview is not None and self.page.worksheet_preview.enabled):
            self.page.worksheet_preview.refresh()
        self.update_title()
        self.update_actions()
        if status_text:
            self.status(status_text)

    def batch_figure_styles(self):
        """Change → Apply style to multiple graphs…: apply one saved style atomically to chosen graphs."""
        from .batch_figure_styles_dialog import (BatchFigureStylesDialog, batch_message, batch_style_rows,
                                                 format_summary, t as batch_style_text)
        from .graph_style_presets import PresetLibrary

        if self.busy():
            return
        if not self.settle_graph_draft():
            return
        project = self.project
        rows = batch_style_rows(project)
        if not rows:
            self.error(batch_style_text("no_graphs"))
            return
        current_uid = None
        if self.gallery is None and self.selected and self.selected[0] == "graph":
            current_uid = project.runs[self.selected[1]].uid
        expected = {
            row.uid: (row.run, row.run.result,
                      row.run.result.figure if row.run.result is not None else None,
                      deepcopy(row.run.style or {}))
            for row in rows if row.eligible
        }
        dialog = BatchFigureStylesDialog(self, project, rows, PresetLibrary(), current_uid=current_uid)
        accepted = dialog.exec() == BatchFigureStylesDialog.DialogCode.Accepted and dialog.result is not None
        payload = dialog.result
        dialog.deleteLater()
        if not accepted:
            return
        if self.project is not project or self.busy():
            self.error(batch_style_text("changed"))
            return
        selected_uids, preset = payload
        try:
            outcome = project.commit_style_batch(selected_uids, preset, expected=expected)
        except Exception as error:  # noqa: BLE001 - report validation or figure failure without partial writes
            self.error(batch_message(error))
            return
        summary = format_summary(outcome)
        self.last_batch_style_summary = summary
        if outcome.changed_uids:
            self._after_style_batch(outcome.changed_uids, summary)
        else:
            self.status(summary)

    def _figure_canvas(self, figure):
        """The canvas that shows ``figure`` on the active page, if any."""
        for canvas in getattr(self.page, "canvases", ()) or ():
            if canvas.figure is figure:
                return canvas
        return None

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

    def edit_imported_panel(self, index):
        if self.busy():
            return
        from .layout_dialog import ImportedPanelDialog

        run = self.project.runs[index]
        options = dict(run.options)
        edits = options.get(LEGACY_PANEL_EDITS) or {}
        try:
            dialog = ImportedPanelDialog(self, options[LEGACY_PREVIEW], options[LEGACY_EDITABLE_PANELS], edits)
        except (KeyError, TypeError, ValueError):
            self.error(ui("Invalid legacy layout edits."))
            return
        if dialog.exec() != ImportedPanelDialog.DialogCode.Accepted or dialog.result is None or dialog.result == edits:
            return
        if dialog.result:
            options[LEGACY_PANEL_EDITS] = dialog.result
        else:
            options.pop(LEGACY_PANEL_EDITS, None)
        try:
            candidate = self.project.candidate(run.title, run.method, options, index=index)
        except ValueError as error:
            self.error(error)
            return
        self.calculate_candidate(candidate, self.project.tables[run.title].frame(mask_excluded=True), index)

    # -- linked tables -----------------------------------------------------------------------------
    def linked_table_targets(self):
        """Where a table can go: every native graph that can be formatted and every layout, as ``(caption, ref)``."""
        from .gallery_catalog import graph_runs
        targets = []
        for index, run in graph_runs(self.project):
            if (run.method not in LEGACY_GRAPH_METHODS and run.result is not None
                    and self.project.graph_format_problem(run) is None):
                targets.append((tr("linked_table.place.graph", name=self.project.sheet_title(("graph", index))),
                                ("graph", index)))
        for index, layout in enumerate(self.project.layouts):
            targets.append((tr("linked_table.place.layout", name=layout.name), ("layout", index)))
        return targets

    def edit_linked_tables(self, *, preset=None, reference=None):
        """Insert → Linked table…: the tables of the selected graph or layout (or of ``reference``)."""
        from analisi.linked_tables import TABLES
        from .linked_tables import LinkedTablesDialog
        if self.busy():
            return
        reference = reference or self.selected
        if not reference or reference[0] not in {"graph", "layout"}:
            self.error(tr("linked_table.native"))
            return
        kind, key = reference
        if kind == "graph":
            run = self.project.runs[key]
            problem = self.project.graph_format_problem(run)
            if problem or run.method in LEGACY_GRAPH_METHODS:
                self.error(problem or tr("linked_table.native"))
                return
            if not self.settle_graph_draft():
                return
            records, owner = (run.style or {}).get(TABLES, []), self.project.sheet_title(("graph", key))
        else:
            layout = self.project.layouts[key]
            records, owner = layout.tables, layout.name
        dialog = LinkedTablesDialog(self, self.project, records, owner=owner, preset=preset)
        if dialog.exec() != LinkedTablesDialog.DialogCode.Accepted or dialog.result is None \
                or dialog.result == list(records):
            return
        self.commit_linked_tables(reference, dialog.result)

    def commit_linked_tables(self, reference, records):
        """Store ``records`` as the tables of a graph or layout: one undoable step, then redraw."""
        from dataclasses import replace as replaced
        from analisi.linked_tables import TABLES, sync_tables
        kind, key = reference
        try:
            if kind == "graph":
                run = self.project.runs[key]
                style = deepcopy(run.style or {})
                before = deepcopy(style)
                if records:
                    style[TABLES] = records
                else:
                    style.pop(TABLES, None)
                self.project.apply_format(run, style)
                self.project.history.record_style_batch("Linked tables", {run.uid: before},
                                                        {run.uid: deepcopy(style)})
                live = (self._figure_canvas(run.result.figure)
                        if self.gallery is None and self.selected == reference and run.result is not None else None)
            else:
                self.project.put_layout(replaced(self.project.layouts[key], tables=list(records)), key)
                live = (next(iter(getattr(self.page, "canvases", ()) or ()), None)
                        if self.gallery is None and self.selected == reference else None)
        except ValueError as error:
            self.error(translate_message(error, "linked_table.error."))
            return False
        if live is not None:
            if kind == "layout":
                sync_tables(live.figure, self.project.layout_table_specs(self.project.layouts[key]))
            live.draw_idle()
            self.update_title()
            self.update_actions()
            self.table_move.sync()
        else:
            self.show_sheet(kind, key)
        self.status(tr("linked_table.applied"))
        return True

    def insert_linked_table_from_selection(self):
        """Insert → Linked table from selection…: the selected cells of a worksheet or result, placed on a graph
        or layout chosen in the window that opens."""
        from analisi.linked_tables import MAX_TABLES, TABLES
        from .linked_tables import LinkedTableDialog
        if self.busy():
            return
        target = self.text_format.target()
        if target is None:
            self.error(tr("linked_table.no_selection"))
            return
        top, left, bottom, right = target.box
        if self.selected[0] == "data":
            title = self.selected[1]
            dataset = self.project.tables[title]
            choice = {"kind": "sheet", "sheet": title, "label": title, "rows": len(dataset.raw),
                      "columns": len(dataset.columns)}
            box = (top, left, min(bottom, len(dataset.raw) - 1), min(right, len(dataset.columns) - 1))
        else:
            run = self.project.runs[self.selected[1]]
            name = tuple(run.result.tables)[self.result_tabs.currentIndex()]
            if right == 0:
                self.error(tr("linked_table.row_titles"))
                return
            choice = next((entry for entry in self.project.table_source_choices()
                           if entry["kind"] == "result" and entry["analysis"] == run.uid and entry["table"] == name),
                          None)
            if choice is None:
                self.error(tr("linked_table.no_selection"))
                return
            box = (top, max(left, 1) - 1, min(bottom, choice["rows"] - 1), right - 1)
        targets = self.linked_table_targets()
        if not targets:
            self.error(tr("linked_table.no_target"))
            return
        reference = self.selected if self.selected in {ref for _, ref in targets} else None
        dialog = LinkedTableDialog(self, self.project, preset=(choice, box), targets=targets)
        if reference is not None:
            dialog.choose_target(reference)
        if dialog.exec() != LinkedTableDialog.DialogCode.Accepted or dialog.result is None:
            return
        kind, key = dialog.target
        current = ((self.project.runs[key].style or {}).get(TABLES, []) if kind == "graph"
                   else self.project.layouts[key].tables)
        if len(current) >= MAX_TABLES:
            self.error(tr("linked_table.limit", count=MAX_TABLES))
            return
        self.commit_linked_tables(dialog.target, [*current, dialog.result])

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
        problem = (pg.graph_problem(run.method, run.options) if run.method not in LEGACY_GRAPH_METHODS
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
        from analisi.graph_annotations import ANNOTATIONS
        if self.busy() or not self.selected or self.selected[0] != "graph":
            return
        run = self.project.runs[self.selected[1]]
        problem = self.project.graph_format_problem(run)
        if problem or run.method in LEGACY_GRAPH_METHODS:
            self.error(problem or tr(native))
            return
        if not self.settle_graph_draft():
            return
        style = deepcopy(run.style or {})
        before = deepcopy(style)
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
        if key == ANNOTATIONS:  # Shapes have their own history; annotations are one Undo step like a cell format.
            self.project.history.record_style_batch("Annotations", {run.uid: before}, {run.uid: deepcopy(style)})
        self.show_sheet(*self.selected)
        self.status(tr(applied))

    def calculate_candidate(self, candidate, frame, index, *, only=None, create_table=False, graph_type=False):
        pairwise = self.project.pairwise_snapshot(candidate)
        layout_data = self.project.layout_panel_data(candidate)
        join_data = self.project.join_data(candidate)  # read here: the worker never looks a sheet up
        control = CalculationControl()

        def done(future, cancelled):
            if cancelled:
                self.status(qt("qt.cancelled"))
                return
            try:
                result = future.result()
            except (MonteCarloCancelled, ChainCancelled, WeightedComparisonCancelled):
                self.status(qt("qt.cancelled"))
                return
            except Exception as error:  # Field and data errors reopen the dialog with the message.
                self.status(qt("qt.failed"))
                if candidate.method == SAVED_BINARY_LAYOUT:
                    self.error(ui(str(error)))
                    return
                field = error.field if isinstance(error, FieldError) else None
                self._ask(None if create_table else candidate.title, frame,
                          current=(candidate.method, candidate.options), only=only,
                          index=index, error=str(error), error_field=field, source=candidate.source, graph_type=graph_type)
                return
            if create_table:
                tables = ({name: result_as_table(table) for name, table in result.tables.items()}
                          if candidate.method == "Simulate data" else {candidate.title: frame})
                try:
                    titles = self.project.add_tables(tables)
                except ValueError as error:
                    self.error(error)
                    return
                if candidate.method == "Simulate data":
                    self.show_sheet("data", titles[0])
                    self.status(qt("qt.complete", method=method_label(candidate.method)))
                    return
            try:
                new_index, dependents = self.project.add_result(candidate, result, index, graph_type=graph_type)
            except ValueError as error:
                self.status(qt("qt.failed"))
                self.error(error)
                return
            message = qt("qt.complete", method=method_label(candidate.method))
            if result.style_warning:
                message += f" {result.style_warning}"
            keep = index is not None and self.selected is not None and self.selected[0] in {"result", "graph"}
            if keep and self.selected[0] == "graph" and result.figure is None:
                keep = False
            self.show_sheet(self.selected[0] if keep else preferred_view(candidate, result), new_index)
            self.status(message)
            if dependents:
                self.refresh_runs(dependents)

        extra = {} if join_data is None else {"join_data": join_data}
        future = self.worker.submit(compute, candidate, frame, control, layout_data, pairwise, **extra)
        self._start(future, control, done, qt("qt.running", method=method_label(candidate.method)))

    def refresh_runs(self, runs, *, reopen_analysis_field_error=False):
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
            recovery = None
            try:
                outcomes = future.result()
            except (ChainCancelled, WeightedComparisonCancelled):
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
                    self.status(qt("qt.update_failed", count=len(errors), first=translate_message(errors[0], "xy.error.")) if errors
                                else qt("qt.updated", count=len(outcomes)))
                    if reopen_analysis_field_error and errors:
                        for index, run in enumerate(self.project.runs):
                            outcome = outcomes.get(run.uid)
                            if (run.method in ANALYSIS_GRAPH_OPTIONS and run.result is not None and outcome is not None
                                    and isinstance(outcome.error, FieldError)):
                                recovery = index, run, outcome.error
                                break
            if self.selected and self.selected[0] != "data" and self.gallery is None:
                self.show_sheet(*self.selected)
            else:
                self.refresh()
            if recovery is not None:
                index, run, error = recovery
                try:
                    frame = self.project.input_frame(run)
                except ValueError:
                    return  # A linked input that also failed already has its warning.
                self._ask(run.title, frame, current=(run.method, run.options), index=index,
                          error=str(error), error_field=error.field)

        future = self.worker.submit(Project.run_refresh, job)
        self._start(future, job.control, done, qt("qt.updating", count=len(job.selected)))
        if self.selected and self.selected[0] != "data" and self.gallery is None:
            self.show_sheet(*self.selected)

    # == families ================================================================================
    def browse_family(self, kind=None):
        from analisi.family_workflow import FamilyError, plan_family
        from .family import family_error_text

        selected = self._family_start()
        if selected is None:
            return
        project = self.project
        try:
            plan = plan_family(project.tables, project.layouts, tuple(project.info_sheets.values()), selected)
        except FamilyError as error:
            self.error(family_error_text(error))
            return

        if kind == "data" and plan.start_table is not None:
            self.open_sheet(("data", plan.start_table))
            return
        kinds = {"data": tr("nav.data_tables"), "info": tr("nav.info"), "result": tr("nav.results"),
                 "graph": tr("nav.graphs"), "saved-layout": tr("nav.layouts"), "layout": tr("nav.layouts")}
        captions, refs = [], []
        for index in range(self.sheet_picker.count()):
            ref = tuple(self.sheet_picker.itemData(index))
            section, key = ref
            if kind is not None and section != kind:
                continue
            if section == "data":
                belongs = key in plan.tables
            elif section == "info":
                belongs = key in plan.infos or key in plan.global_infos
            elif section == "layout":
                belongs = key in plan.layouts
            else:
                run = project.runs[key]
                belongs = run.slot in plan.slots.get(run.title, ())
            if belongs:
                caption = self.sheet_picker.itemText(index)
                captions.append(f"{kinds[section]} · {caption}" if kind is None else caption)
                refs.append(ref)
        if not refs:
            self.status(qt("qt.family_empty"))
            return
        if len(refs) == 1 and kind is not None:
            self.open_sheet(refs[0])
            return
        from .family import FamilySheetsDialog

        dialog = FamilySheetsDialog(self, captions, refs, current=self.selected)
        try:
            if dialog.exec() and dialog.selected is not None:
                self.open_sheet(dialog.selected)
        finally:
            dialog.deleteLater()

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
            except (ChainCancelled, WeightedComparisonCancelled):
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
        from .family import FamilyDialog, family_blank_choices, family_describer, family_error_text
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
        dialog = FamilyDialog(self, "duplicate", kind, describe, initial=initial,
                              blank_choices=family_blank_choices(self.project, selected))
        if dialog.exec() != FamilyDialog.DialogCode.Accepted or dialog.result is None:
            return
        name, include = dialog.result
        blanks = dialog.blanks()
        project, control = self.project, CalculationControl()
        tables, layouts, infos = project.tables, project.layouts, tuple(project.info_sheets.values())

        def finish(bundle):
            focus = project.apply_family(bundle)
            if focus[0] != "data":
                cleared = next((title for title in bundle.plan.tables if blanks.columns(tables[title])), None)
                if cleared is not None:
                    focus = ("data", bundle.table_names[cleared])
            self.open_sheet(focus)
            self.status(tr("family.duplicated", tables=len(bundle.tables), analyses=bundle.analysis_count,
                           layouts=len(bundle.layouts), infos=len(bundle.infos)))

        self._family_job(lambda: duplicate_family(tables, layouts, infos, selected, name=name, include_layouts=include,
                                                  cancel=control.cancel, blanks=blanks),
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

    # == repeat analysis on other sheets (trama_qt/repeat_analysis.py) ===========================
    def repeat_analysis(self):
        from .repeat_analysis import repeat_analysis
        repeat_analysis(self)

    # == analysis templates (trama_qt/templates.py) =============================================
    def save_template(self):
        from .templates import save_template
        save_template(self)

    def new_from_template(self, path=None):
        from .templates import new_from_template
        new_from_template(self, path)

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
        self.drawing.cancel()
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
        deferred, self._deferred = self._deferred, []
        for retry in deferred:
            retry()
        queued, self._queued = self._queued, []
        for path, import_data in queued:
            self.open_path(path, import_data=import_data)  # Queues again by itself if this one starts a job.

    def cancel_calculation(self):
        if self.job is not None and self.job.control is not None:
            self.job.control.cancel.set()
            self.status(qt("qt.cancelled"))

    # == files ===================================================================================
    def _ask_save(self):
        """Save, Discard or Cancel for the active project."""
        return QMessageBox.question(
            self, qt("qt.unsaved_title"), qt("qt.unsaved", name=self.project.title),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)

    def confirm_saved(self):
        """Save, Discard or Cancel for the active project only. True when it may be left behind."""
        self.flush_info()
        if not self.project.dirty:
            return True
        answer = self._ask_save()
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

    def prepare_project_change(self, retry=None):
        """Before leaving the active tab: settle the Inspector draft, store typed cells and Info notes, and make
        sure no calculation is running. False keeps the active tab as it is. When storing the last edit starts a
        recalculation, ``retry`` runs once it has ended (the edit stays with its own project meanwhile)."""
        if self.busy(warn=False):
            self.status(qt("qt.wait_projects"))
            return False
        if not self.settle_graph_draft():
            return False
        self._commit_sheet_edit()
        self.flush_info()
        if self.busy(warn=False):
            if retry is not None:
                self._deferred.append(retry)
                self.status(qt("qt.switch_later"))
            else:
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

        QTimer.singleShot(0, self, scroll)

    def _activate(self, session, *, capture=True):
        self.close_worksheet_notes()
        if capture:
            self._capture()
        else:
            self.dispose_inspector()
            self.info_editor = None
        self._drop_gallery()
        self.gallery_view = {"kind": None, "text": ""}
        self.sessions.active = session
        self._install()

    def switch_project(self, session):
        """Make ``session`` the active tab. False (and the tab strip unchanged) when the active tab must stay."""
        if session is self.sessions.active:
            return True
        if session not in self.sessions.items or not self.prepare_project_change(lambda: self.switch_project(session)):
            self._sync_tabs()
            return False
        self._activate(session)
        return True

    def _project_tab_changed(self, index):
        if 0 <= index < len(self.sessions) and self.sessions[index] is not self.sessions.active:
            self.switch_project(self.sessions[index])

    def _tab_close_button(self):
        button = QToolButton()
        button.setObjectName("projectTabClose")
        button.setIcon(theme.icon("x", theme.T["text3"], 14))
        button.setIconSize(theme.icon_size(14))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(qt("qt.close_project_hint"))
        button.setAccessibleName(tr("command.close_project"))
        button.clicked.connect(lambda _checked=False, owner=button: self._tab_close_clicked(owner))
        return button

    def _tab_close_clicked(self, button):
        for index in range(self.project_tabs.count()):
            if self.project_tabs.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.project_tabs.tabCloseRequested.emit(index)
                return

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
        if not self.prepare_project_change(self.new_project):
            return
        self.project_number += 1
        self._activate(self.sessions.add(Project(self.project_number)))

    def close_project(self, session=None):
        """Close one project tab: Save, Discard or Cancel for that project only. The last tab becomes empty."""
        if session is not None and not self.switch_project(session):
            return False
        if not self.prepare_project_change(lambda: self.close_project(session)) or not self.confirm_saved():
            return False
        closing = self.sessions.active
        if self.recovery is not None:  # Saved or discarded: its recovery copies go (Cancel returned above).
            self.recovery.forget(closing.project)
        target = self.sessions.neighbour(closing)
        if target is None:
            self._drop_gallery()
            self.gallery_view = {"kind": None, "text": ""}
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
        decisions = []
        for session in [active] + [other for other in self.sessions if other is not active]:
            if not session.project.dirty:
                continue
            if session is not self.sessions.active:
                self._activate(session)
            answer = self._ask_save()
            if answer == QMessageBox.StandardButton.Cancel:  # Nothing has been saved or closed yet.
                return False
            decisions.append((session, answer))
        for session, answer in decisions:
            if answer == QMessageBox.StandardButton.Save:
                if session is not self.sessions.active:
                    self._activate(session)
                if not self.save():  # Failed or cancelled: the window stays, on that project.
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
        initial_sheet, import_warnings = [], []
        try:
            if replace:
                existing = self.sessions.find(path)
                if existing is not None:
                    if self.switch_project(existing):
                        remember_project(path)
                        self.status(qt("qt.already_open", name=path.name))
                    return
                reuse = self.project.is_empty()
                if not reuse and self.sessions.full():
                    raise ValueError(qt("qt.too_many_projects", count=MAX_PROJECT_TABS))
                if not self.prepare_project_change(lambda: self.open_path(path, import_data=import_data)):
                    return
                number = self.project.number if reuse else self.project_number + 1
                project = Project(number)
                # Read before changing the active tab.
                titles = project.load(path, initial_sheet=initial_sheet, import_warnings=import_warnings)
                if suffix != ".alab":
                    project.origin, project.dirty = path, False
                self._put_project(project, reuse=reuse)
                remember_project(path)
                self.status(tr("status.opened", name=path.name))
            elif import_data and suffix in TEXT_SUFFIXES:  # Import text data: choose rows, columns and format.
                from .text_import import TextImportDialog
                dialog = TextImportDialog(self, path)
                if dialog.exec() != TextImportDialog.DialogCode.Accepted or dialog.result is None:
                    return
                titles = self.project.add_tables({path.stem: dialog.result})
                if dialog.link_spec is not None:  # Link to the source file: File → Update from file… reads it again.
                    self.project.attach_source(titles[0], dialog.link_spec)
                self.status(qt("qt.imported", count=len(titles)))
            else:
                titles = self.project.load(path, import_warnings=import_warnings)
                self.status(qt("qt.imported", count=len(titles)))
        except Exception as error:  # Nothing changed: no tab was added and the active one is as it was.
            self.error(qt("qt.open_failed", name=path.name, error=error))
            return
        if import_warnings:
            self.status(qt("qt.import_skipped", items=", ".join(dict.fromkeys(import_warnings))))
        if focus := initial_sheet_reference(initial_sheet, self.project.runs, run_view):
            self.open_sheet(focus)
            return
        sheets = [title for title in titles if not stored_legacy_view(self.project.tables[title])]
        if sheets:
            self.show_sheet("data", sheets[0])
        elif self.project.runs:
            run = self.project.runs[0]
            self.open_sheet((preferred_view(run, run.result), 0))
        elif replace and self.project.info_sheets:
            self.show_sheet("info", next(iter(self.project.info_sheets)))
        else:
            self.refresh()

    def _put_project(self, project, *, reuse):
        """Show a project just read in the empty active tab (``reuse``) or in a new tab."""
        if reuse:
            self._drop_gallery()
            self.gallery_view = {"kind": None, "text": ""}
            self.dispose_inspector()
            self.info_editor = None
            if self.recovery is not None:
                self.recovery.forget(self.project)
            project.number = self.project.number
            self.sessions.active.reset(project)
        else:
            self.project_number = max(self.project_number + 1, project.number)
            project.number = self.project_number
            self._activate(self.sessions.add(project))

    # == recovery copies ==========================================================================
    def room_for_project(self):
        return self.project.is_empty() or not self.sessions.full()

    def place_project(self, project):
        """Open a project read elsewhere (a recovered copy) in its own tab. False when the active tab must stay."""
        if not self.room_for_project() or not self.prepare_project_change():
            return False
        self._put_project(project, reuse=self.project.is_empty())
        sheets = [title for title in project.tables if not stored_legacy_view(project.tables[title])]
        if sheets:
            self.show_sheet("data", sheets[0])
        elif project.info_sheets:
            self.show_sheet("info", next(iter(project.info_sheets)))
        else:
            self.refresh()
        return True

    def recover_projects(self):
        """File → Recover projects…: choose copies to reopen, leave for later or delete."""
        if self.recovery is None or self.busy():
            return
        self.recovery.hide_notice()
        dialog = RecoveryDialog(self.recovery, self)
        if dialog.exec() == RecoveryDialog.DialogCode.Accepted and dialog.chosen:
            self.recovery.recover(dialog.chosen)

    def recovery_settings(self):
        if self.recovery is not None:
            RecoverySettingsDialog(self.recovery, self).exec()

    def save(self, *, as_new=False):
        if self.busy() or not self.settle_graph_draft():
            return False
        project = self.project
        self._commit_sheet_edit()
        self.flush_info()
        if self.job is not None:
            # Committing the editor can start a linked calculation. Save this project when it settles.
            def save_after_edit():
                if self.project is project:
                    self.save(as_new=as_new)

            self._deferred.append(save_after_edit)
            return False
        if not self.project.tables and not self.project.info_sheets:
            return False
        path = self.project.path if not as_new else None
        if path is None:
            suggested = (self.project.origin.with_suffix(".alab").name if self.project.origin
                         else self.project.save_suggestion or "")
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
        if self.recovery is not None:
            self.recovery.saved(self.project)
        remember_project(path)
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
                run = None
                if kind == "layout":
                    layout = self.project.layouts[key]
                    figure, name = self.project.layout_figure(layout), layout.name
                else:
                    run = self.project.runs[key]
                    figure = run.result.figure if run.result is not None else None
                    name = self.project.sheet_title(self.selected)
                vector = self.project.imported_vector_format(run) if run is not None else None
                if figure is None and vector is None:
                    raise ValueError(qt("qt.layout_missing"))
                filters = [("PNG (*.png)", ".png"), ("SVG (*.svg)", ".svg"),
                           ("PDF (*.pdf)", ".pdf"), ("TIFF (*.tif *.tiff)", ".tif")] if figure is not None else []
                native_suffix = f".{vector}" if vector else None
                if native_suffix:
                    label = qt("qt.vector_edited" if run.method == SAVED_EDITABLE_GRAPH else "qt.vector_original")
                    filters = [(f"{vector.upper()} — {label} (*{native_suffix})", native_suffix),
                               *(item for item in filters if item[1] != native_suffix)]
                path, chosen = QFileDialog.getSaveFileName(
                    self, qt("qt.export_graph"), f"{name}{filters[0][1]}",
                    ";;".join(label for label, _ in filters))
                if path:
                    if not Path(path).suffix:
                        path += dict(filters).get(chosen, filters[0][1])
                    if Path(path).suffix.lower() == native_suffix:
                        self.project.export_imported_vector(run, path)
                    elif figure is None:
                        raise ValueError(qt("qt.layout_missing"))
                    elif kind == "layout":
                        self.project.export_layout(layout, path)
                    else:
                        export_graph(figure, path, size_inches=imported_paper(run))
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
                path, _ = QFileDialog.getSaveFileName(self, qt("qt.export_table"), f"{safe_stem(name)}.csv", "CSV (*.csv)")
                if path:
                    if not Path(path).suffix:
                        path += ".csv"
                    safe_csv(path, frame, index=index)
            if path:
                self.status(qt("qt.exported", name=Path(path).name))
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def export_current_layout_emf(self, run):
        if not self.settle_graph_draft():
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("layout.export_current_emf"), f"{run.name}.emf", "EMF (*.emf)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".emf"
        try:
            self.project.export_imported_vector(run, path, current_layout=True)
        except (OSError, ValueError, TypeError) as error:
            self.error(error)
            return
        self.status(qt("qt.exported", name=Path(path).name))

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
        raster_panels = kind == "saved-layout" and ZIP_LAYOUT not in run.options
        recorded_paper = imported_paper(None if layout is not None else run)
        size = tuple(recorded_paper or figure.get_size_inches())
        dialog = ExportOptionsDialog(self, size, raster_panels=raster_panels,
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
                export_graph(figure, path, settings, size_inches=recorded_paper)
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
        entries, notes = bundle_sheets(self.project, graphs, LEGACY_GRAPH_METHODS)
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

    def export_batch(self):
        """File → Export multiple figures…: one PNG, SVG or PDF per graph or layout of the active project."""
        if self.busy() or not self.settle_graph_draft():
            return
        from .batch_export_dialog import BatchExportDialog, batch_rows
        project = self.project  # The active project: the dialog is modal, so it cannot change while it runs.
        rows = batch_rows(project, LEGACY_GRAPH_METHODS)
        if not any(row.ready for row in rows):
            self.error(" ".join([tr("pdf.empty"), *dict.fromkeys(row.reason for row in rows)]))
            return
        folder = project.path.parent if project.path is not None else ""
        dialog = BatchExportDialog(self, project, rows, folder)
        try:
            dialog.exec()
            if dialog.outcomes is not None:
                counts = dialog.counts()
                self.status(batch_text("status", done=counts["done"], total=len(dialog.outcomes),
                                       folder=dialog.batch.folder.name or str(dialog.batch.folder)))
        finally:
            dialog.deleteLater()

    def export_report(self):
        from .report_dialog import export_report
        export_report(self)

    def import_excel_workbook(self, path=None):
        from .excel_workbook import import_workbook
        import_workbook(self, path)

    def export_excel_workbook(self, path=None):
        from .excel_workbook import export_workbook
        export_workbook(self, path)

    def choose_processes(self):
        if self.busy():
            return
        from .processes import ProcessesDialog

        path = config_path()
        dialog = ProcessesDialog(path, self)
        if dialog.exec() == ProcessesDialog.DialogCode.Accepted:
            parallel.configure(dialog.setting)
            self.status(tr("processes.saved", count=parallel.status()["processes"]))

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

    def show_shortcuts(self):
        from .shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

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
        self.drawing.cancel()
        self.table_move.cancel()
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
        self.close_worksheet_notes()
        self._drop_gallery()
        self.worker.shutdown(wait=False, cancel_futures=True)
        if self.recovery is not None:  # Every project was saved or discarded: their copies go.
            self.recovery.shutdown([session.project for session in self.sessions])
        if self._release_gc is not None:
            self._release_gc()
        event.accept()
