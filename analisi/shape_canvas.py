"""Transactional native shape interaction; overlays never enter the persistent artist tree."""
from copy import deepcopy
import json
import tkinter as tk
import uuid

import numpy as np
from matplotlib.lines import Line2D

from .graph_shapes import draw_shapes, on_axis_domain, validate_shapes
from .i18n import tr


class ShapeHistory:
    """Bounded per-graph record snapshots; never overwrites an unexpected external edit."""
    def __init__(self, max_steps=20, max_bytes=512*1024):
        self.max_steps, self.max_bytes = max_steps, max_bytes
        self.changes, self.position = [], 0

    def can_apply(self, *, redo=False):
        return self.position < len(self.changes) if redo else self.position > 0

    def record(self, before, after):
        if before == after:
            return False
        if self.position and self.changes[self.position-1][1] != before:
            self.changes, self.position = [], 0
        del self.changes[self.position:]
        self.changes.append((deepcopy(before), deepcopy(after)))
        while len(self.changes)>1 and (len(self.changes)>self.max_steps or
                                      len(json.dumps(self.changes))>self.max_bytes):
            del self.changes[0]
        self.position = len(self.changes)
        return True

    def apply(self, current, *, redo=False):
        if not self.can_apply(redo=redo):
            return None
        before, after = self.changes[self.position if redo else self.position-1]
        if current != (before if redo else after):
            self.changes, self.position = [], 0
            return None
        self.position += 1 if redo else -1
        return deepcopy(after if redo else before)


def render_shapes(axes, records):
    """Replace just the drawing objects, preserving axis views, data and every other artist."""
    records = validate_shapes(records)
    old = list(getattr(axes, '_tramastat_shapes', ()))
    previous = set(axes.lines) | set(axes.patches)
    try:
        new = draw_shapes(axes, records)
    except Exception:
        for artist in (set(axes.lines) | set(axes.patches)) - previous:
            artist.remove()
        raise
    for artist in old:
        if artist.axes is axes:
            artist.remove()
    axes._tramastat_shapes = new


class ShapeCanvas:
    """Opt-in create/select/move/resize modes on a calculated native graph's primary axes.

    ``records`` returns confirmed canonical records. ``commit`` atomically stores a new list, and does not
    recreate the canvas. Preview changes never call it. ``allowed`` protects pan/zoom, pending work and drafts.
    """
    MODES = (None, 'select', 'line', 'arrow', 'rectangle', 'ellipse')

    def __init__(self, canvas, axes, *, records, commit, status, allowed=lambda: True,
                 undo=None, edit=None, context=None, clipboard=None, mode_changed=lambda mode: None):
        self.canvas, self.axes = canvas, axes
        self.records, self.commit, self.status = records, commit, status
        self.allowed, self.undo, self.edit = allowed, undo, edit
        self.context = context
        self.clipboard = clipboard
        self.mode_changed = mode_changed
        self.mode, self.selected, self.gesture = None, None, None
        self._previewed, self._closed = False, False
        self._grabbed, self._keys = None, {}
        self.connections = [canvas.mpl_connect(name, callback) for name, callback in (
            ('button_press_event', self.press), ('motion_notify_event', self.motion),
            ('button_release_event', self.release), ('draw_event', self.draw_overlay))]

    def set_mode(self, mode):
        if mode not in self.MODES:
            raise ValueError('Unknown shape canvas mode.')
        self.cancel()
        self.mode = mode
        if mode is None:
            self.selected = None
            self._unbind_keys()
        else:
            self._bind_keys()
        self.mode_changed(mode)
        self.status(tr('shape.canvas.help') if mode == 'select' else
                    tr('shape.canvas.draw_help') if mode else tr('shape.canvas.off'))
        self.canvas.draw_idle()

    def _widget(self):
        return self.canvas.get_tk_widget() if hasattr(self.canvas, 'get_tk_widget') else None

    def _bind_keys(self):
        widget = self._widget()
        if widget is None or self._keys:
            return
        mapping = {'<Escape>':'escape', '<Delete>':'delete', '<BackSpace>':'delete',
                   '<Left>':'left','<Right>':'right','<Up>':'up','<Down>':'down',
                   '<Shift-Left>':'shift+left','<Shift-Right>':'shift+right',
                   '<Shift-Up>':'shift+up','<Shift-Down>':'shift+down',
                   '<Control-Left>':'ctrl+left','<Control-Right>':'ctrl+right',
                   '<Control-Up>':'ctrl+up','<Control-Down>':'ctrl+down',
                   '<Control-z>':'ctrl+z','<Control-y>':'ctrl+y','<Return>':'enter'}
        if self.clipboard is not None:
            mapping.update({'<Control-c>':'ctrl+c','<Control-x>':'ctrl+x','<Control-v>':'ctrl+v'})
        for sequence, key in mapping.items():
            previous = widget.bind(sequence)
            def handle_key(event, key=key):
                self.key(key)
                return 'break'
            callback = widget.bind(sequence, handle_key)
            self._keys[sequence] = previous, callback
        previous = widget.bind('<FocusOut>')
        callback = widget.bind('<FocusOut>', lambda event: self.cancel() if self.gesture is not None else None)
        self._keys['<FocusOut>'] = previous, callback
        widget.focus_set()

    def _unbind_keys(self):
        widget = self._widget()
        if widget is not None:
            for sequence, (previous, callback) in self._keys.items():
                try:
                    widget.unbind(sequence, callback)
                    if previous:
                        widget.bind(sequence, previous)
                except tk.TclError:
                    pass  # The containing page can already be going away.
        self._keys.clear()

    def _grab(self):
        widget = self._widget()
        if widget is not None:
            widget.grab_set()
            self._grabbed = widget

    def _ungrab(self):
        if self._grabbed is not None:
            try:
                if self._grabbed.grab_current() is self._grabbed:
                    self._grabbed.grab_release()
            except tk.TclError:
                pass
            self._grabbed = None

    def transform(self, record):
        return self.axes.transAxes if record['units'] == 'axes' else self.axes.transData

    def selected_record(self):
        return next((r for r in self.records() if r['id'] == self.selected), None)

    def hit(self, event):
        point = np.array([event.x, event.y])
        records = {r['id']: r for r in self.records()}
        artists = sorted(getattr(self.axes, '_tramastat_shapes', ()), key=lambda a: a.get_zorder(), reverse=True)
        tolerance = 5*self.canvas.figure.dpi/72
        for artist in artists:
            record = records.get(str(artist.get_gid()).removeprefix('tramastat-shape-'))
            if record is None or record['alpha'] == 0:
                continue
            if record['kind'] == 'line':
                points = self.transform(record).transform(record['points'])
                start, end = points[0], points[-1]
                delta = end-start
                fraction = np.clip((point-start)@delta/max(float(delta@delta),1e-20),0,1)
                found = np.linalg.norm(point-(start+fraction*delta)) <= tolerance
                if not found and not isinstance(artist, Line2D):
                    path = artist.get_path().transformed(artist.get_transform())
                    found = (path.contains_point(point,radius=2*tolerance)
                             or path.contains_point(point,radius=-2*tolerance))
            else:
                path = artist.get_path().transformed(artist.get_transform())
                outer = path.contains_point(point,radius=2*tolerance)
                inner = path.contains_point(point,radius=-2*tolerance)
                found = outer or inner
                if record['kind'] != 'line' and record['fill'] is None and record.get('hatch','none') == 'none':
                    found = found and not (outer and inner)
            if found:
                return record
        return None

    def press(self, event):
        if not self._closed and event.button == 3 and event.inaxes is self.axes and self.context is not None:
            if not self.allowed():
                return
            self.cancel()
            record = self.hit(event)
            if record is not None:
                self.selected = record['id']
                self.context(record['id'], event)
                if not self._closed:
                    self.canvas.draw_idle()
            return
        if self._closed or self.mode is None or event.button != 1:
            return
        if not self.allowed():
            self.set_mode(None)
            return
        if event.inaxes is not self.axes:
            return
        self.cancel()
        point = np.array([event.x, event.y],dtype=float)
        snapshot = deepcopy(self.records())
        if self.mode == 'select':
            record = self.selected_record()
            endpoint = None
            if record is not None:
                distances = np.linalg.norm(self.transform(record).transform(record['points'])-point,axis=1)
                if min(distances) <= 7*self.canvas.figure.dpi/72:
                    endpoint = int(np.argmin(distances))
            if endpoint is None:
                record = self.hit(event)
            self.selected = record['id'] if record is not None else None
            self.canvas.draw_idle()
            if record is None:
                return
            if event.dblclick:
                if self.edit is not None:
                    self.edit(self.selected)
                return
            self.gesture = {'kind':'resize' if endpoint is not None else 'move','record':deepcopy(record),
                            'endpoint':endpoint,'snapshot':snapshot,'start':point}
        else:
            record = {'id':str(uuid.uuid4()),'kind':'line' if self.mode=='arrow' else self.mode,
                      'units':'axes','points':[[0.,0.],[0.,0.]],'stroke':'#216a94','width':1.5,
                      'line_style':'solid','fill':None,'alpha':1.,'layer':'above'}
            if self.mode == 'arrow':
                record.update(arrow_heads='end',arrow_style='filled')
            self.gesture = {'kind':'create','record':record,'snapshot':snapshot,'start':point,'endpoint':1}
        self._previewed = False
        self._grab()

    def candidate(self, point, key=''):
        gesture = self.gesture
        record = deepcopy(gesture['record'])
        transform = self.transform(record)
        if gesture['kind'] == 'move':
            delta = point-gesture['start']
            modifiers = set(key.lower().replace('control', 'ctrl').split('+'))
            if 'ctrl' in modifiers and 'shift' not in modifiers:
                delta[1] = 0.
            elif 'shift' in modifiers and 'ctrl' not in modifiers:
                delta[0] = 0.
            if not np.any(delta):
                return deepcopy(gesture['snapshot'])
            pixels = transform.transform(record['points']) + delta
        else:
            if gesture['kind'] == 'create':
                pixels = np.array([gesture['start'],point],dtype=float)
            else:
                pixels = transform.transform(record['points'])
                pixels[gesture['endpoint']] = point
            if record['kind'] != 'line' and ('control' in key or 'ctrl' in key):
                moving = gesture['endpoint']; fixed = 1-moving
                delta = pixels[moving]-pixels[fixed]
                side = max(abs(delta))
                pixels[moving] = pixels[fixed]+np.copysign([side,side],delta)
        record['points'] = transform.inverted().transform(pixels).tolist()
        records = deepcopy(gesture['snapshot'])
        if gesture['kind'] == 'create':
            records.append(record)
        else:
            records = [record if r['id']==record['id'] else r for r in records]
        records = validate_shapes(records)
        if not on_axis_domain(self.axes,record):
            raise ValueError(tr('shape.error.axis_domain'))
        return records

    def motion(self, event):
        if self.gesture is None:
            return
        if not self.allowed():
            self.cancel()
            return
        try:
            records = self.candidate(np.array([event.x,event.y],dtype=float),event.key or '')
        except (ValueError,TypeError,OverflowError):
            return  # No invalid recipe or partial candidate can reach the confirmed model.
        render_shapes(self.axes,records)
        self._previewed = True
        self.canvas.draw_idle()

    def release(self, event):
        if self.gesture is None or event.button != 1:
            return
        gesture = self.gesture
        try:
            distance = np.linalg.norm(np.array([event.x,event.y])-gesture['start'])
            if distance < 3 or not self.allowed():
                self.cancel()
                return
            records = self.candidate(np.array([event.x,event.y],dtype=float),event.key or '')
        except (ValueError,TypeError,OverflowError):
            self.cancel()
            self.status(tr('shape.canvas.invalid'))
            return
        self.gesture = None
        self._previewed = False
        self._ungrab()
        render_shapes(self.axes,records)
        if records != gesture['snapshot']:
            self.commit(deepcopy(records))
        self.selected = gesture['record']['id']
        if self.mode != 'select' and 'shift' not in (event.key or ''):
            self.mode = 'select';self.mode_changed('select')
        self.status(tr('shape.canvas.changed'))
        self.canvas.draw_idle()

    def cancel(self, *, redraw=True):
        previewed = self._previewed
        self.gesture = None
        self._previewed = False
        self._ungrab()
        if previewed:
            render_shapes(self.axes,self.records())
            if redraw:
                self.canvas.draw_idle()

    def key(self, key):
        key = key.lower().replace('control', 'ctrl')
        if self.mode is None:
            return False
        if key == 'escape':
            self.cancel();self.set_mode('select')
            return True
        if not self.allowed():
            return True
        if key in ('ctrl+c','ctrl+x','ctrl+v') and self.clipboard is not None:
            self.cancel()
            self.clipboard({'ctrl+c':'copy','ctrl+x':'cut','ctrl+v':'paste'}[key])
            return True
        if key in ('ctrl+z','ctrl+y'):
            self.cancel()
            if self.undo is not None:
                self.undo(key=='ctrl+y')
            return True
        record = self.selected_record()
        if record is None:
            return True
        if key == 'enter':
            if self.edit is not None:
                self.edit(record['id'])
            return True
        if key == 'delete':
            records = [r for r in self.records() if r['id']!=self.selected]
            render_shapes(self.axes,records);self.commit(deepcopy(records));self.selected=None
        else:
            parts = key.split('+')
            direction = parts[-1]
            deltas = {'left':(-1,0),'right':(1,0),'up':(0,1),'down':(0,-1)}
            if direction not in deltas or set(parts[:-1]) - {'shift', 'ctrl'}:
                return True
            delta = np.array(deltas[direction],dtype=float)*(10 if len(parts)>1 else 1)
            transform = self.transform(record)
            moved = deepcopy(record)
            moved['points'] = transform.inverted().transform(transform.transform(record['points'])+delta).tolist()
            records = [moved if r['id']==record['id'] else r for r in self.records()]
            try:
                records=validate_shapes(records)
                if not on_axis_domain(self.axes,moved):
                    raise ValueError(tr('shape.error.axis_domain'))
            except ValueError:
                self.status(tr('shape.canvas.invalid'));return True
            render_shapes(self.axes,records);self.commit(deepcopy(records))
        self.canvas.draw_idle()
        return True

    def draw_overlay(self, event):
        if self._closed or self.mode is None or event.canvas.is_saving():
            return
        record = self.selected_record()
        if record is None:
            return
        # This artist is drawn directly, never added to axes.lines or the figure's saved content.
        pixels = self.transform(record).transform(record['points'])
        handle = Line2D(pixels[:,0],pixels[:,1],linestyle='none',marker='s',markersize=6,
                        markerfacecolor='white',markeredgecolor='#176676')
        from matplotlib.transforms import IdentityTransform
        handle.set_transform(IdentityTransform());handle.set_figure(self.canvas.figure)
        handle.draw(event.renderer)

    def close(self):
        if self._closed:
            return
        self.cancel(redraw=False);self.selected=None;self.mode=None;self._unbind_keys()
        for connection in self.connections:
            self.canvas.mpl_disconnect(connection)
        self.connections=[];self._closed=True
