"""Session state and the desktop strip for open projects."""
from dataclasses import dataclass, field
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .i18n import tr
from .worksheet_history import WorksheetHistory
from .workspace_icons import show_hint


MAX_PROJECT_TABS = 6
WELCOME = "Open a project, import data, or start with the example."  # English text of status.welcome
_PROJECT_FIELDS = (
    "tables", "runs", "layouts", "info_sheets", "active_data", "selected", "nav_expansion",
    "history", "history_position", "worksheet_history", "path", "dirty",
)


@dataclass(eq=False)
class ProjectSession:
    number: int = 1
    tables: dict = field(default_factory=dict)
    runs: list = field(default_factory=list)
    layouts: list = field(default_factory=list)
    info_sheets: dict = field(default_factory=dict)
    active_data: str | None = None
    selected: tuple | None = None
    nav_expansion: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    history_position: int = -1
    worksheet_history: WorksheetHistory = field(default_factory=WorksheetHistory)
    path: Path | None = None
    dirty: bool = False
    origin: Path | None = None
    search: str = ""
    status: str = field(default_factory=lambda: tr("status.welcome"))
    grid_view: tuple | None = None

    def capture(self, app):
        for name in _PROJECT_FIELDS:
            setattr(self, name, getattr(app, name))
        self.search = app.search.get()
        self.status = app.status.get()
        self.grid_view = app.current_grid.view_state() if app.current_grid is not None else None

    def install(self, app):
        for name in _PROJECT_FIELDS:
            setattr(app, name, getattr(self, name))

    @property
    def title(self):
        path = self.path or self.origin
        return path.name if path else tr("project.untitled", number=self.number)


class ProjectTabs(ttk.Frame):
    def __init__(self, parent, switch, new, close):
        super().__init__(parent, style="ProjectStrip.TFrame", padding=(5, 0, 5, 0))
        self.switch = switch
        self.notebook = ttk.Notebook(self, style="Projects.TNotebook", height=1)
        self.notebook.pack(side="left", fill="x", expand=True)
        self.notebook.bind("<ButtonPress-1>", self._press)
        self.notebook.bind("<<NotebookTabChanged>>", self._changed)
        self.new_button = ttk.Button(self, text="+", command=new, style="ProjectTool.TButton")
        self.new_button.pack(side="left", padx=(4, 1))
        self.close_button = ttk.Button(self, text="×", command=close, style="ProjectTool.TButton")
        self.close_button.pack(side="left")
        show_hint(self.new_button, tr("project.new_hint"))
        show_hint(self.close_button, tr("project.close_hint"))

    def add(self):
        panel = ttk.Frame(self.notebook, height=1)
        self.notebook.add(panel, text="")
        self.new_button.state(["disabled" if len(self.keys()) >= MAX_PROJECT_TABS else "!disabled"])
        return str(panel)

    def remove(self, key):
        self.notebook.nametowidget(key).destroy()
        self.new_button.state(["!disabled"])

    def keys(self):
        return self.notebook.tabs()

    def select(self, key):
        self.notebook.select(key)

    def caption(self, key, text, dirty):
        width = 23 if len(self.keys()) <= 4 else 16
        label = text if len(text) <= width else text[:width - 1] + "…"
        self.notebook.tab(key, text=label + (" *" if dirty else ""))

    def _press(self, event):
        try:
            key = self.keys()[self.notebook.index(f"@{event.x},{event.y}")]
        except (tk.TclError, IndexError):
            return None
        self.switch(key)
        return "break"

    def _changed(self, _event):
        key = self.notebook.select()
        if key:
            self.switch(key)
