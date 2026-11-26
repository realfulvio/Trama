"""Select and move linked tables directly on native graphs and layout pages in Classica Qt.

``TableMoveController`` handles pointer hit-testing, live drag previews, keyboard nudging,
editor-only selection highlights and movement guides on a ``FigureCanvasQTAgg``.
``LinkedTableCanvas`` connects it to ``MainWindow`` actions, pan/zoom precedence,
``MainWindow.commit_linked_tables`` (one Undo step), and the numeric ``LinkedTableDialog``.
"""
from copy import deepcopy
from math import hypot

import numpy as np
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.transforms import IdentityTransform
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu

from analisi import linked_tables as lt
from analisi.i18n import tr
from analisi.layout_geometry import page_ink
from analisi.shape_interaction import event_key

from .strings import qt
from .theme import DARK, LIGHT

_ARROWS = {
    Qt.Key.Key_Left: (-1.0, 0.0),
    Qt.Key.Key_Right: (1.0, 0.0),
    Qt.Key.Key_Up: (0.0, 1.0),
    Qt.Key.Key_Down: (0.0, -1.0),
}
_ARROW_NAMES = {
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
}


class _Keys(QObject):
    """Canvas keys active only while table-move mode is on; window shortcuts (Tab, F1, Ctrl+Z/Y) stay free."""

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
                event.accept()
                return True
            return self.controller.key(name)
        if kind == QEvent.Type.FocusOut and self.controller.gesture is not None:
            self.controller.cancel(message=tr("linked_table.move.cancelled"))
        return False


class TableMoveController:
    """Opt-in pointer selection and movement of ``LinkedTableArtist`` objects on a figure canvas."""

    def __init__(self, canvas, figure, *, records, commit, status, allowed=lambda: True,
                 edit=None, context=None, mode_changed=lambda _active: None):
        self.canvas = canvas
        self.figure = figure
        self.records = records
        self.commit = commit
        self.status = status
        self.allowed = allowed
        self.edit = edit
        self.context = context
        self.mode_changed = mode_changed
        self.mode = False
        self.selected = None
        self._hovered = None
        self.gesture = None
        self._drag_cache = None
        self._capturing_bg = False
        self._cursor_owned = False
        self._closed = False
        self._filter = None
        self.connections = [
            canvas.mpl_connect(name, callback) for name, callback in (
                ("button_press_event", self.press),
                ("motion_notify_event", self.motion),
                ("button_release_event", self.release),
                ("draw_event", self.draw_overlay),
            )
        ]

    # -- widget key & cursor helpers ---------------------------------------------------------------
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
                pass
            self._filter = None

    def _set_cursor(self, shape):
        if shape is None:
            if self._cursor_owned:
                try:
                    self.canvas.unsetCursor()
                except RuntimeError:
                    pass
                self._cursor_owned = False
        else:
            self.canvas.setCursor(shape)
            self._cursor_owned = True

    def _dpr(self):
        return float(getattr(self.canvas, "device_pixel_ratio", 1.0) or 1.0)

    def _accent(self):
        try:
            ink = page_ink(self.figure.get_facecolor())
        except (ValueError, TypeError):
            ink = "#000000"
        palette = DARK if ink == "#ffffff" else LIGHT
        return palette["table_move_ink"]

    # -- mode & lookup -----------------------------------------------------------------------------
    def set_mode(self, active):
        active = bool(active)
        if active == self.mode:
            return
        self.cancel(redraw=False)
        self.mode = active
        self._hovered = None
        if not active:
            self.selected = None
            self._unbind_keys()
            self._set_cursor(None)
            self.status(tr("linked_table.move.off"))
        else:
            self._bind_keys()
            self.status(tr("linked_table.move.help"))
        self.mode_changed(active)
        self.canvas.draw_idle()

    def _table_artists(self):
        by_id = {record["id"]: record for record in self.records()}
        ordered = []
        for index, artist in enumerate(self.figure.artists):
            if isinstance(artist, lt.LinkedTableArtist) and artist.get_visible():
                table_id = str(artist.get_gid() or "").removeprefix(lt.GID)
                record = by_id.get(table_id)
                if record is not None:
                    ordered.append((float(artist.get_zorder()), index, record, artist))
        ordered.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [(record, artist) for _, _, record, artist in ordered]

    def _artist_for(self, table_id):
        if table_id is None:
            return None
        for record, artist in self._table_artists():
            if record["id"] == table_id:
                return artist
        return None

    def selected_record(self):
        if self.selected is None:
            return None
        return next((record for record in self.records() if record["id"] == self.selected), None)

    def _describe(self, record, position=None):
        kind = tr(f"linked_table.mode.{record['mode']}_short")
        origin = record.get("origin") or tr("linked_table.unknown_source")
        x, y = position if position is not None else record["position"]
        return tr("linked_table.move.selected", kind=kind, origin=origin,
                  x=f"{x * 100:.1f}", y=f"{y * 100:.1f}")

    def hit(self, event):
        """Topmost visible table under ``event`` (exact interior first, then a small edge margin)."""
        if event.x is None or event.y is None:
            return None, None
        candidates = self._table_artists()
        if not candidates:
            return None, None
        px, py = float(event.x), float(event.y)
        tol = 3.0 * float(self.figure.dpi) / 72.0
        for margin in (0.0, tol):
            for record, artist in candidates:
                left, bottom, right, top = artist.bounds_pixels(self.figure)
                if left - margin <= px <= right + margin and bottom - margin <= py <= top + margin:
                    return record, artist
        return None, None

    # -- fast drag blitting ------------------------------------------------------------------------
    def _figure_key(self):
        return (tuple(round(float(v), 4) for v in self.figure.get_size_inches()), float(self.figure.dpi))

    def _begin_drag_preview(self, artist):
        if not all(hasattr(self.canvas, name) for name in ("copy_from_bbox", "restore_region", "blit", "get_renderer")):
            return
        try:
            dpi = float(self.figure.dpi)
            pad_px = max(4, round(4 * dpi / 100.0))
            w_px = max(1, int(np.ceil(artist.extent[0] / 72.0 * dpi)) + 2 * pad_px)
            h_px = max(1, int(np.ceil(artist.extent[1] / 72.0 * dpi)) + 2 * pad_px)
            mini_fig = Figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
            mini_spec = lt.TableSpec({**artist.spec.record, "position": [pad_px / w_px, pad_px / h_px]},
                                     artist.spec.resolved)
            mini_artist = lt.LinkedTableArtist(mini_fig, mini_spec, artist.scale)
            mini_renderer = RendererAgg(w_px, h_px, dpi)
            mini_artist.draw(mini_renderer)
            rgba = np.asarray(mini_renderer.buffer_rgba()).copy()[::-1]

            artist.set_animated(True)
            self._capturing_bg = True
            try:
                self.canvas.draw()
            finally:
                self._capturing_bg = False
            bg = self.canvas.copy_from_bbox(self.figure.bbox)
            self._drag_cache = {
                "artist": artist,
                "bg": bg,
                "rgba": rgba,
                "pad_px": pad_px,
                "key": self._figure_key(),
            }
        except Exception:  # noqa: BLE001 - fall back to ordinary draw_idle() on non-Agg canvases
            self._end_drag_preview()

    def _end_drag_preview(self):
        cache, self._drag_cache = self._drag_cache, None
        if cache is not None:
            cache["artist"].set_animated(False)

    def _render_drag_preview(self, artist, candidate):
        cache = self._drag_cache
        if cache is not None and cache["key"] == self._figure_key() and cache["artist"] is artist:
            self.canvas.restore_region(cache["bg"])
            left_px, bottom_px, _, _ = artist.bounds_pixels(self.figure, candidate)
            renderer = self.canvas.get_renderer()
            gc = renderer.new_gc()
            try:
                renderer.draw_image(gc, round(left_px - cache["pad_px"]), round(bottom_px - cache["pad_px"]),
                                    cache["rgba"])
            finally:
                gc.restore()
            self._paint_overlay(renderer)
            self.canvas.blit(self.figure.bbox)
            return
        if cache is not None:
            self._end_drag_preview()
        self.canvas.draw_idle()

    # -- coordinate conversion ---------------------------------------------------------------------
    def _constrained_delta(self, dx, dy, key):
        modifiers = set(key.lower().replace("control", "ctrl").split("+"))
        if "ctrl" in modifiers and "shift" not in modifiers:
            dy = 0.0
        elif "shift" in modifiers and "ctrl" not in modifiers:
            dx = 0.0
        return dx, dy

    def _candidate_position(self, gesture, dx_px, dy_px, key=""):
        dx_px, dy_px = self._constrained_delta(dx_px, dy_px, key)
        dpi = float(self.figure.dpi)
        left0, top0, _, _ = gesture["start_bounds"]
        return lt.clamp_position(self.figure, gesture["artist"].extent, left0 + dx_px / dpi, top0 - dy_px / dpi)

    # -- pointer events ----------------------------------------------------------------------------
    def press(self, event):
        if self._closed or not self.mode:
            return
        if not self.allowed():
            self.cancel(redraw=False)
            return
        if event.x is None or event.y is None:
            return
        if event.button == 3 and self.context is not None:
            self.cancel()
            record, _ = self.hit(event)
            if record is not None:
                self.selected = record["id"]
                self.status(self._describe(record))
                self.context(record["id"], event)
                if not self._closed:
                    self.canvas.draw_idle()
            return
        if event.button != 1:
            return
        self.cancel()
        record, artist = self.hit(event)
        self.selected = record["id"] if record is not None else None
        self._hovered = None
        if record is None or artist is None:
            self._set_cursor(Qt.CursorShape.ArrowCursor)
            self.status(tr("linked_table.move.help"))
            self.canvas.draw_idle()
            return
        self.status(self._describe(record))
        if event.dblclick:
            self.canvas.draw_idle()
            if self.edit is not None:
                self.edit(record["id"])
            return
        self.gesture = {
            "id": record["id"],
            "artist": artist,
            "snapshot": deepcopy(self.records()),
            "start_px": (float(event.x), float(event.y)),
            "start_bounds": artist.bounds_inches(self.figure),
            "start_pos": list(record["position"]),
            "candidate": None,
            "moved": False,
        }
        self._set_cursor(Qt.CursorShape.ClosedHandCursor)
        self.canvas.draw_idle()

    def motion(self, event):
        if self._closed or not self.mode:
            return
        if self.gesture is None:
            if not self.allowed():
                self._cursor_owned = False  # Pan/Zoom owns the canvas cursor.
                if self._hovered is not None:
                    self._hovered = None
                    self.canvas.draw_idle()
                return
            record, _ = self.hit(event)
            hovered = record["id"] if record is not None else None
            self._set_cursor(Qt.CursorShape.OpenHandCursor if hovered is not None else Qt.CursorShape.ArrowCursor)
            if hovered != self._hovered:
                self._hovered = hovered
                if record is not None and self.selected is None:
                    self.status(self._describe(record))
                self.canvas.draw_idle()
            return
        if not self.allowed():
            self.cancel()
            return
        if event.x is None or event.y is None:
            return
        gesture = self.gesture
        dx = float(event.x) - gesture["start_px"][0]
        dy = float(event.y) - gesture["start_px"][1]
        if not gesture["moved"]:
            if hypot(dx, dy) < 3.0 * self._dpr():
                return
            gesture["moved"] = True
            self._begin_drag_preview(gesture["artist"])
        candidate = self._candidate_position(gesture, dx, dy, event_key(event))
        gesture["candidate"] = candidate
        gesture["artist"].set_preview_position(candidate)
        record = next((r for r in gesture["snapshot"] if r["id"] == gesture["id"]), None)
        if record is not None:
            self.status(self._describe(record, candidate))
        self._render_drag_preview(gesture["artist"], candidate)

    def release(self, event):
        if self._closed or self.gesture is None or event.button != 1:
            return
        gesture = self.gesture
        if event.x is None or event.y is None or not self.allowed():
            self.cancel()
            return
        dx = float(event.x) - gesture["start_px"][0]
        dy = float(event.y) - gesture["start_px"][1]
        if not gesture["moved"] and hypot(dx, dy) < 3.0 * self._dpr():
            self.cancel()
            return
        candidate = self._candidate_position(gesture, dx, dy, event_key(event))
        self._end_drag_preview()
        gesture["artist"].set_preview_position(None)
        self.gesture = None
        if self.mode and self.allowed():
            record, _ = self.hit(event)
            self._hovered = record["id"] if record is not None else None
            self._set_cursor(Qt.CursorShape.OpenHandCursor if record is not None else Qt.CursorShape.ArrowCursor)
        else:
            self._set_cursor(None)
        if candidate == gesture["start_pos"]:
            self.canvas.draw_idle()
            return
        records = [
            {**record, "position": candidate} if record["id"] == gesture["id"] else deepcopy(record)
            for record in gesture["snapshot"]
        ]
        self.selected = gesture["id"]
        self.commit(records)
        if not self._closed:
            self.canvas.draw_idle()

    def cancel(self, *, redraw=True, message=None):
        gesture = self.gesture
        moved = bool(gesture is not None and gesture["moved"])
        self._end_drag_preview()
        if gesture is not None:
            gesture["artist"].set_preview_position(None)
        self.gesture = None
        if not self._closed:
            if self.mode and self.allowed():
                self._set_cursor(Qt.CursorShape.ArrowCursor)
            elif not self.mode:
                self._set_cursor(None)
            else:
                self._cursor_owned = False
        if message:
            self.status(message)
        if moved and redraw and not self._closed:
            self.canvas.draw_idle()

    # -- keyboard ----------------------------------------------------------------------------------
    def key_name(self, event):
        if not self.mode:
            return None
        key, modifiers = event.key(), event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return None
        if key == Qt.Key.Key_Escape and not (ctrl or shift):
            return "escape"
        if self.selected is None:
            return None
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (ctrl or shift):
            return "enter"
        if key in _ARROW_NAMES:
            return "+".join([*(["ctrl"] if ctrl else []), *(["shift"] if shift else []), _ARROW_NAMES[key]])
        return None

    def key(self, name):
        if not self.mode:
            return False
        if name == "escape":
            if self.gesture is not None:
                self.cancel(message=tr("linked_table.move.cancelled"))
                return True
            self.set_mode(False)
            return True
        if not self.allowed() or self.selected is None:
            return False
        if name == "enter":
            self.cancel()
            if self.edit is not None:
                self.edit(self.selected)
            return True
        parts = name.split("+")
        direction = parts[-1]
        deltas = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "up": (0.0, 1.0), "down": (0.0, -1.0)}
        if direction not in deltas or set(parts[:-1]) - {"ctrl", "shift"}:
            return False
        artist = self._artist_for(self.selected)
        records = deepcopy(self.records())
        record = next((r for r in records if r["id"] == self.selected), None)
        if artist is None or record is None:
            return False
        step = 10.0 if len(parts) > 1 else 1.0
        dpr = self._dpr()
        dpi = float(self.figure.dpi)
        left0, top0, _, _ = artist.bounds_inches(self.figure)
        dx_px, dy_px = deltas[direction][0] * step * dpr, deltas[direction][1] * step * dpr
        candidate = lt.clamp_position(self.figure, artist.extent, left0 + dx_px / dpi, top0 - dy_px / dpi)
        if candidate == list(record["position"]):
            return True
        updated = [{**r, "position": candidate} if r["id"] == self.selected else r for r in records]
        self.commit(updated)
        if not self._closed:
            self.status(self._describe(record, candidate))
            self.canvas.draw_idle()
        return True

    # -- editor overlay ----------------------------------------------------------------------------
    def _draw_artist(self, renderer, artist):
        artist.set_transform(IdentityTransform())
        artist.set_figure(self.figure)
        artist.draw(renderer)

    def _paint_overlay(self, renderer):
        accent = self._accent()
        dpr = self._dpr()
        if self.gesture is None and self._hovered is not None and self._hovered != self.selected:
            hovered = self._artist_for(self._hovered)
            if hovered is not None:
                left, bottom, right, top = hovered.bounds_pixels(self.figure)
                pad = 2.0 * dpr
                frame = Line2D(
                    [left - pad, left - pad, right + pad, right + pad, left - pad],
                    [bottom - pad, top + pad, top + pad, bottom - pad, bottom - pad],
                    linewidth=1.1, linestyle="--", color=accent, alpha=0.8,
                )
                self._draw_artist(renderer, frame)

        if self.selected is None:
            return
        selected = self._artist_for(self.selected)
        if selected is None:
            return

        if self.gesture is not None and self.gesture["moved"]:
            s_left, s_top, s_width, s_height = self.gesture["start_bounds"]
            fig_h = float(self.figure.get_size_inches()[1])
            dpi = float(self.figure.dpi)
            gl = s_left * dpi
            gb = (fig_h - s_top - s_height) * dpi
            gr = (s_left + s_width) * dpi
            gt = (fig_h - s_top) * dpi
            ghost = Line2D([gl, gl, gr, gr, gl], [gb, gt, gt, gb, gb],
                           linewidth=1.0, linestyle=":", color=accent, alpha=0.6)
            self._draw_artist(renderer, ghost)

        left, bottom, right, top = selected.bounds_pixels(self.figure)
        if self.gesture is not None and self.gesture["moved"]:
            fig_h_px = float(self.figure.get_size_inches()[1]) * float(self.figure.dpi)
            x_guide = Line2D([0.0, left], [top, top], linewidth=0.9, linestyle="--", color=accent, alpha=0.65)
            y_guide = Line2D([left, left], [fig_h_px, top], linewidth=0.9, linestyle="--", color=accent, alpha=0.65)
            self._draw_artist(renderer, x_guide)
            self._draw_artist(renderer, y_guide)

        pad = 2.0 * dpr
        l, b, r, t = left - pad, bottom - pad, right + pad, top + pad
        tint = Rectangle((l, b), r - l, t - b, facecolor=accent, edgecolor="none", alpha=0.08)
        border = Line2D([l, l, r, r, l], [b, t, t, b, b], linewidth=1.5, linestyle="-", color=accent)
        anchor = Line2D([l], [t], linestyle="none", marker="s", markersize=5.5,
                        markerfacecolor=accent, markeredgecolor="white")
        for artist in (tint, border, anchor):
            self._draw_artist(renderer, artist)

    def draw_overlay(self, event):
        if self._capturing_bg or self._closed or not self.mode or event.canvas.is_saving() or not self.allowed():
            return
        if self._drag_cache is not None and self._drag_cache["key"] != self._figure_key():
            self._end_drag_preview()
        self._paint_overlay(event.renderer)

    def close(self):
        if self._closed:
            return
        self.cancel(redraw=False)
        self.selected = None
        self._hovered = None
        self.mode = False
        self._unbind_keys()
        for connection in self.connections:
            try:
                self.canvas.mpl_disconnect(connection)
            except (AttributeError, RuntimeError, ValueError):
                pass
        self.connections = []
        self._closed = True


class LinkedTableCanvas:
    """Window adapter for interactive linked-table selection and movement on graphs and layouts."""

    def __init__(self, window):
        self.window = window
        self.controller = None
        self.reference = None
        self.canvas = None
        self.toolbar = None
        self.figure = None
        self._nav_connections = []

    def create_actions(self):
        action = self.window._action(
            "linked_table_move",
            tr("command.linked_table_move"),
            self.toggle,
            shortcut="Ctrl+Shift+M",
            tip=tr("linked_table.move.tip"),
        )
        action.setCheckable(True)
        return action

    def toggle(self):
        self.start(self.window.actions["linked_table_move"].isChecked())

    @property
    def active(self):
        return self.controller is not None and self.controller.mode

    @property
    def selected_id(self):
        return self.controller.selected if self.controller is not None else None

    def _records(self, reference=None):
        reference = self.reference if reference is None else reference
        if reference is None:
            return []
        kind, key = reference
        if kind == "graph" and 0 <= key < len(self.window.project.runs):
            return deepcopy((self.window.project.runs[key].style or {}).get(lt.TABLES, []))
        if kind == "layout" and 0 <= key < len(self.window.project.layouts):
            return deepcopy(self.window.project.layouts[key].tables)
        return []

    def problem(self):
        w = self.window
        if w.gallery is not None or not w.selected:
            return tr("linked_table.native")
        if w.job is not None:
            return qt("qt.wait")
        kind, key = w.selected
        if kind == "graph":
            if not 0 <= key < len(w.project.runs):
                return tr("linked_table.native")
            run = w.project.runs[key]
            from .project import LEGACY_GRAPH_METHODS
            if run.method in LEGACY_GRAPH_METHODS:
                return tr("linked_table.native")
            problem = w.project.graph_format_problem(run)
            if problem:
                return problem
        elif kind == "layout":
            if not 0 <= key < len(w.project.layouts) or self.figure is None:
                return tr("linked_table.native")
        else:
            return tr("linked_table.native")
        if self.controller is None or self.reference != w.selected:
            return tr("linked_table.native")
        if not self._records(w.selected):
            return tr("linked_table.move.none")
        return None

    def allowed(self):
        w, tools = self.window, self.toolbar
        return (
            w.gallery is None
            and w.job is None
            and self.controller is not None
            and not (tools is not None and tools.mode)
            and not (w.inspector is not None and w.inspector.has_draft)
        )

    def attach(self, page, canvas, toolbar, reference, figure):  # noqa: ARG002 - page kept for symmetry with GraphDrawing
        self.detach()
        self.reference, self.canvas, self.toolbar, self.figure = reference, canvas, toolbar, figure
        self.controller = TableMoveController(
            canvas,
            figure,
            records=self._records,
            commit=self.commit,
            status=self.window.status,
            allowed=self.allowed,
            edit=self.edit,
            context=self.context,
            mode_changed=lambda _active: self.sync(),
        )
        if toolbar is not None:
            for key in ("pan", "zoom"):
                nav_action = getattr(toolbar, "_actions", {}).get(key)
                if nav_action is not None:
                    nav_action.toggled.connect(self._navigation_toggled)
                    self._nav_connections.append((nav_action, self._navigation_toggled))
        self.sync()

    def detach(self):
        for nav_action, slot in self._nav_connections:
            try:
                nav_action.toggled.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._nav_connections.clear()
        controller, self.controller = self.controller, None
        if controller is not None:
            controller.close()
        self.reference = self.canvas = self.toolbar = self.figure = None
        self.sync()

    def _navigation_toggled(self, _checked=False):
        if self.controller is not None:
            self.controller.cancel(redraw=False)
            self.canvas.draw_idle()

    def cancel(self):
        if self.controller is not None:
            self.controller.cancel()

    def sync(self):
        action = self.window.actions.get("linked_table_move")
        if action is None:
            return
        problem = self.problem()
        if problem is not None and self.controller is not None and self.controller.mode:
            self.controller.set_mode(False)
        active = self.controller is not None and self.controller.mode
        action.setEnabled(problem is None)
        action.setChecked(active)
        label = tr("command.linked_table_move")
        tip = tr("linked_table.move.tip")
        action.setToolTip(tip if problem is None else f"{label}\n{problem}")
        if self.controller is not None and self.controller.selected is not None:
            if self.controller.selected not in {record["id"] for record in self._records()}:
                self.controller.selected = None

    def start(self, active, *, selected=None):
        w = self.window
        if not active:
            if self.controller is not None:
                self.controller.set_mode(False)
            self.sync()
            return True
        problem = self.problem()
        if problem is not None:
            w.error(problem)
            self.sync()
            return False
        if not w.settle_graph_draft():
            self.sync()
            return False
        if w.inspector is not None:
            w.inspector_wanted = False
            w.dispose_inspector()
        if getattr(w, "drawing", None) is not None and w.drawing.controller is not None and w.drawing.controller.mode is not None:
            w.drawing.start(None)
        tools = self.toolbar
        if tools is not None and tools.mode:
            if tools.mode.name == "PAN":
                tools.pan()
            else:
                tools.zoom()
        if self.controller is None:
            return False
        self.controller.set_mode(True)
        if selected is not None and selected in {record["id"] for record in self._records()}:
            self.controller.selected = selected
            self.canvas.draw_idle()
        self.sync()
        return True

    def commit(self, records):
        if self.reference is None:
            return False
        return self.window.commit_linked_tables(self.reference, records)

    def edit(self, table_id):
        from .linked_tables import LinkedTableDialog
        w = self.window
        if self.reference is None or self.controller is None or w.job is not None:
            return False
        self.controller.cancel()
        records = self._records()
        index = next((i for i, record in enumerate(records) if record["id"] == table_id), None)
        if index is None:
            return False
        record = records[index]
        reference = self.reference
        dialog = LinkedTableDialog(w, w.project, record)
        accepted = dialog.exec() == LinkedTableDialog.DialogCode.Accepted and dialog.result is not None
        dialog.deleteLater()
        if self.reference != reference:
            return False
        changed = False
        if accepted and dialog.result != record:
            updated = [dialog.result if i == index else r for i, r in enumerate(records)]
            changed = self.commit(updated)
        if self.canvas is not None:
            self.canvas.draw_idle()
            self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        return changed

    def context(self, table_id, event):
        if not self.active or self.controller is None:
            return
        w = self.window
        menu = QMenu(w)
        edit_action = menu.addAction(tr("linked_table.move.edit_one"))
        edit_action.triggered.connect(lambda _checked=False: self.edit(table_id))
        manage_action = menu.addAction(tr("linked_table.move.manage"))
        manage_action.triggered.connect(lambda _checked=False: w.edit_linked_tables(reference=self.reference))
        gui = getattr(event, "guiEvent", None)
        position = (gui.globalPosition().toPoint() if gui is not None and hasattr(gui, "globalPosition")
                    else QCursor.pos())
        menu.exec(position)
        menu.deleteLater()


__all__ = ["LinkedTableCanvas", "TableMoveController"]
