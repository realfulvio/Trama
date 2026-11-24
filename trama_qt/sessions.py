"""The projects open in one Qt window: one session per tab, each with its own ``Project``.

No Qt here. A session keeps what the window shows of its project while another tab is active: the selected
sheet, the cell and scroll positions, the result tab, the Inspector wish and the last status line. The window
installs the active session's state; everything else (data, history, results, layouts, recipes, Info, dirty
state) already lives in the ``Project`` object, so switching never copies a dataset.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
from uuid import uuid4

from .strings import qt

MAX_PROJECT_TABS = 6  # Same limit as the classic window (analisi.project_tabs, which imports Tk).
LABEL_WIDTH = 32


def canonical(path):
    """A path as the file system names it: absolute, links resolved, case folded where the system ignores case."""
    return os.path.normcase(os.path.realpath(os.fspath(path)))


@dataclass(eq=False)
class Session:
    project: object
    selected: tuple | None = None
    view: dict = field(default_factory=dict)
    status: str = ""
    inspector_wanted: bool = False
    inspector_element: object = None
    key: str = field(default_factory=lambda: uuid4().hex)
    combined_navigator: bool = True
    collapsed_folders: set = field(default_factory=set)
    sheet_filter: str = ""
    sheet_history: list = field(default_factory=list)
    sheet_position: int = -1

    def reset(self, project):
        """A fresh project in this tab (the last tab closed)."""
        self.project, self.selected, self.view, self.status = project, None, {}, ""
        self.inspector_wanted, self.inspector_element = False, None
        self.combined_navigator = True
        self.collapsed_folders.clear()
        self.sheet_filter = ""
        self.sheet_history.clear()
        self.sheet_position = -1

    def visit(self, ref):
        if self.sheet_position >= 0 and self.sheet_history[self.sheet_position] == ref:
            return
        self.sheet_history = [*self.sheet_history[:self.sheet_position + 1], ref][-100:]
        self.sheet_position = len(self.sheet_history) - 1

    def paths(self):
        """The files this tab stands for: the saved project and, for an imported project, its source."""
        return [path for path in (self.project.path, self.project.origin) if path is not None]

    def holds(self, path):
        target = canonical(path)
        return any(canonical(own) == target for own in self.paths())


class Sessions:
    """The ordered tabs and the active one."""

    def __init__(self, project):
        self.items = [Session(project)]
        self.active = self.items[0]

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(list(self.items))

    def __getitem__(self, index):
        return self.items[index]

    def index(self, session):
        return self.items.index(session)

    def full(self):
        return len(self.items) >= MAX_PROJECT_TABS

    def add(self, project):
        if self.full():
            raise ValueError(f"Close a project before opening more than {MAX_PROJECT_TABS} at once.")
        session = Session(project)
        self.items.append(session)
        return session

    def remove(self, session):
        """Drop a tab that is not active."""
        if session is self.active:
            raise ValueError("Activate another project before removing this tab.")
        self.items.remove(session)

    def neighbour(self, session):
        """The tab that takes over when ``session`` closes: the one on its left, else the one on its right."""
        position = self.items.index(session)
        if len(self.items) == 1:
            return None
        return self.items[position - 1] if position else self.items[1]

    def step(self, offset):
        position = self.items.index(self.active)
        return self.items[(position + offset) % len(self.items)]

    def find(self, path):
        """The tab that already holds ``path``, saved or imported from it."""
        return next((session for session in self.items if session.holds(path)), None)

    def holding(self, path, besides=None):
        """Another tab whose project is saved at ``path`` (Save as must not overwrite it)."""
        return next((session for session in self.items if session is not besides and session.holds(path)), None)

    def labels(self):
        """Tab captions in the active language: the project name, a dirty marker, and for projects with the same
        name the folders that tell them apart. Returns ``[(caption, tooltip), …]`` in tab order."""
        titles = [session.project.title for session in self.items]
        suffixes = [""] * len(self.items)
        for title in set(titles):
            group = [position for position, other in enumerate(titles) if other == title]
            if len(group) > 1:
                for position, suffix in zip(group, _distinct_folders([self.items[p] for p in group])):
                    suffixes[position] = suffix
        labels = []
        for session, title, suffix in zip(self.items, titles, suffixes):
            caption = elide(title + (f" · {suffix}" if suffix else ""))
            dirty = session.project.dirty
            path = next(iter(session.paths()), None)
            lines = [str(path) if path is not None else qt("qt.not_saved_yet")]
            if dirty:
                lines.append(qt("qt.unsaved_title"))
            labels.append((("• " if dirty else "") + caption, "\n".join(lines)))
        return labels


def elide(text, width=LABEL_WIDTH):
    """Long names keep their start and their end (where numbers and extensions usually are)."""
    if len(text) <= width:
        return text
    head = (width - 1) // 2
    return text[:head] + "…" + text[-(width - 1 - head):]


def _distinct_folders(sessions):
    """For tabs with the same name: the fewest trailing folders of each path that tell them apart."""
    parents = []
    for session in sessions:
        path = next(iter(session.paths()), None)
        parents.append(Path(canonical(path)).parent.parts if path is not None else ())
    depth = max((len(parts) for parts in parents), default=0)
    for count in range(1, depth + 1):
        tails = ["/".join(parts[-count:]) for parts in parents]
        if len(set(tails)) == len(tails):
            break
    else:
        tails = ["/".join(parts) for parts in parents]
    seen = {}
    result = []
    for tail in tails:
        seen[tail] = seen.get(tail, 0) + 1
        result.append(tail if seen[tail] == 1 else f"{tail} ({seen[tail]})")
    return result
