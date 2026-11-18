"""Command bars shared by the Standard and Modern workspaces.

The ribbon keeps the commands and the group order of ``App.build_ribbon``. Each group has two rows of
small buttons and, where it has one, a tall lead button (Paste, Analyze…, Import…, New graph…). Labels
appear group by group as the window gets wider; at 1024 px the small buttons are icons, as before.
"""
from itertools import zip_longest
import tkinter as tk
from tkinter import simpledialog, ttk

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


# A surface for the existing actions, ordered for the compact and expanded rows.
MODERN_ACTIONS = {
    "file": ("New", "Open", "Save", "Save as…", "Import…", "Export"),
    "home": ("Paste", "Cut cells", "Copy", "Undo", "Redo", "Add row", "Analyze…", "New graph…", "Export"),
    "insert": ("Add row", "Add column…", "New Info sheet…", "Formula…", "Layout"),
    "analyze": ("Analyze…", "Descriptive statistics", "Linear regression", "Nonlinear regression", "Correlation matrix"),
    "graph": ("New graph…", "Layout", "Pairwise Comparisons…", "Format", "Export"),
    "arrange": ("Arrange drawing objects…", "Layout"),
    "family": ("Family gallery", "Duplicate family…", "Save family as…"),
    "tools": ("Power and sample size…", "Plot a function…", "Monte Carlo study…"),
    "view": ("Show or hide Navigator", "Sheet gallery", "Previous sheet", "Next sheet"),
    "format": ("Format", "Inspector", "Pairwise Comparisons…", "Export with options…"),
    "annotations": ("Graph annotations…", "Graph shapes…", "Arrange drawing objects…"),
}

MODERN_MORE_ACTIONS = {
    "file": ("Export with options…",),
    "home": ("Paste Special…", "Paste as new table", "Exclude / include cell", "Add column…",
             "Descriptive statistics", "Layout", "Import…", "Save"),
    "analyze": ("Change parameters…",),
    "graph": ("Graph annotations…", "Graph shapes…", "Export with options…"),
}

MODERN_CONTEXT = ("format", "annotations")


class CommandSearch(simpledialog.Dialog):
    """Filter enabled workspace actions and return the chosen callback."""

    def __init__(self, parent, commands):
        from .i18n import tr

        self.commands = commands
        self.matches = []
        super().__init__(parent, tr("ribbon.modern.search"))

    def body(self, master):
        from . import ui_theme
        from .i18n import tr

        pane = ttk.Frame(master, padding=(12, 8))
        pane.pack(fill="both", expand=True)
        self.query = tk.StringVar(self)
        search = ttk.Entry(pane, textvariable=self.query, width=46)
        search.pack(fill="x", pady=(0, 8))
        results = ttk.Frame(pane)
        results.pack(fill="both", expand=True)
        self.results = tk.Listbox(results, height=9, borderwidth=1, relief="solid", exportselection=False,
                                  background=ui_theme.SURFACE, foreground=ui_theme.TEXT,
                                  selectbackground=ui_theme.ACCENT, selectforeground="#ffffff",
                                  highlightcolor=ui_theme.ACCENT, font=ui_theme.font())
        self.results.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.results.yview)
        scroll.pack(side="right", fill="y")
        self.results.configure(yscrollcommand=scroll.set)
        self.empty = ttk.Label(pane, text=tr("ribbon.modern.search_empty"), style="Hint.TLabel")
        self.results.bind("<Double-Button-1>", lambda _: self.ok())
        search.bind("<Down>", lambda _: self._move(1))
        search.bind("<Up>", lambda _: self._move(-1))
        self.query.trace_add("write", self._update)
        self._update()
        return search

    def buttonbox(self):
        from .i18n import tr

        box = ttk.Frame(self, padding=(12, 0, 12, 8))
        box.pack(fill="x")
        ttk.Button(box, text=tr("ribbon.modern.run"), command=self.ok, style="Action.TButton").pack(side="right")
        ttk.Button(box, text=tr("language.cancel"), command=self.cancel).pack(side="right", padx=(0, 5))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def _update(self, *_):
        tokens = self.query.get().casefold().split()
        self.matches = [(text, action) for text, action in self.commands
                        if all(token in text.casefold() for token in tokens)]
        self.results.delete(0, "end")
        if self.matches:
            self.empty.pack_forget()
            self.results.insert("end", *(text for text, _ in self.matches))
            self.results.selection_set(0)
        else:
            self.empty.pack(anchor="w", pady=(5, 0))

    def _move(self, step):
        if self.matches:
            selected = self.results.curselection()
            index = max(0, min((selected[0] if selected else 0) + step, len(self.matches) - 1))
            self.results.selection_clear(0, "end")
            self.results.selection_set(index)
            self.results.see(index)
        return "break"

    def validate(self):
        return bool(self.results.curselection())

    def apply(self):
        self.result = self.matches[self.results.curselection()[0]][1]


class ModernRibbon(ttk.Frame):
    """Two levels of commands with graph tabs that follow the active sheet."""

    def __init__(self, parent, groups, factory, ui, menus, extra_actions, *,
                 command_menus=(), expanded=False, save_expanded=None):
        from .i18n import tr

        super().__init__(parent, style="Ribbon.TFrame")
        self._active = "home"
        self._graph = False
        self.expanded = expanded
        self._save_expanded = save_expanded
        self._width = None
        self.density = 0
        self.tabs = {}
        self.buttons = {}
        self._menus = menus
        self._command_menus = command_menus
        self._label = lambda key: tr("ribbon.modern." + key)
        catalogue = {label: (icon, action) for _, *rows in groups for row in rows for label, icon, action in row}
        catalogue.update(extra_actions)

        self._tab_row = ttk.Frame(self, style="Ribbon.TFrame", padding=(7, 3, 7, 0))
        self._tab_row.pack(fill="x")
        self.search = factory(self._tab_row, tr("ribbon.modern.search"), "search",
                              self.open_search, text=True)
        self.search.configure(style="Modern.Ribbon.TButton")
        self.search.pack(side="right")
        self._tab_menu = ttk.Menubutton(self._tab_row, style="Modern.TMenubutton", width=0)
        self._tab_picker = tk.Menu(self._tab_menu, tearoff=False)
        self._tab_menu.configure(menu=self._tab_picker)
        for key in MODERN_ACTIONS:
            style = "ModernContext.Tab.TButton" if key in MODERN_CONTEXT else "Modern.Tab.TButton"
            self.tabs[key] = ttk.Button(self._tab_row, text=self._label(key), style=style, width=0,
                                        command=lambda key=key: self.select_tab(key))

        ttk.Separator(self).pack(fill="x")
        self._bar = ttk.Frame(self, style="Ribbon.TFrame", padding=(7, 4))
        self._bar.pack(fill="x")
        self.toggle = ttk.Button(self._bar, style="Modern.Ribbon.TButton", command=self.toggle_expanded, width=0)
        self.toggle.pack(side="right")
        self.more = ttk.Menubutton(self._bar, text=tr("theme.more"), style="Modern.TMenubutton", width=0)
        self.more.pack(side="right", padx=(3, 4))
        self._more_menu = tk.Menu(self.more, tearoff=False)
        self.more.configure(menu=self._more_menu)
        for caption, *rows in groups:
            submenu = tk.Menu(self._more_menu, tearoff=False)
            for row in rows:
                for label, _, action in row:
                    submenu.add_command(label=ui(label), command=action)
            self._more_menu.add_cascade(label=ui(caption), menu=submenu)
        self._actions_menu = ttk.Menubutton(self._bar, text=tr("ribbon.modern.commands"),
                                            style="Modern.TMenubutton", width=0)
        self._group = ttk.Frame(self._bar, style="Ribbon.TFrame")
        self._group.pack(side="left", fill="x", expand=True)
        for label, (icon, action) in catalogue.items():
            primary = label == "Analyze…"
            button = factory(self._group, label, icon, action, primary=primary)
            button.configure(style="ModernPrimary.Ribbon.TButton" if primary else "Modern.Ribbon.TButton")
            self.buttons[label] = button
        self._update_menu()
        self.bind("<Configure>", self._resized)
        self.fit(820)

    def _update_menu(self):
        from .i18n import tr
        self.toggle.configure(text=tr("ribbon.modern.collapse" if self.expanded else "ribbon.modern.expand"))
        self._actions_menu.pack_forget()
        if menu := self._menus.get(self._active):
            self._actions_menu.configure(menu=menu)
            self._actions_menu.pack(side="right", before=self._group, padx=(3, 0))

    def _visible_tabs(self):
        return tuple(key for key in self.tabs if self._graph or key not in MODERN_CONTEXT)

    def set_graph_context(self, active):
        if active == self._graph:
            return
        self._graph = active
        self.select_tab("format" if active else "home" if self._active in MODERN_CONTEXT else self._active)

    def select_tab(self, key):
        if key not in self._visible_tabs():
            return
        self._active = key
        self._update_menu()
        self.fit(self._width or self.winfo_width())

    def toggle_expanded(self):
        self.expanded = not self.expanded
        self._update_menu()
        self.fit(self._width or self.winfo_width())
        if self._save_expanded is not None:
            self._save_expanded(self.expanded)

    def _fit_tabs(self, width):
        from . import ui_theme
        for button in self.tabs.values():
            button.pack_forget()
        self._tab_menu.pack_forget()
        self._tab_picker.delete(0, "end")
        keys = self._visible_tabs()
        self.search.configure(compound="image" if width < ui_theme.px(1000) else "left")
        width -= self.search.winfo_reqwidth() + ui_theme.px(14)
        required = sum(self.tabs[key].winfo_reqwidth() for key in keys)
        if required > width:
            self._tab_menu.configure(text=self._label(self._active))
            self._tab_menu.pack(side="right")
            width -= self._tab_menu.winfo_reqwidth()
        for key in keys:
            button = self.tabs[key]
            button.state(["selected" if key == self._active else "!selected"])
            size = button.winfo_reqwidth()
            if size <= width:
                button.pack(side="left")
                width -= size
            else:
                self._tab_picker.add_command(label=self._label(key), command=lambda key=key: self.select_tab(key))

    def open_search(self):
        commands = {}
        for button in self.buttons.values():
            if not button.instate(["disabled"]):
                commands[button.cget("text")] = button.invoke
        for menu in self._command_menus:
            end = menu.index("end")
            for index in range(0 if end is None else end + 1):
                if menu.type(index) == "command" and menu.entrycget(index, "state") != "disabled":
                    label = menu.entrycget(index, "label")
                    commands.setdefault(label, lambda menu=menu, index=index: menu.invoke(index))
        dialog = CommandSearch(self.winfo_toplevel(), sorted(commands.items(), key=lambda entry: entry[0].casefold()))
        if dialog.result is not None:
            dialog.result()

    def _active_actions(self):
        compact = MODERN_ACTIONS[self._active]
        if not self.expanded:
            return (compact,)
        extra = MODERN_MORE_ACTIONS.get(self._active, ())
        split = (len(compact) + 1) // 2
        return compact[:split] + extra[:len(extra)//2], compact[split:] + extra[len(extra)//2:]

    def set_density(self, level):
        self.density = level
        for label, button in self.buttons.items():
            labelled = level > 0 or label == "Analyze…"
            button.configure(compound="left" if labelled else "image")

    def fit(self, width):
        from . import ui_theme
        if width <= 1:
            width = 820
        self._fit_tabs(width)
        for button in self.buttons.values():
            button.grid_remove()
        occupied = self.toggle.winfo_reqwidth() + self.more.winfo_reqwidth() + ui_theme.px(22)
        if self._active in self._menus:
            occupied += self._actions_menu.winfo_reqwidth() + ui_theme.px(3)
        rows = self._active_actions()
        available = width - occupied
        for level in (1, 0):
            self.set_density(level)
            columns = [max(self.buttons[label].winfo_reqwidth() + 2 for label in labels if label)
                       for labels in zip_longest(*rows)]
            if sum(columns) <= available:
                break
        for column, size in enumerate(columns):
            if size > available:
                break
            for row_index, row in enumerate(rows):
                if column < len(row):
                    self.buttons[row[column]].grid(row=row_index, column=column, sticky="w", padx=1)
            available -= size
        self.update_idletasks()

    def minimum_width(self):
        # Every action is also reachable from a menu at this width.
        return 820

    def _resized(self, event):
        if event.widget is self and event.width != self._width:
            self._width = event.width
            self.fit(event.width)
