"""The Classica menu and compact two-row toolbar, backed by the window's Qt actions."""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from analisi.i18n import tr, ui

from . import theme
from .strings import qt
from .text_format import ICONS as TEXT_ICONS, MENU as TEXT_MENU, ToolbarTextControls


SELECTION_COMMANDS = {
    "select_sheet_cells": "Ctrl+A",
    "select_data_column": "Ctrl+Space",
    "select_data_row": "Shift+Space",
}


MENUS = (
    ("File", ("new_project", "new_table", "open", "import", "import_excel", "refresh_source", "source_link",
              "recover", "|",
              "save", "save_as", "save_template", "new_from_template", "|", "export", "export_options",
              "export_pdf", "export_batch", "export_report", "export_excel", "send_word", "send_powerpoint", "|",
              "print", "print_preview", "page_setup", "|", "close_project", "exit")),
    ("Edit", ("undo", "redo", "|", "cut", "copy", "paste", "paste_special", "paste_transpose", "paste_table",
              "|", *SELECTION_COMMANDS, "|", "clear_cells", "|", "exclude", "move_rows_up", "move_rows_down", "move_rows_first", "move_rows_last",
              "sort_rows", "sort_by_x", "sort_by_row_title", "reverse_rows", "reset_row_height",
              "delete_rows", "delete_columns", "|",
              "sheet_duplicate", "sheet_rename", "sheet_delete", "sheet_move_up", "sheet_move_down", "sheet_freeze")),
    ("View", ("navigator", "find_sheet", "combined_navigator", "gallery", "previous_sheet", "next_sheet", "previous_project", "next_project", "|",
              "worksheet_preview", "analysis_graph", "analysis_tables", "layout_go_origin", "inspector", "|",
              "fit_graph", "fit_layout_page", "layout_rulers", "layout_page_grid", "|",
              "sheet_zoom_in", "sheet_zoom_out", "sheet_zoom_reset", "|",
              "theme_system", "theme_light", "theme_dark")),
    ("Insert", ("new_table", "new_info", "sheet_notes", "insert_row", "insert_column",
                "create_numeric_series", "formula", "|",
                "new_graph", "new_layout", "place_layout_graph", "pairwise", "compact_letters", "annotations", "shapes", "|",
                "linked_table", "linked_table_selection", "linked_table_move")),
    ("Analyze", ("analyze", "change", "recalculate", "analyze_result", "source_analysis", "change_input",
                 "repeat_analysis", "use_result", "|", "descriptive", "ttest", "anova", "correlation", "correlation_matrix",
                 "linear", "nonlinear", "survival", "contingency", "load_example")),
    ("Change", ("format_data_table", "number_format", "|", "change", "change_graph_type", "format_graph",
                "format_axis_x", "format_axis_y", "format_axis_right", "format_legend", "reverse_legend",
                "graph_style_presets", "batch_figure_styles",
                "plot_margins", "edit_layout", "replace_layout_graph", "layout_clear_background",
                "variable_properties", "category_order", "cell_background",
                "clear_cell_background", "edit_column_titles", "edit_subcolumn_titles", "|",
                *TEXT_MENU, "|",
                "info_properties")),
    ("Arrange", ("layout_align_edges", "layout_distribute", "layout_align_x", "layout_align_y", "layout_center_page", "layout_equalize", "|",
                 "layout_front", "layout_back", "layout_group", "layout_ungroup", "layout_lock", "layout_duplicate", "layout_position", "|",
                 "arrange_shapes", "linked_table_move", "new_layout", "edit_layout")),
    ("Family", ("family_data", "family_info", "family_results", "family_graphs", "family_gallery", "|",
                "duplicate_family", "save_family")),
    ("Tools", ("power", "paired_power", "simulate", "monte_carlo", "transpose_xy", "plot_function", "|", "search")),
    ("Settings", ("language", "table_font", "processes", "recovery_settings")),
    ("Help", ("help_shortcuts", "search", "|", "about")),
)

# In reading order. Compact groups show icons before moving into More.
GROUPS = (
    ("File", ("new_table", "open"), ("save", "save_as")),
    ("Sheet", ("insert_row", "insert_column", "new_info"), ("exclude",)),
    ("Undo", ("undo",), ("redo",)),
    ("Clipboard", ("cut", "copy", "paste"), ("paste_special", "paste_table")),
    ("Analysis", ("analyze", "linear", "nonlinear"), ("descriptive", "correlation_matrix", "new_graph", "new_layout", "pairwise")),
    ("Change", ("format_data_table", "change"), ("format_graph",)),
    ("Data", ("formula",), ("variable_properties",)),
    ("Import", ("import",), ("import_excel",)),
    ("Draw", ("shapes",), ("annotations",)),
    ("Write", ("sheet_notes",), ("linked_table", "linked_table_move")),
    ("Text", ("text_size", "text_font", "text_color"),
     ("text_grow", "text_shrink", "text_bold", "text_italic", "text_underline",
      "text_align_left", "text_align_center", "text_align_right", "text_restore")),
    ("Export", ("export",), ("export_options",)),
    ("Print", ("print",), ("print_preview",)),
    ("Send", ("send_word",), ("send_powerpoint",)),
    ("Help", ("about",), ("search",)),
)
OVERFLOW_ORDER = ("Help", "Send", "Print", "Write", "Draw", "Export", "Import", "Data", "Change",
                  "Sheet", "Text", "Undo", "Clipboard", "File", "Analysis")
GROUP_LABELS = {"Data": "qt.toolbar_data", "Draw": "qt.toolbar_draw", "Write": "qt.toolbar_write",
                "Send": "qt.toolbar_send", "Help": "qt.toolbar_help", "Print": "qt.print_title"}

SHORT = {
    "change": "qt.toolbar_parameters", "format_graph": "qt.toolbar_format",
    "formula": "qt.toolbar_formula", "variable_properties": "qt.toolbar_properties",
    "import": "qt.toolbar_import_data", "import_excel": "qt.toolbar_excel",
    "shapes": "qt.toolbar_shapes", "annotations": "qt.toolbar_annotate",
    "sheet_notes": "qt.toolbar_note", "linked_table": "qt.toolbar_linked_table",
    "linked_table_move": "qt.toolbar_linked_table_move",
    "export": "qt.toolbar_export_figure", "export_options": "qt.toolbar_export_options",
    "print": "qt.print_title", "print_preview": "qt.toolbar_preview",
    "send_word": "qt.toolbar_word", "send_powerpoint": "qt.toolbar_powerpoint",
    "about": "qt.toolbar_about", "search": "qt.toolbar_search",
}

ICONS = {
    "new_table": "new", "open": "open", "save": "save", "save_as": "saveas",
    "insert_row": "addrow", "insert_column": "addcol", "new_info": "info",
    "exclude": "exclude", "formula": "formula", "undo": "undo", "redo": "redo",
    "cut": "cut", "copy": "copy", "paste_special": "pastespecial", "paste_table": "pastetable", "paste": "paste",
    "linear": "linreg", "nonlinear": "curve", "descriptive": "bars", "correlation_matrix": "heatmap",
    "analyze": "analyze", "change": "params", "format_graph": "format", "import": "import",
    "export": "export", "export_options": "exportopts", "new_layout": "layout",
    "pairwise": "pairwise", "new_graph": "graph", "variable_properties": "data", "shapes": "shapes",
    "annotations": "annotation", "sheet_notes": "annotation", "linked_table": "link", "linked_table_move": "movetable", "print_preview": "result",
    "about": "info", "search": "search",
    **TEXT_ICONS,
}
QT_ICONS = {"print": "printer", "send_word": "file-up", "send_powerpoint": "move-up-right"}
STEPS = {"text_grow": "A+", "text_shrink": "A−"}


def build_menus(window):
    bar = window.menuBar()
    bar.setNativeMenuBar(False)
    menus = {}
    for name, keys in MENUS:
        title = tr("theme.settings") if name == "Settings" else qt("qt.toolbar_help") if name == "Help" else ui(name)
        menu = menus[name] = bar.addMenu(title)
        selection_menu = None
        for key in keys:
            if key in SELECTION_COMMANDS:
                if selection_menu is None:
                    selection_menu = menu.addMenu(qt("qt.select_cells"))
                    window.cell_selection_menu = selection_menu
                selection_menu.addAction(window.actions[key])
            elif key == "|":
                menu.addSeparator()
            else:
                action = window.actions[key]
                action.setIconVisibleInMenu(False)
                menu.addAction(action)
    return menus


@dataclass
class ToolbarGroup:
    name: str
    widget: QWidget
    divider: QFrame | None
    menu: QMenu
    grid: QGridLayout


class ClassicToolbar(QFrame):
    def __init__(self, actions, text_format, parent=None):
        super().__init__(parent)
        self.setObjectName("classicToolbar")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.actions = actions
        self.buttons = {}
        self.groups = []
        self.text_controls = text_format.toolbar_controls = ToolbarTextControls(text_format)
        self.fields = {"text_font": self.text_controls.font, "text_size": self.text_controls.size}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(2)
        for title, first, second in GROUPS:
            self._add_group(title, first, second)
        self.overflow = QToolButton()
        self.overflow.setText(tr("theme.more"))
        self.overflow.setToolTip(qt("qt.toolbar_more_tip"))
        self.overflow.setAccessibleName(tr("theme.more"))
        self.overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.overflow.setMenu(QMenu(self.overflow))
        layout.addWidget(self.overflow, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.overflow.hide()
        layout.addStretch()

    def _add_group(self, title, first, second):
        divider = None
        if self.groups:
            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.VLine)
            divider.setObjectName("classicDivider")
            self.layout().addWidget(divider)
        group = QWidget()
        group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(group)
        column.setContentsMargins(3, 0, 3, 0)
        column.setSpacing(1)
        label = QLabel(qt(GROUP_LABELS[title]) if title in GROUP_LABELS else ui(title))
        label.setObjectName("classicGroup")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(1)
        column.addLayout(grid)
        if title == "Text":
            top = QHBoxLayout()
            top.setSpacing(2)
            for key in first:
                top.addWidget(self.fields[key] if key in self.fields else self._button(key))
            grid.addLayout(top, 0, 0, 1, len(second))
            for position, key in enumerate(second):
                grid.addWidget(self._button(key), 1, position, Qt.AlignmentFlag.AlignCenter)
        else:
            for line, keys in enumerate((first, second)):
                for position, key in enumerate(keys):
                    alignment = Qt.AlignmentFlag.AlignLeft if key in SHORT or key == "analyze" else Qt.AlignmentFlag.AlignCenter
                    grid.addWidget(self._button(key), line, position, alignment)
        menu = QMenu(label.text(), self)
        for key in first + second:
            menu.addAction(self.actions[key])
        self.groups.append(ToolbarGroup(title, group, divider, menu, grid))
        self.layout().addWidget(group)

    @staticmethod
    def _sync_tooltip(button, action):
        name = action.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
        tip = action.toolTip() or name
        shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        if shortcut and shortcut not in tip:
            tip = f"{tip} ({shortcut})"
        button.setToolTip(tip)
        button.setAccessibleName(name)
        button.setAccessibleDescription(tip)

    def _button(self, key):
        action = self.actions[key]
        if key in STEPS:
            action.setIconText(STEPS[key])
        elif key in SHORT:
            action.setIconText(qt(SHORT[key]))
        if key in ICONS:
            action.setIcon(theme.classic_icon(ICONS[key], "on_accent" if key == "analyze" else None))
        elif key in QT_ICONS:
            action.setIcon(theme.icon(QT_ICONS[key]))
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setIconSize(theme.icon_size(14))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(24)
        if key == "analyze":
            button.setObjectName("primary")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if key in STEPS:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        if action.menu() is not None:
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._sync_tooltip(button, action)
        action.changed.connect(lambda: self._sync_tooltip(button, action))
        self.buttons[key] = button
        return button

    def _measure_groups(self, captions):
        style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon if captions
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        for key in SHORT:
            self.buttons[key].setToolButtonStyle(style)
        widths = {}
        for group in self.groups:
            group.grid.invalidate()
            layout = group.widget.layout()
            layout.invalidate()
            widths[group.name] = layout.sizeHint().width()
        return widths

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _fit(self):
        names = {group.name for group in self.groups}
        widths = self._measure_groups(captions=True)
        if self._content_width(names, widths) > self.width():
            widths = self._measure_groups(captions=False)
        hidden = []
        for name in OVERFLOW_ORDER:
            if self._content_width(names, widths) <= self.width():
                break
            names.remove(name)
            hidden.append(name)
        # Bring groups back in priority order and stop at the first that does not fit, so a smaller
        # low-priority group (Send) never takes the place of a more important one (Export).
        for name in reversed(hidden):
            if self._content_width(names | {name}, widths) > self.width():
                break
            names.add(name)

        menu = self.overflow.menu()
        menu.clear()
        first = True
        for group in self.groups:
            visible = group.name in names
            group.widget.setFixedWidth(widths[group.name])
            group.widget.setVisible(visible)
            if group.divider is not None:
                group.divider.setVisible(visible and not first)
            if visible:
                first = False
            else:
                menu.addMenu(group.menu)
        self.overflow.setVisible(not menu.isEmpty())
        self.layout().invalidate()
        self.layout().activate()

    def _content_width(self, names, widths):
        layout = self.layout()
        margins = layout.contentsMargins()
        groups = [group for group in self.groups if group.name in names]
        width = margins.left() + margins.right()
        for index, group in enumerate(groups):
            width += widths[group.name] + layout.spacing()
            if index:
                width += group.divider.sizeHint().width() + layout.spacing()
        if len(groups) < len(self.groups):
            width += self.overflow.sizeHint().width() + layout.spacing()
        return width
