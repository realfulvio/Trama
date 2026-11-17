"""Icons and hover hints for the Trama shell. The shapes live in ``ui_icons``; the colours in ``ui_theme``."""
from PIL import ImageTk

from . import ui_icons, ui_theme

# Names the application uses -> shapes of the icon set.
ALIASES = {
    "paste-special": "pastespecial", "format": "params", "folder": "open", "family": "link", "previous": "prev",
    "following": "next", "add-row": "addrow", "add-column": "addcol", "style": "format",
    "export-options": "exportopts", "linear": "linreg", "table": "data",
}


class IconSet(dict):
    """Normal icons by name, with ``state(name)`` for buttons (grey when disabled) and ``on_accent(name)``."""

    def __init__(self):
        super().__init__()
        self.disabled = {}
        self.white = {}

    def state(self, name):
        return (self[name], "disabled", self.disabled[name])


def workspace_icons(master):
    size = ui_theme.icon_size()
    icons = IconSet()
    names = {*ui_icons.ICONS, *ALIASES}
    cache = {}
    for name in sorted(names):
        shape = ALIASES.get(name, name)
        if shape not in cache:
            cache[shape] = tuple(
                ImageTk.PhotoImage(ui_icons.render(shape, size, ink=ink, accent=accent, knockout=ui_theme.CHROME),
                                   master=master)
                for ink, accent in ((ui_theme.ICON_INK, ui_theme.ACCENT),
                                    (ui_theme.DISABLED, ui_theme.DISABLED), ("#ffffff", "#ffffff")))
        icons[name], icons.disabled[name], icons.white[name] = cache[shape]
    return icons


def show_hint(widget, label):
    """Show an icon button's name on hover or keyboard focus."""
    from tkinter import Toplevel, ttk

    timer, tip = None, None

    def hide(_event=None):
        nonlocal timer, tip
        if timer is not None:
            widget.after_cancel(timer)
            timer = None
        if tip is not None:
            tip.destroy()
            tip = None

    def show():
        nonlocal timer, tip
        timer = None
        tip = Toplevel(widget)
        tip.overrideredirect(True)
        tip.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
        ttk.Label(tip, text=label, padding=(7, 4), relief="solid").pack()

    def schedule(_event):
        nonlocal timer
        hide()
        timer = widget.after(450, show)

    for event in ("<Enter>", "<FocusIn>"):
        widget.bind(event, schedule, add="+")
    for event in ("<Leave>", "<FocusOut>", "<ButtonPress-1>", "<Destroy>"):
        widget.bind(event, hide, add="+")
