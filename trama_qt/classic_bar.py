"""The Classica menu and compact two-row toolbar, backed by the window's Qt actions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget
from itertools import zip_longest

from analisi.i18n import tr, ui

from . import theme


MENUS = (
    ("File", ("new_project", "new_table", "open", "import", "import_excel", "recover", "|",
              "save", "save_as", "save_template", "new_from_template", "|", "export", "export_options",
              "export_pdf", "export_batch", "export_report", "export_excel", "|", "close_project", "classic", "about", "exit")),
    ("Edit", ("undo", "redo", "|", "cut", "copy", "paste", "paste_special", "paste_transpose", "paste_table",
              "clear_cells", "|", "exclude", "delete_rows", "language")),
    ("View", ("navigator", "find_sheet", "combined_navigator", "gallery", "previous_sheet", "next_sheet", "|",
              "worksheet_preview", "analysis_graph", "analysis_tables", "inspector", "|",
              "sheet_zoom_in", "sheet_zoom_out", "sheet_zoom_reset", "|",
              "theme_system", "theme_light", "theme_dark")),
    ("Insert", ("new_table", "new_info", "insert_row", "insert_column", "formula", "|",
                "new_graph", "new_layout", "pairwise", "compact_letters", "annotations", "shapes")),
    ("Analyze", ("analyze", "change", "recalculate", "analyze_result", "source_analysis", "change_input",
                 "repeat_analysis", "use_result", "|", "descriptive", "ttest", "anova", "correlation", "correlation_matrix",
                 "linear", "nonlinear", "survival", "contingency", "load_example")),
    ("Change", ("change", "format_graph", "graph_style_presets", "plot_margins", "edit_layout", "category_order", "cell_background", "clear_cell_background", "number_format", "|",
                "info_properties", "info_up", "info_down", "remove_info")),
    ("Arrange", ("arrange_shapes", "new_layout", "edit_layout")),
    ("Family", ("family_data", "family_info", "family_results", "family_graphs", "family_gallery", "|",
                "duplicate_family", "save_family")),
    ("Tools", ("power", "simulate", "monte_carlo", "transpose_xy", "plot_function", "|", "search")),
    ("Settings", ("language", "table_font", "processes", "recovery_settings")),
)

# Group, first row, second row, tall button, and the density at which short captions fit.
GROUPS = (
    ("File", ("new_table", "open"), ("save", "save_as"), None, 2),
    ("Sheet", ("insert_row", "insert_column", "new_info"), ("exclude", "formula"), None, 3),
    ("Undo", ("undo",), ("redo",), None, 4),
    ("Clipboard", ("cut", "copy"), ("paste_special", "paste_table"), "paste", 1),
    ("Analysis", ("linear", "nonlinear"), ("descriptive", "correlation_matrix"), "analyze", 1),
    ("Change", ("change", "format_graph"), (), None, 3),
    ("Import / Export", ("export",), ("export_options",), "import", 1),
    ("Graph", ("new_layout",), ("pairwise",), "new_graph", 3),
)

SHORT = {"new_table": "ribbon.new", "open": "ribbon.open", "save": "ribbon.save",
         "save_as": "ribbon.save_as", "import": "ribbon.import", "export": "ribbon.export"}

ICONS = {
    "new_table": "new", "open": "open", "save": "save", "save_as": "saveas",
    "insert_row": "addrow", "insert_column": "addcol", "new_info": "info",
    "exclude": "exclude", "formula": "formula", "undo": "undo", "redo": "redo",
    "cut": "cut", "copy": "copy", "paste_special": "pastespecial", "paste_table": "pastetable", "paste": "paste",
    "linear": "linreg", "nonlinear": "curve", "descriptive": "bars", "correlation_matrix": "heatmap",
    "analyze": "analyze", "change": "params", "format_graph": "format", "import": "import",
    "export": "export", "export_options": "exportopts", "new_layout": "layout",
    "pairwise": "pairwise", "new_graph": "graph",
}


def build_menus(window):
    bar = window.menuBar()
    bar.setNativeMenuBar(False)
    menus = {}
    for name, keys in MENUS:
        title = tr("theme.settings") if name == "Settings" else ui(name)
        menu = menus[name] = bar.addMenu(title)
        for key in keys:
            if key == "|":
                menu.addSeparator()
            else:
                action = window.actions[key]
                action.setIconVisibleInMenu(False)
                menu.addAction(action)
    return menus


class ClassicToolbar(QFrame):
    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("classicToolbar")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.buttons = {}
        self.compact = []
        self.groups = []
        self.density = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 1)
        layout.setSpacing(3)
        for index, (title, first, second, lead, threshold) in enumerate(GROUPS):
            if index:
                divider = QFrame()
                divider.setFrameShape(QFrame.Shape.VLine)
                divider.setObjectName("classicDivider")
                layout.addWidget(divider)
            group = QWidget()
            column = QVBoxLayout(group)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(1)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)
            lead_button = None
            if lead:
                button = self._button(lead, actions[lead])
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                if lead == "analyze":
                    button.setObjectName("primary")
                button.ensurePolished()
                button.setMinimumWidth(button.sizeHint().width())
                row.addWidget(button)
                lead_button = button
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(1)
            rows = []
            for line, keys in enumerate((first, second)):
                row_buttons = []
                for position, key in enumerate(keys):
                    button = self._button(key, actions[key])
                    self.compact.append((button, threshold))
                    grid.addWidget(button, line, position, Qt.AlignmentFlag.AlignLeft)
                    row_buttons.append(button)
                rows.append(row_buttons)
            row.addLayout(grid)
            column.addLayout(row)
            label = QLabel(ui(title))
            label.setObjectName("classicGroup")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
            self.groups.append((label, lead_button, rows, row.spacing(), grid.spacing()))
            layout.addWidget(group)
        layout.addStretch()
        self._set_density(0)

    def _button(self, key, action):
        if key in SHORT:
            action.setIconText(tr(SHORT[key]))
        action.setIcon(theme.classic_icon(ICONS[key], "on_accent" if key == "analyze" else None))
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolTip(action.toolTip() or action.text())
        button.setAccessibleName(action.text())
        button.setIconSize(theme.icon_size(14))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if action.menu() is not None:
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.buttons[key] = button
        return button

    def _set_density(self, level):
        if level == self.density:
            return
        self.density = level
        for button, threshold in self.compact:
            text = level >= threshold
            style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text else Qt.ToolButtonStyle.ToolButtonIconOnly
            button.setToolButtonStyle(style)
            button.setFixedWidth(button.sizeHint().width())
        self.layout().invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for density in (3, 2, 1, 0):
            self._set_density(density)
            if self._content_width() <= event.size().width():
                break

    def _content_width(self):
        layout = self.layout()
        margins = layout.contentsMargins()
        width = margins.left() + margins.right()
        separators = len(self.groups) - 1
        width += separators + layout.spacing() * (len(self.groups) + separators)
        for label, lead, rows, lead_gap, column_gap in self.groups:
            columns = list(zip_longest(*rows))
            grid = sum(max(button.width() for button in column if button is not None) for column in columns)
            grid += column_gap * max(0, len(columns) - 1)
            if lead is not None:
                grid += lead.sizeHint().width() + lead_gap
            width += max(label.sizeHint().width(), grid)
        return width
