"""Shell widgets for the Trama window: the grouped ribbon of proposal A.

The ribbon keeps the commands and the group order of ``App.build_ribbon``. Each group has two rows of
small buttons and, where it has one, a tall lead button (Paste, Analyze…, Import…, New graph…). Labels
appear group by group as the window gets wider; at 1024 px the small buttons are icons, as before.
"""
from tkinter import ttk

# English group title -> the density level (1..3) from which its small buttons carry a text label.
TEXT_FROM = {"File": 2, "Sheet": 3, "Clipboard": 1, "Analysis": 1, "Change": 3, "Import / Export": 1, "Graph": 3}
MAX_DENSITY = 3


class Ribbon(ttk.Frame):
    """Ribbon built from ``groups``: ``(title, top row, bottom row[, lead row])``.

    ``factory(parent, label, icon, action, lead=False, primary=False)`` creates one button; ``ui`` translates
    group titles. ``buttons`` maps the English label to its button.
    """

    def __init__(self, parent, groups, factory, ui):
        super().__init__(parent, style="Ribbon.TFrame", padding=(6, 3, 6, 0))
        ttk.Frame(self, height=1, style="RibbonRule.TFrame").pack(side="bottom", fill="x")
        self.buttons = {}
        self.density = -1
        self._records = []
        self._width = None
        for index, (title, top, bottom, *lead) in enumerate(groups):
            if index:
                ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=3, pady=(3, 4))
            pane = ttk.Frame(self, style="Ribbon.TFrame")
            pane.pack(side="left", fill="y", padx=1)
            ttk.Label(pane, text=ui(title), style="RibbonGroup.TLabel", anchor="center").pack(side="bottom", fill="x")
            body = ttk.Frame(pane, style="Ribbon.TFrame")
            body.pack(side="top", fill="both", expand=True)
            for entries in lead:
                for label, icon, action in entries:
                    button = factory(body, label, icon, action, lead=True, primary=label == "Analyze…")
                    button.pack(side="left", fill="y", padx=(0, 2))
                    self.buttons[label] = button
                    self._records.append((button, title, True))
            grid = ttk.Frame(body, style="Ribbon.TFrame")
            grid.pack(side="left", fill="y")
            for row, entries in enumerate((top, bottom)):
                for column, (label, icon, action) in enumerate(entries):
                    button = factory(grid, label, icon, action)
                    button.grid(row=row, column=column, sticky="w", padx=(0, 1), pady=0)
                    self.buttons[label] = button
                    self._records.append((button, title, False))
        self.set_density(0)
        self.bind("<Configure>", self._resized)

    def set_density(self, level):
        if level == self.density:
            return
        self.density = level
        for button, title, lead in self._records:
            if lead:
                button.configure(compound="top")
            else:
                text = level >= TEXT_FROM.get(title, MAX_DENSITY + 1)
                button.configure(compound="left" if text else "image")
                button.grid_configure(sticky="ew" if text else "w")

    def minimum_width(self):
        """Width of the ribbon with every small button reduced to its icon: the narrowest the window can be."""
        density = self.density
        self.set_density(0)
        self.update_idletasks()
        width = self.winfo_reqwidth()
        self.set_density(density)
        return width

    def _resized(self, event):
        if event.widget is not self or event.width == self._width:
            return
        self._width = event.width
        self.fit(event.width)

    def fit(self, width):
        """Show the most labels that fit in ``width`` pixels."""
        for level in range(MAX_DENSITY, -1, -1):
            self.set_density(level)
            self.update_idletasks()
            if self.winfo_reqwidth() <= width:
                return
        self.set_density(0)


class ModernRibbon(ttk.Frame):
    """A single command row with the complete grouped command catalogue in More.

    Labels stay attached even when a narrow window shows icons only. No analysis or
    worksheet action is removed; the overflow menu contains every original command.
    """
    def __init__(self, parent, groups, factory, ui):
        import tkinter as tk
        from .i18n import tr
        super().__init__(parent, style="Ribbon.TFrame", padding=(10, 7))
        self.buttons = {}
        self._width = None
        self.density = -1
        self._records = []
        self._hidden = ttk.Frame(self)
        catalogue = {}
        self.more = ttk.Menubutton(self, text=tr("theme.more"), style="Modern.TMenubutton")
        menu = tk.Menu(self.more, tearoff=False)
        self.more.configure(menu=menu)
        for title, top, bottom, *lead in groups:
            popup = tk.Menu(menu, tearoff=False)
            for row in (top, bottom, *lead):
                for label, icon, action in row:
                    catalogue[label] = (icon, action)
                    popup.add_command(label=ui(label), command=action)
            menu.add_cascade(label=ui(title), menu=popup)
        visible = ("New", "Open", "Save", "Undo", "Redo", "Paste", "Analyze…", "Export", "New graph…", "Format")
        for label in visible:
            icon, action = catalogue[label]
            if label in ("Undo", "Analyze…", "New graph…"):
                ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=7, pady=4)
            primary = label == "Analyze…"
            button = factory(self, label, icon, action, text=True, primary=primary)
            button.configure(style="ModernPrimary.Ribbon.TButton" if primary else "Modern.Ribbon.TButton",
                             compound="left")
            button.pack(side="left", padx=1)
            self.buttons[label] = button
            self._records.append((button, label, primary))
        for label, (icon, action) in catalogue.items():
            if label not in self.buttons:
                self.buttons[label] = factory(self._hidden, label, icon, action)
        self.more.pack(side="right", padx=(5, 0))
        self.set_density(0)
        self.bind("<Configure>", self._resized)

    def set_density(self, level):
        if level == self.density:
            return
        self.density = level
        for button, label, primary in self._records:
            show = primary or level >= (1 if label in ("Export", "New graph…") else 2)
            button.configure(compound="left" if show else "image")

    def minimum_width(self):
        previous = self.density
        self.set_density(0)
        self.update_idletasks()
        width = self.winfo_reqwidth()
        self.set_density(previous)
        return width

    def fit(self, width):
        for level in (2, 1, 0):
            self.set_density(level)
            self.update_idletasks()
            if self.winfo_reqwidth() <= width:
                return

    def _resized(self, event):
        if event.widget is self and event.width != self._width:
            self._width = event.width
            self.fit(event.width)
