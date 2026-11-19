"""Tk adapter of the shared shape editing controller (``analisi.shape_interaction``).

The transactions, hit testing and overlays live in the toolkit-free module so the Qt window reuses them; this
module only binds the Tk canvas widget's keys and pointer grab. ``ShapeHistory`` and ``render_shapes`` are
re-exported for the classic window and its tests.
"""
from .shape_interaction import MODES, ShapeController, ShapeHistory, event_key, render_shapes

__all__ = ["MODES", "ShapeCanvas", "ShapeHistory", "event_key", "render_shapes"]


class ShapeCanvas(ShapeController):
    """The classic window's controller: Tk key bindings, focus-out cancel and pointer grab."""

    def __init__(self, *args, **kwargs):
        self._grabbed, self._keys = None, {}
        super().__init__(*args, **kwargs)

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
                except _tk().TclError:
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
            except _tk().TclError:
                pass
            self._grabbed = None


def _tk():
    import tkinter
    return tkinter
