"""A scrollable Tk dialog body with a separate footer."""
import tkinter as tk
from tkinter import ttk

from . import ui_theme


class ScrolledBody:
    """Vertically scrolling body frame keeping footer buttons visible on 1024x768 screens."""

    def __init__(self, master, height, *, fit_height=False):
        panel_bg = ttk.Style(master).lookup("TLabel", "background") or ui_theme.SURFACE
        self.outer = ttk.Frame(master)
        scroll = ttk.Scrollbar(self.outer, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self.outer, highlightthickness=0, background=panel_bg,
                                yscrollcommand=scroll.set, height=height)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(4, 4, 8, 4))
        window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")

        def resize(_event):
            dimensions = {"width": max(360, self.body.winfo_reqwidth())}
            if fit_height:
                dimensions["height"] = min(height, self.body.winfo_reqheight())
            self.canvas.configure(scrollregion=self.canvas.bbox("all"), **dimensions)

        self.body.bind("<Configure>", resize)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))

    def reveal(self, widget):
        self.canvas.update_idletasks()
        total = max(1, self.body.winfo_height())
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + widget.winfo_height()
        first, last = self.canvas.yview()
        if top < first * total or bottom > last * total:
            self.canvas.yview_moveto(max(0.0, (top - 12) / total))
