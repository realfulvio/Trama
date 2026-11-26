"""Draw, select, move and resize native shapes with the pointer on the Qt graph canvas.

``QtShapeCanvas`` adapts the toolkit-free controller of ``analisi.shape_interaction`` (the same transactions
as the classic window) to a ``FigureCanvasQTAgg``: editing keys while a tool is on, focus-out cancel.
``GraphDrawing`` connects it to the window: the tool actions, the per-graph Undo/Redo, the clipboard, the
context menu and the numeric editor of ``trama_qt.shapes``.

Every confirmed change goes through ``MainWindow.commit_style`` (one Undo step); previews only touch the
figure's drawing artists, and the selection handles are never part of an export or a saved style.
"""
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QActionGroup, QColor, QCursor
from PySide6.QtWidgets import QApplication, QColorDialog, QLabel, QMenu

from analisi.axis_breaks import segment_axes
from analisi.graph_shapes import ARROW_HEADS, ARROW_STYLES, HATCHES, LINE_STYLES, SHAPES, on_axis_domain
from analisi.i18n import tr
from analisi.presentation import apply_style
from analisi.legacy_restore import SAVED_BINARY_GRAPH, SAVED_EDITABLE_GRAPH, SAVED_XY
from analisi.qq_panels import panel_axes
from analisi.shape_clipboard import dump_object, paste_shape
from analisi.shape_context import DEFAULTS, ENDING_SIZES, WIDTHS, edit_records
from analisi.shape_interaction import ShapeController, render_shapes
from analisi.shape_objects import is_locked, selected_objects

from .strings import qt

TOOLS = ("select", "line", "arrow", "rectangle", "ellipse")
TOOL_ICONS = {"select": "mouse-pointer-2", "line": "slash", "arrow": "move-up-right", "rectangle": "square",
              "ellipse": "circle"}
CLIPBOARD = ("cut", "copy", "paste")
IMPORTED_GRAPHS = {SAVED_XY, SAVED_BINARY_GRAPH, SAVED_EDITABLE_GRAPH}
_ARROWS = {Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down"}
_LETTERS = {Qt.Key.Key_C: "ctrl+c", Qt.Key.Key_X: "ctrl+x", Qt.Key.Key_V: "ctrl+v"}


def shapes_of(run):
    return deepcopy((run.style or {}).get(SHAPES, []))


def canvas_problem(figure):
    """Why pointer drawing is outside its scope on ``figure`` (single-panel 2D native plot), or None."""
    if figure is None or not figure.axes:
        return tr("shape.native")
    if segment_axes(figure):
        return tr("axis_breaks.canvas_note")
    main = figure.axes[0]
    if main.name != "rectilinear" or panel_axes(figure):
        return qt("qt.draw_single_panel")
    position = main.get_position().bounds
    for axes in figure.axes[1:]:
        if not axes.get_visible() or axes.get_label() == "<colorbar>" or getattr(axes, "_colorbar", None):
            continue
        if not np.allclose(axes.get_position().bounds, position):  # A twin axis shares the plot rectangle.
            return qt("qt.draw_single_panel")
    return None


class _Keys(QObject):
    """Editing keys of the canvas while a tool is on; they never reach the window shortcuts."""

    def __init__(self, controller):
        super().__init__(controller.canvas)
        self.controller = controller

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            name = self.controller.key_name(event)
            if name is None:
                return False
            if kind == QEvent.Type.ShortcutOverride:
                event.accept()  # The canvas takes the key: no window action fires for it.
                return True
            self.controller.key(name)
            return True
        if kind == QEvent.Type.FocusOut and self.controller.gesture is not None:
            self.controller.cancel()
        return False


class QtShapeCanvas(ShapeController):
    """The shared controller on a ``FigureCanvasQTAgg``. Undo/Redo stays with the window actions."""

    def __init__(self, *args, **kwargs):
        self._filter = None
        super().__init__(*args, **kwargs)

    def _bind_keys(self):
        if self._filter is not None:
            return
        self._filter = _Keys(self)
        self.canvas.installEventFilter(self._filter)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _unbind_keys(self):
        if self._filter is not None:
            try:
                self.canvas.removeEventFilter(self._filter)
            except RuntimeError:
                pass  # The page that owned the canvas is already deleted.
            self._filter = None

    def key_name(self, event):
        """The controller's name for a Qt key event, or None when the key is not a drawing key."""
        key, modifiers = event.key(), event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return None
        if key == Qt.Key.Key_Escape and not (ctrl or shift):
            return "escape"
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not (ctrl or shift):
            return "delete"
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (ctrl or shift):
            return "enter"
        if key in _ARROWS:
            return "+".join([*(["ctrl"] if ctrl else []), *(["shift"] if shift else []), _ARROWS[key]])
        if ctrl and not shift and key in _LETTERS and self.clipboard is not None:
            return _LETTERS[key]
        return None

    def key(self, key):
        # A second Esc, with nothing being dragged, leaves the drawing tools.
        if key == "escape" and self.gesture is None and self.mode == "select":
            self.set_mode(None)
            return True
        return super().key(key)


class GraphDrawing:
    """The window side of pointer drawing: actions, commit, history, clipboard, menu and editor."""

    def __init__(self, window):
        self.window = window
        self.controller = None
        self.run = self.canvas = self.toolbar = None
        self.reason = None
        self.group = None
        self.menu = None

    # -- actions ---------------------------------------------------------------------------------
    def create_actions(self):
        w = self.window
        self.group = QActionGroup(w)
        self.group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        for mode in TOOLS:
            action = w._action(f"draw_{mode}", tr(f"shape.canvas.{mode}"), lambda mode=mode: self.toggle(mode),
                               icon=TOOL_ICONS[mode])
            action.setCheckable(True)
            self.group.addAction(action)
        for name in CLIPBOARD:
            w._action(f"shape_{name}", tr(f"shape.clipboard.{name}"), lambda name=name: self.clipboard_action(name),
                      icon={"cut": "scissors", "copy": "copy", "paste": "clipboard-paste"}[name])
        w._action("draw_stop", tr("shape.canvas.stop"), lambda: self.start(None), icon="x")
        self.menu = QMenu(w)
        for mode in TOOLS:
            self.menu.addAction(w.actions[f"draw_{mode}"])
        self.menu.addSeparator()
        for name in CLIPBOARD:
            self.menu.addAction(w.actions[f"shape_{name}"])
        self.menu.addSeparator()
        self.menu.addAction(w.actions["arrange_shapes"])
        self.menu.addAction(w.actions["shapes"])
        self.menu.addAction(w.actions["draw_stop"])
        draw = w._action("draw", qt("qt.draw"), lambda: self.toggle("select", force=True), icon="pencil",
                         tip=qt("qt.draw_tip"))
        draw.setMenu(self.menu)

    def toggle(self, mode, *, force=False):
        action = self.window.actions[f"draw_{mode}"]
        if force:
            action.setChecked(True)
        self.start(mode if action.isChecked() else None)

    # -- scope ---------------------------------------------------------------------------------------
    def selected_run(self):
        w = self.window
        if w.gallery is None and w.selected and w.selected[0] == "graph" and 0 <= w.selected[1] < len(w.project.runs):
            return w.project.runs[w.selected[1]]
        return None

    def problem(self):
        """Why the drawing tools cannot be used now, or None."""
        w = self.window
        run = self.selected_run()
        if run is None or run.method in IMPORTED_GRAPHS:
            return tr("shape.native")
        if w.job is not None:
            return qt("qt.wait")
        problem = w.project.graph_format_problem(run)
        if problem:
            return problem
        problem = canvas_problem(run.result.figure)
        if problem:
            return problem
        if self.controller is None or self.run is not run:
            return tr("shape.native")
        return None

    def allowed(self):
        w, tools = self.window, self.toolbar
        return (w.gallery is None and w.job is None and self.controller is not None
                and not (tools is not None and tools.mode)
                and not (w.inspector is not None and w.inspector.has_draft))

    # -- page life -----------------------------------------------------------------------------------
    def attach(self, page, canvas, tools, run):
        """Bind the tools to the graph canvas of a new page (the previous page was detached)."""
        self.detach()
        self.run, self.canvas, self.toolbar = run, canvas, tools
        figure = run.result.figure
        self.reason = None if run.method in IMPORTED_GRAPHS else canvas_problem(figure)
        if run.method not in IMPORTED_GRAPHS and self.reason is None:
            self.controller = QtShapeCanvas(
                canvas, figure.axes[0], records=lambda: shapes_of(run), commit=lambda records: self.commit(run, records),
                status=self.window.status, allowed=self.allowed, edit=self.edit, context=self.context,
                clipboard=self.clipboard_action, mode_changed=lambda mode: self.sync())
        if self.reason is not None:
            note = QLabel(qt("qt.draw_unavailable", reason=self.reason))
            note.setObjectName("muted")
            note.setWordWrap(True)
            index = page.layout_.indexOf(tools) if tools is not None else -1
            page.layout_.insertWidget(index if index >= 0 else page.layout_.count(), note, 0)
        self.sync()

    def detach(self):
        controller, self.controller = self.controller, None
        if controller is not None:
            controller.close()
        self.run = self.canvas = self.toolbar = None
        self.reason = None
        self.sync()

    def cancel(self):
        """Close a pointer preview (page switch, export, save, recalculation, closing)."""
        if self.controller is not None:
            self.controller.cancel()

    def sync(self):
        """Checked tool, enabled actions and the reason in each tool tip."""
        w = self.window
        if self.group is None:
            return
        problem = self.problem()
        mode = self.controller.mode if self.controller is not None else None
        for name in TOOLS:
            action = w.actions[f"draw_{name}"]
            action.setEnabled(problem is None)
            action.setChecked(mode == name)
            text = tr(f"shape.canvas.{name}")
            action.setToolTip(text if problem is None else f"{text}\n{problem}")
        for name in CLIPBOARD:
            w.actions[f"shape_{name}"].setEnabled(problem is None)
        w.actions["draw_stop"].setEnabled(mode is not None)
        w.actions["draw"].setEnabled(problem is None)
        w.actions["draw"].setToolTip(qt("qt.draw_tip") if problem is None else f"{qt('qt.draw_tip')}\n{problem}")

    # -- modes ---------------------------------------------------------------------------------------
    def start(self, mode):
        w = self.window
        if mode is None:
            if self.controller is not None:
                self.controller.set_mode(None)
            self.sync()
            return True
        problem = self.problem()
        if problem:
            w.error(problem)
            self.sync()
            return False
        if not w.settle_graph_draft():
            self.sync()
            return False
        if w.inspector is not None:
            w.inspector_wanted = False
            w.dispose_inspector()
        if getattr(w, "table_move", None) is not None and w.table_move.active:
            w.table_move.start(False)
        tools = self.toolbar
        if tools is not None and tools.mode:
            if tools.mode.name == "PAN":
                tools.pan()
            else:
                tools.zoom()
        if self.controller is None:
            return False
        self.controller.set_mode(mode)
        self.sync()
        return True

    # -- confirmed changes ---------------------------------------------------------------------------
    def commit(self, run, records):
        """One confirmed change of the drawings: one Undo step, the project marked as changed."""
        style = deepcopy(run.style or {})
        if records:
            style[SHAPES] = deepcopy(records)
        else:
            style.pop(SHAPES, None)
        w = self.window
        w.commit_style(run, style)
        w.update_actions()

    def can_arrange(self):
        run = self.selected_run()
        return run is not None and bool((run.style or {}).get(SHAPES)) and self.problem() is None

    def arrange(self):
        from .shape_arrange import ArrangeShapesDialog

        run = self.selected_run()
        records = shapes_of(run)
        axes = run.result.figure.axes[0]

        def preview(candidate):
            render_shapes(axes, candidate)
            self.canvas.draw_idle()

        dialog = ArrangeShapesDialog(self.window, axes, records, preview=preview)
        try:
            accepted = dialog.exec()
            candidate = dialog.result_records if accepted else records
            preview(candidate)
            if candidate != records:
                self.commit(run, candidate)
        finally:
            dialog.deleteLater()

    def history_run(self):
        """The graph whose drawings Undo/Redo affect now, or None for the worksheet history."""
        run = self.selected_run()
        if run is None or run.method in IMPORTED_GRAPHS:
            return None
        active = self.controller is not None and self.controller.mode is not None and self.run is run
        return run if run.shape_history.changes or active else None

    def apply_history(self, run, *, redo=False):
        w = self.window
        if w.job is not None or run.result is None or run.result.figure is None:
            return False
        self.cancel()
        history = run.shape_history
        position = history.position
        records = history.apply(shapes_of(run), redo=redo)
        if records is None:
            w.update_actions()
            return False
        figure = run.result.figure
        try:
            if segment_axes(figure):
                draft = deepcopy(run.style or {})
                draft.pop(SHAPES, None)
                if records:
                    draft[SHAPES] = records
                apply_style(figure, draft)
            else:
                render_shapes(figure.axes[0], records)
        except (ValueError, TypeError, OverflowError) as error:
            history.position = position
            w.error(error)
            return False
        style = deepcopy(run.style or {})
        if records:
            style[SHAPES] = records
        else:
            style.pop(SHAPES, None)
        w.project.commit_style(run, style, record_shapes=False)
        if self.controller is not None and self.controller.selected not in {r["id"] for r in records}:
            self.controller.selected = None
        if self.canvas is not None and self.run is run:
            self.canvas.draw_idle()
        w.update_title()
        w.update_actions()
        w.status(tr("shape.canvas.redo" if redo else "shape.canvas.undo"))
        return True

    def change(self, shape_id, action, value=None):
        """A context-menu edit of one drawing (colour, width, order, duplicate, remove)."""
        run, w = self.run, self.window
        if run is None or self.problem() is not None or not self.allowed():
            return False
        confirmed = shapes_of(run)
        try:
            records, selected = edit_records(confirmed, shape_id, action, value)
            if records == confirmed:
                return False
            self.controller.cancel()
            render_shapes(run.result.figure.axes[0], records)
        except (ValueError, TypeError, OverflowError) as error:
            w.error(error)
            return False
        self.commit(run, records)
        self._select(selected)
        w.status(tr("shape.canvas.changed"))
        return True

    def _select(self, shape_id):
        if self.controller is None:
            return
        if self.controller.mode is None:
            self.controller.set_mode("select")
        self.controller.selected = shape_id
        self.sync()
        self.canvas.draw_idle()

    def clipboard_action(self, action, shape_id=None):
        """Cut, copy or paste a complete drawing object through the system clipboard."""
        w = self.window
        problem = self.problem()
        if problem is None and not self.allowed():
            problem = tr("shape.native")
        if problem:
            w.error(problem)
            return False
        run, axes = self.run, self.run.result.figure.axes[0]
        confirmed = shapes_of(run)
        clipboard = QApplication.clipboard()
        try:
            if action in ("copy", "cut"):
                selected = shape_id or self.controller.selected
                members = next(iter(selected_objects(confirmed, [selected])), [])
                if not members:
                    raise ValueError(tr("shape.clipboard.select"))
                if action == "cut" and is_locked(members):
                    raise ValueError(tr("shape.objects.locked"))
                text = dump_object(members)
                clipboard.setText(text)
                if clipboard.text() != text:
                    raise ValueError(qt("qt.clipboard_failed"))
                if action == "cut":
                    return self.change(selected, "remove")
                w.status(tr("shape.clipboard.copied"))
                return True
            if action != "paste":
                return False
            records, selected = paste_shape(confirmed, clipboard.text())
            if any(not on_axis_domain(axes, record) for record in records[len(confirmed):]):
                raise ValueError(tr("shape.error.axis_domain"))
            self.controller.cancel()
            render_shapes(axes, records)
        except (ValueError, TypeError, OverflowError) as error:
            w.error(error)
            return False
        self.commit(run, records)
        self._select(selected)
        w.status(tr("shape.clipboard.pasted"))
        return True

    # -- editor and menu -----------------------------------------------------------------------------
    def edit(self, shape_id):
        """The numeric editor of ``trama_qt.shapes`` for one drawing (double click or Enter)."""
        from .shapes import ShapeEditor
        run, w = self.run, self.window
        if run is None or self.controller is None or w.job is not None:
            return False
        self.controller.cancel()
        confirmed = shapes_of(run)
        members = next(iter(selected_objects(confirmed, [shape_id])), [])
        if not members:
            return False
        if is_locked(members) or len(members) > 1:
            w.error(tr("shape.objects.locked" if is_locked(members) else "shape.objects.ungroup_first"))
            return False
        record = members[0]
        axes = run.result.figure.axes[0]
        dialog = ShapeEditor(w, axes, record)
        accepted = dialog.exec() == ShapeEditor.DialogCode.Accepted and dialog.result is not None
        if self.controller is None or self.run is not run:
            return False  # The page changed while the editor was open.
        changed = False
        if accepted and dialog.result != record:
            records = [dialog.result if r["id"] == shape_id else r for r in confirmed]
            try:
                render_shapes(axes, records)
            except (ValueError, TypeError, OverflowError) as error:
                render_shapes(axes, confirmed)
                w.error(error)
            else:
                self.commit(run, records)
                changed = True
        self.canvas.draw_idle()
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        return changed

    def context(self, shape_id, event):
        """Right click on a drawing: select it and offer the same choices as the classic window."""
        if not self.start("select"):
            return
        self.controller.selected = shape_id
        self.canvas.draw_idle()
        menu = self.context_menu(shape_id)
        if menu is None:
            return
        gui = getattr(event, "guiEvent", None)
        position = gui.globalPosition().toPoint() if gui is not None and hasattr(gui, "globalPosition") \
            else QCursor.pos()
        self.popup(menu, position)

    def popup(self, menu, position):
        menu.exec(position)
        menu.deleteLater()

    def context_menu(self, shape_id):
        if self.run is None:
            return None
        members = next(iter(selected_objects(shapes_of(self.run), [shape_id])), [])
        if not members:
            return None
        record = next(record for record in members if record["id"] == shape_id)
        locked, grouped = is_locked(members), bool(record.get("group"))
        w = self.window
        menu = QMenu(w)

        def add(text, handler, *, enabled=True, parent=menu):
            action = parent.addAction(text)
            action.triggered.connect(lambda _checked=False: handler())
            action.setEnabled(enabled)
            return action

        add(tr("shape.context.format"), lambda: self.edit(shape_id), enabled=not locked and not grouped)
        command = "unlock" if locked else "lock"
        add(tr(f"shape.objects.{command}"), lambda: self.change(shape_id, command))
        if grouped:
            add(tr("shape.objects.ungroup"), lambda: self.change(shape_id, "ungroup"), enabled=not locked)
        menu.addSeparator()
        for name, shortcut in (("cut", "Ctrl+X"), ("copy", "Ctrl+C"), ("paste", "Ctrl+V")):
            action = add(tr(f"shape.clipboard.{name}"), lambda name=name: self.clipboard_action(name, shape_id),
                         enabled=name != "cut" or not locked)
            action.setShortcut(shortcut)
            action.setShortcutVisibleInContextMenu(True)
        menu.addSeparator()
        if not grouped and not locked:
            suffix = "line" if record["kind"] == "line" else "area"
            add(tr(f"shape.context.color_{suffix}"), lambda: self.choose_color(shape_id, "stroke"))

            def choices(label, key, values, *, translated=True, units=False, enabled=True):
                child = menu.addMenu(tr(label))
                child.setEnabled(enabled)
                current = record.get(key, DEFAULTS.get(key))
                for value in values:
                    caption = tr(f"shape.option.{value}") if translated else f"{value:g}" + (" pt" if units else "")
                    action = add(caption, lambda value=value: self.change(shape_id, key, value), parent=child)
                    action.setCheckable(True)
                    action.setChecked(value == current if translated else float(value) == float(current))

            choices(f"shape.context.width_{suffix}", "width", WIDTHS, translated=False, units=True)
            choices(f"shape.context.style_{suffix}", "line_style", LINE_STYLES)
            if record["kind"] == "line":
                choices("shape.arrow_heads", "arrow_heads", ARROW_HEADS)
                active = record.get("arrow_heads", "none") != "none"
                choices("shape.arrow_style", "arrow_style", ARROW_STYLES, enabled=active)
                choices("shape.arrow_size", "arrow_size", ENDING_SIZES, translated=False, units=True, enabled=active)
            else:
                add(tr("shape.context.fill_color"), lambda: self.choose_color(shape_id, "fill"))
                add(tr("shape.context.no_fill"), lambda: self.change(shape_id, "fill", None))
                choices("shape.hatch", "hatch", HATCHES)
                patterned = record.get("hatch", "none") != "none"
                add(tr("shape.context.pattern_color"), lambda: self.choose_color(shape_id, "hatch_color"),
                    enabled=patterned)
                add(tr("shape.context.pattern_follow"), lambda: self.change(shape_id, "hatch_color", None),
                    enabled=patterned)
            menu.addSeparator()
        for name in ("duplicate", "remove"):
            add(tr(f"shape.context.{name}"), lambda name=name: self.change(shape_id, name), enabled=not locked)
        menu.addSeparator()
        for name in ("front", "back"):
            add(tr(f"shape.context.{name}"), lambda name=name: self.change(shape_id, name), enabled=not locked)
        return menu

    def choose_color(self, shape_id, key):
        from matplotlib.colors import to_hex
        record = next((r for r in shapes_of(self.run) if r["id"] == shape_id), None) if self.run else None
        if record is None:
            return False
        initial = record.get(key) or (record["stroke"] if key == "hatch_color" else "#ffffff")
        color = QColorDialog.getColor(QColor(to_hex(initial, keep_alpha=False)), self.window)
        return color.isValid() and self.change(shape_id, key, color.name())
