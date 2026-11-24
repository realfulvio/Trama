"""What the Qt gallery lists: graphs and layouts of a project, their state, and the literal search.

Nothing here draws or calculates. It only reads the confirmed results of ``Project`` (and never changes
them), so scanning a project for the gallery cannot start a calculation or mark the project as modified.
"""
from dataclasses import dataclass
import unicodedata

from analisi.workbench import GRAPH_METHODS
from analisi.paired_graphs import shows_paired_estimation

from .project import run_view

GRAPH, LAYOUT = "graph", "layout"
READY, PENDING, STALE, ERROR = "ready", "pending", "stale", "error"
KINDS = (None, GRAPH, LAYOUT)  # The views of the gallery: all, graphs, layouts.


@dataclass(frozen=True, eq=False)
class Entry:
    """One card. ``ref`` is the reference the workbench navigates with, e.g. ``("graph", 0)``."""
    ref: tuple
    name: str
    kind: str
    state: str
    detail: str = ""
    ordinal: int = 0  # Position among the sheets that share the name; 0 when the name is unique.
    total: int = 1
    panels: int = 0
    folded: str = ""
    refs: tuple = ()  # Confirmed objects a preview depends on; compared by identity to notice a recalculation.
    sig: tuple = ()  # Style and layout settings a preview depends on.

    @property
    def previewable(self):
        return self.state in (READY, STALE)


def fold(text):
    """Text for comparing: accents removed, case folded, white space collapsed. ``$`` and other characters
    stay literal."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def graph_runs(project):
    """``(index, run)`` of every graph sheet, as the navigator lists them."""
    return [(index, run) for index, run in enumerate(project.runs)
            if not project.sheet_state(("graph", index)).get("hidden")
            and (run_view(run.method) == "graph" or run.method in GRAPH_METHODS
            or (run.result is None and shows_paired_estimation(run.method, run.options))
            or (run.result is not None and run.result.figure is not None and run_view(run.method) == "result"))]


def layout_refs(project):
    """References of every layout sheet: the project's layouts, then layouts imported with their drawing."""
    return ([("layout", index) for index in range(len(project.layouts))]
            + [("saved-layout", index) for index, run in enumerate(project.runs)
               if run_view(run.method) == "saved-layout"
               and not project.sheet_state(("saved-layout", index)).get("hidden")])


def _state(runs, expected):
    errors = [run.calculation_error for run in runs if run.calculation_error]
    if len(runs) < expected or any(run.result is None or run.result.figure is None for run in runs):
        return (ERROR, errors[0]) if errors else (PENDING, "")
    if errors:
        return STALE, errors[0]
    return READY, ""


def describe(project, ref):
    """The card of one sheet, or None when the reference no longer names a graph or a layout."""
    kind, key = ref
    try:
        if kind == "graph" or kind == "saved-layout":
            run = project.runs[key]
            runs, name, expected, extra = [run], project.sheet_title(ref), 1, ()
        elif kind == "layout":
            layout = project.layouts[key]
            runs, name, expected = project.layout_runs(layout), layout.name, len(layout.panels)
            extra = (layout.columns, tuple(layout.panels), layout.paper, layout.background)
        else:
            return None
    except (IndexError, TypeError):
        return None
    state, detail = _state(runs, expected)
    figures = tuple(run.result.figure if run.result is not None else None for run in runs)
    return Entry(tuple(ref), name, GRAPH if kind == "graph" else LAYOUT, state, detail,
                 panels=expected if kind == "layout" else 0, folded=fold(name),
                 refs=tuple(run.result for run in runs) + figures,
                 sig=tuple(repr(run.style) for run in runs) + extra)


def catalog(project):
    """Every graph, then every layout, in the order of the navigator."""
    refs = [("graph", index) for index, _ in graph_runs(project)] + layout_refs(project)
    entries = [entry for entry in (describe(project, ref) for ref in refs) if entry is not None]
    totals, seen = {}, {}
    for entry in entries:
        totals[entry.name] = totals.get(entry.name, 0) + 1
    result = []
    for entry in entries:
        seen[entry.name] = seen.get(entry.name, 0) + 1
        if totals[entry.name] > 1:
            entry = _numbered(entry, seen[entry.name], totals[entry.name])
        result.append(entry)
    return result


def _numbered(entry, ordinal, total):
    values = {name: getattr(entry, name) for name in entry.__dataclass_fields__}
    values.update(ordinal=ordinal, total=total)
    return Entry(**values)


def visible(entries, kind=None, text=""):
    """The entries of a view that contain the search text. The match is literal, never a pattern."""
    query = fold(text)
    return [entry for entry in entries
            if (kind is None or entry.kind == kind) and (not query or query in entry.folded)]
