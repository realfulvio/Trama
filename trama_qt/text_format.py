"""The Text group of the Classica toolbar: font, size, colour, bold, italic, underline and alignment.

The commands act on the selected cells of a worksheet or of a result table and only change how the text is
drawn (``analisi.worksheet_text``): values, formulas, analyses, the clipboard and the exports keep every digit.
What the selection shows for each attribute is *inherited* (nothing set), *uniform* (one value everywhere) or
*mixed*; a toggle button shows it, and the tooltips say it in words. ``Restore text`` removes only the text
attributes. On a native graph the font and size commands open the existing Format graph window, which owns the
fonts of titles, axes and tick labels.

One change is one undoable worksheet step (``Project.set_table_text_style`` and ``set_result_text_style``); no
analysis is recalculated, so the cost follows the number of ranges selected, not the number of cells.
"""
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QInputDialog, QLabel,
                               QMenu, QVBoxLayout)

from analisi.data import decimal_comma
from analisi.i18n import active_language, tr
from analisi.worksheet_text import (ALIGN, ALIGNMENTS, BOLD, COLOR, FONT, INHERITED, ITALIC, MAX_SIZE, MIN_SIZE, MIXED,
                                    SIZE, SIZE_CHOICES, UNDERLINE, UNIFORM, TextStyles)

from .strings import qt


FIRST_ROW = ("text_font", "text_size", "text_bold", "text_italic", "text_underline")
SECOND_ROW = ("text_color", "text_align_left", "text_align_center", "text_align_right", "text_restore")
GRID_MENU = (*FIRST_ROW, "|", *SECOND_ROW)
MENU = (*GRID_MENU, "|", "text_graph")
ACTIONS = tuple(key for key in MENU if key != "|")
TOGGLES = {"text_bold": BOLD, "text_italic": ITALIC, "text_underline": UNDERLINE}
ALIGN_ACTIONS = {"text_align_left": "left", "text_align_center": "center", "text_align_right": "right"}
ICONS = {"text_font": "textfont", "text_size": "textsize", "text_bold": "bold", "text_italic": "italic",
         "text_underline": "underline", "text_color": "textcolor", "text_align_left": "alignleft",
         "text_align_center": "aligncenter", "text_align_right": "alignright", "text_restore": "textrestore",
         "text_graph": "format"}
_KEEP, _INHERIT = "keep", "inherit"
_PIXELS_PER_POINT = 96 / 72


def _read_size(text, unit="pt"):
    value = text.strip().lower()
    if value.endswith(("px", "pt")):
        value, unit = value[:-2], value[-2:]
    try:
        points = float(decimal_comma(value.strip()))
    except ValueError:
        points = float("nan")
    if unit == "px":
        points /= _PIXELS_PER_POINT
    if not MIN_SIZE <= points <= MAX_SIZE:
        raise ValueError(tr("text.error.size", low=MIN_SIZE, high=MAX_SIZE))
    return points, unit


def _selection_size(target, state):
    if state.kind == UNIFORM:
        return state.value
    return target.view.font().pointSizeF() / target.view.model().text_scale


class ToolbarTextControls:
    """Direct formatting controls, using points in the project and either unit in the toolbar."""

    def __init__(self, controller):
        self.controller = controller
        self.unit = "px"
        self.font = QComboBox()
        self.font.setObjectName("toolbarFont")
        self.font.setEditable(True)
        self.font.lineEdit().setReadOnly(True)
        self.font.setFixedWidth(144)
        self.font.setMinimumHeight(24)
        self.font.setAccessibleName(tr("worksheet.font_family"))
        self.font.addItem(tr("text.dialog.reset"), None)
        for family in QFontDatabase.families():
            self.font.addItem(family, family)
        self.font.activated.connect(self._choose_family)

        self.size = QComboBox()
        self.size.setObjectName("toolbarSize")
        self.size.setEditable(True)
        self.size.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.size.setFixedWidth(77)
        self.size.setMinimumHeight(24)
        self.size.setAccessibleName(qt("qt.toolbar_font_size"))
        self._fill_sizes()
        self.size.activated.connect(self._choose_size)
        self.size.lineEdit().returnPressed.connect(self._enter_size)
        self.size.lineEdit().editingFinished.connect(self.controller.update)

    def _format_size(self, points):
        size = points * _PIXELS_PER_POINT if self.unit == "px" else points
        number = f"{size:.2f}".rstrip("0").rstrip(".")
        if active_language() == "it":
            number = number.replace(".", ",")
        return f"{number} {self.unit}"

    def _fill_sizes(self):
        self.size.clear()
        self.size.addItem(tr("text.dialog.reset"), None)
        for points in SIZE_CHOICES:
            self.size.addItem(self._format_size(points), points)

    def _choose_family(self, index):
        self.controller.apply({FONT: self.font.itemData(index)})
        self.controller.update()

    def _choose_size(self, index):
        self.size.lineEdit().setModified(False)
        self.controller.apply({SIZE: self.size.itemData(index)})
        self.controller.update()

    def _enter_size(self):
        editor = self.size.lineEdit()
        if not editor.isModified():
            return
        editor.setModified(False)
        try:
            points, unit = _read_size(editor.text(), self.unit)
        except ValueError as error:
            self.controller.window.status(str(error))
            self.controller.update()
            return
        if unit != self.unit:
            self.unit = unit
            self._fill_sizes()
        self.controller.apply({SIZE: points})
        self.controller.update()

    def update(self, target, states):
        for field in (self.font, self.size):
            field.setEnabled(target is not None)
        self.font.setCurrentIndex(-1)
        self.size.setCurrentIndex(-1)
        if target is None:
            self.font.setEditText("")
            self.size.setEditText("")
            return
        font, size = states[FONT], states[SIZE]
        mixed = tr("text.state.mixed")
        family = font.value if font.kind == UNIFORM else target.view.font().family()
        self.font.setEditText(mixed if font.kind == MIXED else family)
        self.size.setEditText(mixed if size.kind == MIXED else self._format_size(_selection_size(target, size)))


@dataclass(frozen=True)
class TextTarget:
    """The cells a text command reaches: the owning table, the result sheet (if any) and the ranges."""
    view: object
    title: str
    slot: int | None
    name: str | None
    box: tuple
    shape: tuple
    keys: tuple
    top: int
    stop: int
    styles: TextStyles

    @property
    def result(self):
        return self.name is not None

    @property
    def cells(self):
        return (self.stop - self.top) * len(self.keys)


class TextFontDialog(QDialog):
    """Font family and size of the selection; each can be left as it is or sent back to the table default."""

    def __init__(self, parent, states):
        super().__init__(parent)
        self.setWindowTitle(tr("text.dialog.title"))
        self.changes = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.family = QComboBox()
        self.family.addItem(tr("text.dialog.keep"), _KEEP)
        self.family.addItem(tr("text.dialog.reset"), _INHERIT)
        families = QFontDatabase.families()
        for name in families:
            self.family.addItem(name, name)
        state = states[FONT]
        if state.kind == UNIFORM:
            if state.value not in families:
                self.family.addItem(state.value, state.value)
            self.family.setCurrentIndex(self.family.findData(state.value))
        elif state.kind == INHERITED:
            self.family.setCurrentIndex(1)
        form.addRow(tr("worksheet.font_family"), self.family)
        self.size = QComboBox()
        self.size.setEditable(True)
        self.size.addItem(tr("text.dialog.size_keep"), _KEEP)
        self.size.addItem(tr("text.dialog.reset"), _INHERIT)
        for size in SIZE_CHOICES:
            self.size.addItem(f"{size:g}", float(size))
        state = states[SIZE]
        if state.kind == UNIFORM:
            self.size.setCurrentText(f"{state.value:g}")
        elif state.kind == INHERITED:
            self.size.setCurrentIndex(1)
        form.addRow(tr("worksheet.font_size"), self.size)
        note = QLabel(tr("text.dialog.note"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _size(self):
        text = self.size.currentText().strip()
        index = self.size.findText(text)
        if index >= 0 and self.size.itemData(index) in (_KEEP, _INHERIT):
            return self.size.itemData(index)
        return _read_size(text)[0]

    def accept(self):
        try:
            size = self._size()
        except ValueError as error:
            self.problem.setText(str(error))
            self.problem.show()
            self.size.setFocus()
            return
        family = self.family.currentData()
        if family != _KEEP:
            self.changes[FONT] = None if family == _INHERIT else family
        if size != _KEEP:
            self.changes[SIZE] = None if size == _INHERIT else size
        super().accept()


class TextFormat:
    """The window side of the Text group: actions, state of the selection, one undoable step per change."""

    def __init__(self, window):
        self.window = window
        self.size_menu = None
        self.toolbar_controls = None
        self.last = None  # (enabled, states) of the last update, for the tests and the screenshots

    # -- actions ---------------------------------------------------------------------------------
    def create_actions(self):
        w = self.window
        w._action("text_font", tr("command.text_font"), self.choose_font)
        w._action("text_size", tr("command.text_size"), self.choose_size)
        w._action("text_grow", qt("qt.toolbar_font_grow"), lambda: self.step_size(1))
        w._action("text_shrink", qt("qt.toolbar_font_shrink"), lambda: self.step_size(-1))
        for key, attribute in TOGGLES.items():
            w._action(key, tr(f"command.{key}"), lambda attribute=attribute: self.toggle(attribute)).setCheckable(True)
        w._action("text_color", tr("command.text_color"), self.choose_color)
        for key, value in ALIGN_ACTIONS.items():
            w._action(key, tr(f"command.{key}"), lambda value=value: self.toggle_alignment(value)).setCheckable(True)
        w._action("text_restore", tr("command.text_restore"), self.restore)
        w._action("text_graph", tr("command.text_graph"), self.graph_text, tip=tr("text.tip.graph"))
        self.size_menu = QMenu(w)
        self.size_menu.aboutToShow.connect(self._fill_sizes)
        w.actions["text_size"].setMenu(self.size_menu)

    def watch(self, view):
        """Keep the Text state current while the selection of ``view`` changes."""
        view.selectionModel().selectionChanged.connect(lambda *_: self.update())
        view.selectionModel().currentChanged.connect(lambda *_: self.update())

    # -- what is selected --------------------------------------------------------------------------
    def view(self):
        w = self.window
        if w.gallery is not None or not w.selected:
            return None
        if w.selected[0] == "data":
            return w.sheet
        if w.selected[0] == "result" and w.result_tabs is not None:
            return w.result_tabs.currentWidget()
        return None

    def target(self):
        """The cells a command would change, or None when no table, no selection or nothing to style."""
        from .sheet import selection_box  # sheet.py imports this module for its menus

        w = self.window
        view = self.view()
        if view is None or (box := selection_box(view)) is None:
            return None
        top, left, bottom, right = box
        model = view.model()
        if w.selected[0] == "data":
            dataset = w.project.tables[w.selected[1]]
            keys = tuple(model.frame.columns[left:right + 1])
            stop = min(bottom + 1, len(model.frame))
            title, slot, name, styles = w.selected[1], None, None, dataset.text_styles
            shape = (len(model.frame), len(model.frame.columns))
        else:
            run = w.project.runs[w.selected[1]]
            dataset = w.project.tables[run.title]
            name = tuple(run.result.tables)[w.result_tabs.currentIndex()]
            keys = tuple(range(left, min(right + 1, model.columnCount())))
            stop = min(bottom + 1, model.rowCount())
            title, slot = run.title, run.slot
            styles = dataset.result_text_styles.get(slot, {}).get(name, TextStyles())
            shape = (model.rowCount(), model.columnCount())
        if not keys or stop <= top:
            return None
        return TextTarget(view, title, slot, name, box, shape, keys, top, stop, styles)

    def states(self, target=None):
        """``{attribute: TextState}`` of the selection, or None when no command applies."""
        target = target or self.target()
        return target.styles.states(target.keys, target.top, target.stop) if target is not None else None

    def graph_run(self):
        w = self.window
        if not w.selected or w.selected[0] != "graph" or w.gallery is not None:
            return None
        run = w.project.runs[w.selected[1]]
        return run if w.project.graph_format_problem(run) is None else None

    # -- state of the actions -----------------------------------------------------------------------
    def update(self):
        w = self.window
        idle = w.job is None
        locked = bool(w.selected and w.gallery is None and w.project.sheet_locked(w.selected))
        target = self.target() if idle and not locked else None
        states = self.states(target)
        graph = idle and self.graph_run() is not None
        self.last = (target is not None, states)
        for key in ACTIONS:
            w.actions[key].setEnabled(target is not None)
        w.actions["linked_table_selection"].setEnabled(target is not None)
        w.actions["text_graph"].setEnabled(graph)
        for key in ("text_font", "text_size"):
            w.actions[key].setEnabled(target is not None or graph)
        for key in ("text_grow", "text_shrink"):
            w.actions[key].setEnabled(target is not None)
        if states is None:
            states = {attribute: type("S", (), {"kind": INHERITED, "value": None})() for attribute in
                      (FONT, SIZE, COLOR, BOLD, ITALIC, UNDERLINE, ALIGN)}
        for key, attribute in TOGGLES.items():
            state = states[attribute]
            w.actions[key].setChecked(state.kind == UNIFORM and state.value is True)
            self._mark(key, state.kind, f"{w.actions[key].text()} · {self._words(state, attribute)}")
        align = states[ALIGN]
        for key, value in ALIGN_ACTIONS.items():
            w.actions[key].setChecked(align.kind == UNIFORM and align.value == value)
            self._mark(key, align.kind, f"{w.actions[key].text()} · {self._words(align, ALIGN)}")
        self._mark("text_font", states[FONT].kind, self._tip("text_font", FONT, states, graph and target is None))
        self._mark("text_size", states[SIZE].kind, self._tip("text_size", SIZE, states, graph and target is None))
        self._mark("text_color", states[COLOR].kind, self._tip("text_color", COLOR, states, False))
        if self.toolbar_controls is not None:
            self.toolbar_controls.font.setToolTip(w.actions["text_font"].toolTip())
            state = self._words(states[SIZE], SIZE)
            self.toolbar_controls.size.setToolTip(f"{qt('qt.toolbar_size_tip')} · {state}")
            self.toolbar_controls.update(target, states)

    def _words(self, state, attribute):
        if state.kind == MIXED:
            return tr("text.state.mixed")
        if state.kind == INHERITED:
            return tr("text.state.inherited") if attribute in (FONT, SIZE, COLOR, ALIGN) else tr("text.state.off")
        if attribute == SIZE:
            return f"{state.value:g} pt"
        if attribute == ALIGN:
            return tr(f"text.align.{state.value}")
        if attribute in (BOLD, ITALIC, UNDERLINE):
            return tr("text.state.on" if state.value else "text.state.off")
        return str(state.value)

    def _tip(self, key, attribute, states, graph):
        action = self.window.actions[key]
        if graph:
            return f"{action.text()} · {tr('text.tip.graph')}"
        name = {FONT: "font", SIZE: "size", COLOR: "color"}[attribute]
        return f"{action.text()} · {tr(f'text.tip.{name}', state=self._words(states[attribute], attribute))}"

    def _mark(self, key, kind, tip):
        """Show inherited / uniform / mixed on the toolbar button (a property the style sheet reads) and say it."""
        action = self.window.actions[key]
        action.setProperty("textState", kind)
        action.setToolTip(tip)
        action.setStatusTip(tip)
        button = self.window.toolbar.buttons.get(key) if getattr(self.window, "toolbar", None) else None
        if button is not None:
            if button.property("textState") != kind:
                button.setProperty("textState", kind)
                button.style().unpolish(button)
                button.style().polish(button)
            button.setToolTip(tip)
            button.setAccessibleDescription(tip)

    # -- commands -------------------------------------------------------------------------------------
    def apply(self, changes, *, restore=False):
        """One undoable step: ``changes`` (attribute → value, ``None`` inherits again) or ``Restore text``."""
        w = self.window
        if w.busy() or w.gallery is not None:
            return False
        target = self.target()
        if target is None:
            return False
        try:
            if target.result:
                changed = w.project.set_result_text_style(target.title, target.slot, target.name, target.box,
                                                          target.shape, None if restore else changes)
            else:
                changed = w.project.set_table_text_style(target.title, target.box, None if restore else changes)
        except (ValueError, TypeError) as error:
            w.error(error)
            return False
        if not changed:
            w.status(tr("text.status.unchanged"))
            return False
        self.redraw()
        w.update_title()
        w.update_actions()
        w.status(tr("text.status.restored" if restore else "text.status.applied", cells=target.cells))
        return True

    def redraw(self):
        """Read the text styles of the table on screen again (after a change, an undo or a redo)."""
        w = self.window
        if not w.selected:
            return
        if w.selected[0] == "data" and w.sheet is not None:
            w.sheet.refresh_text(w.project.tables[w.selected[1]].text_styles)
        elif w.selected[0] == "result":
            w._refresh_result_backgrounds(w.project.runs[w.selected[1]])

    def toggle(self, attribute):
        states = self.states()
        if states is None:
            return
        state = states[attribute]
        self.apply({attribute: None if state.kind == UNIFORM and state.value is True else True})

    def toggle_alignment(self, value):
        states = self.states()
        if states is None:
            return
        state = states[ALIGN]
        self.apply({ALIGN: None if state.kind == UNIFORM and state.value == value else value})

    def choose_color(self):
        states = self.states()
        if states is None:
            return
        state = states[COLOR]
        start = QColor(state.value) if state.kind == UNIFORM else self.window.palette().text().color()
        chosen = QColorDialog.getColor(start, self.window, tr("command.text_color").rstrip("…"))
        if chosen.isValid():
            self.apply({COLOR: chosen.name()})

    def choose_font(self):
        if self.graph_run() is not None and self.target() is None:
            self.graph_text()
            return
        states = self.states()
        if states is None:
            return
        dialog = TextFontDialog(self.window, states)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.changes:
                self.apply(dialog.changes)
        finally:
            dialog.deleteLater()

    def choose_size(self):
        if self.graph_run() is not None and self.target() is None:
            self.graph_text()
            return
        states = self.states()
        if states is None:
            return
        state = states[SIZE]
        start = state.value if state.kind == UNIFORM else 10.0
        size, accepted = QInputDialog.getDouble(self.window, tr("command.text_size"), tr("worksheet.font_size"),
                                                float(start), MIN_SIZE, MAX_SIZE, 1)
        if accepted:
            self.apply({SIZE: size})

    def step_size(self, step):
        target = self.target()
        if target is not None:
            size = _selection_size(target, self.states(target)[SIZE])
            self.apply({SIZE: min(MAX_SIZE, max(MIN_SIZE, size + step))})

    def _fill_sizes(self):
        menu = self.size_menu
        menu.clear()
        if self.target() is None:
            if self.graph_run() is not None:
                menu.addAction(self.window.actions["text_graph"])
            return
        state = self.states()[SIZE]
        for size in SIZE_CHOICES:
            action = menu.addAction(f"{size:g}")
            action.setCheckable(True)
            action.setChecked(state.kind == UNIFORM and state.value == size)
            action.triggered.connect(lambda _checked=False, size=size: self.apply({SIZE: float(size)}))
        menu.addSeparator()
        menu.addAction(tr("command.text_size_other"), self.choose_size)
        menu.addAction(tr("text.dialog.reset_size"), lambda: self.apply({SIZE: None}))

    def restore(self):
        self.apply(None, restore=True)

    def graph_text(self):
        """Titles, axis labels and tick labels belong to Format graph: open it instead of a second editor."""
        if self.graph_run() is not None:
            self.window.format_graph()
