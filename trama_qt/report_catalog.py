"""What File → Export analysis report… can put in a report, without Qt.

``candidates(project)`` lists the result tables, graphs and layouts of the active project with the
reason why some of them cannot be chosen. Nothing here calculates, draws or changes the project: an
element that is not calculated, is out of date or failed stays in the list, marked and not selectable.

``snapshot`` turns the chosen items into the ``sections`` of ``analisi.report_bundle.export_bundle``
with the export code Trama already uses (CSV like File → Export, SVG through ``analisi.figure_export``
and ``analisi.layout_svg``). It must run on the GUI thread, like every other export of a figure.
"""
from dataclasses import dataclass
import math
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile

from analisi.i18n import active_language
from analisi.legacy_emf_edit import LIMIT_SOURCE
from analisi.legacy_project_metadata import is_import_option
from analisi.legacy_zip_layout import ZIP_LAYOUT
from analisi.report_bundle import LAYOUT_METHOD

from .project import LEGACY_GRAPH_METHODS, SAVED_VIEWS, run_view

TABLE, FIGURE = "table", "figure"
# Recipe keys that only describe where an imported drawing came from or a cached copy of it.
PRIVATE_OPTIONS = {LIMIT_SOURCE, ZIP_LAYOUT}
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp|mnt|media|var|etc|root|private)/)")

_TEXT = {
    "pending": ("Not calculated: open it to calculate it first.", "Non calcolato: aprilo per calcolarlo."),
    "error": ("Out of date or failed: {reason}", "Non aggiornato o in errore: {reason}"),
    "imported": ("Imported graph: no verified SVG export.", "Grafico importato: nessun export SVG verificato."),
    "empty": ("The graph has no axes to export.", "Il grafico non ha assi da esportare."),
    "layout": ("Layout panels not ready: {names}", "Pannelli del layout non pronti: {names}"),
    "layout_missing": ("A panel of the layout no longer exists.", "Un pannello del layout non esiste più."),
    "no_tables": ("No result table.", "Nessuna tabella di risultati."),
}


def text(key, **values):
    english, italian = _TEXT[key]
    message = italian if active_language() == "it" else english
    return message.format(**values) if values else message


@dataclass(frozen=True, eq=False)
class Item:
    """One row of the report dialog. ``ref`` names the source: ``("table", run, name)``, ``("graph", run)``
    or ``("layout", index)``; ``reason`` is why it cannot be chosen, or ``""``."""
    ref: tuple
    kind: str
    label: str
    method: str
    options: dict
    reason: str = ""
    signature: tuple = ()

    @property
    def available(self):
        return not self.reason


# == recipes =====================================================================================
def plain(value, depth=0):
    """A JSON value for the manifest, or ``_DROP`` for values that are not part of a public recipe."""
    if depth > 24:
        return _DROP
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and _ABSOLUTE.match(value):
            return _DROP  # A file path on this computer is not part of the recipe.
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    item = getattr(value, "item", None)  # NumPy scalars.
    if callable(item) and getattr(value, "shape", None) == ():
        try:
            return plain(item(), depth + 1)
        except (TypeError, ValueError):
            return _DROP
    if isinstance(value, (list, tuple)):
        return [entry for entry in (plain(part, depth + 1) for part in value) if entry is not _DROP]
    if isinstance(value, dict):
        result = {}
        for key, entry in value.items():
            key = str(key)
            if key in PRIVATE_OPTIONS or is_import_option(key):
                continue
            entry = plain(entry, depth + 1)
            if entry is not _DROP:
                result[key] = entry
        return result
    if isinstance(value, (bytes, bytearray, memoryview, Path, PureWindowsPath)):
        return _DROP
    try:
        import pandas as pd
        if value is pd.NA or value is pd.NaT:
            return None
    except ImportError:  # pragma: no cover - pandas is a dependency.
        pass
    return str(value)


_DROP = object()


def recipe(options):
    """The canonical recipe of an analysis: its options without file paths, caches and imported drawings."""
    cleaned = plain(dict(options or {}))
    return cleaned if isinstance(cleaned, dict) else {}


def _signature(run):
    return (run.uid, id(run.result), run.method, repr(run.options), run.calculation_error, repr(run.style),
            run.label, id(run.result.figure) if run.result is not None else None)


# == candidates ==================================================================================
def candidates(project):
    """Every result table and graph of every analysis, then every layout, in the order of the navigator."""
    items = []
    for index, run in enumerate(project.runs):
        name, method, signature = project.sheet_title(("result", index)), run.method, _signature(run)
        table_hidden = project.sheet_state(("result", index)).get("hidden")
        options = recipe(run.options)
        result = run.result
        if result is None:
            if not table_hidden:
                items.append(Item(("run", index), TABLE, name, method, options, text("pending"), signature))
            continue
        problem = text("error", reason=run.calculation_error) if run.calculation_error else ""
        tables = [] if table_hidden else list((getattr(result, "tables", None) or {}).items())
        for table, _frame in tables:
            label = name if len(tables) == 1 else f"{name} · {table}"
            items.append(Item(("table", index, table), TABLE, label, method, options, problem, signature))
        figure = getattr(result, "figure", None)
        if figure is not None or method in LEGACY_GRAPH_METHODS or method in SAVED_VIEWS:
            if method in LEGACY_GRAPH_METHODS or method in SAVED_VIEWS:
                reason = text("imported")
            elif figure is None or not figure.axes:
                reason = text("empty")
            else:
                reason = problem
            if not tables or figure is not None:
                kind = "saved-layout" if run_view(method) == "saved-layout" else "graph"
                if not project.sheet_state((kind, index)).get("hidden"):
                    items.append(Item(("graph", index), FIGURE, project.sheet_title((kind, index)),
                                      method, options, reason, signature))
    by_reference = {run.reference: (index, run) for index, run in enumerate(project.runs)}
    for index, layout in enumerate(project.layouts):
        panels = [by_reference.get(reference) for reference in layout.panels]
        signature = (layout.name, layout.columns, tuple(layout.panels), layout.paper, layout.background,
                     layout.panel_size, layout.axis_alignment,
                     *(_signature(entry[1]) if entry else None for entry in panels))
        options = {"columns": layout.columns, "paper": plain(layout.paper), "background": plain(layout.background),
                   "panels": [{"label": entry[1].name, "method": entry[1].method} if entry else None
                              for entry in panels]}
        if layout.panel_size != "original":
            options["panel_size"] = layout.panel_size
        if layout.axis_alignment != "none":
            options["axis_alignment"] = layout.axis_alignment
        if any(entry is None for entry in panels):
            reason = text("layout_missing")
        else:
            waiting = [run.name for _i, run in panels
                       if run.result is None or run.result.figure is None or run.calculation_error
                       or run.method in LEGACY_GRAPH_METHODS or not run.result.figure.axes]
            errors = [run.calculation_error for _i, run in panels if run.calculation_error]
            reason = text("layout", names=", ".join(waiting)) if waiting else ""
            if reason and errors:
                reason += f" ({errors[0]})"
        items.append(Item(("layout", index), FIGURE, layout.name, LAYOUT_METHOD, options, reason, signature))
    return items


def signature(project, item):
    """The current state of an item's source, to notice a change between preview and confirmation."""
    fresh = {entry.ref: entry for entry in candidates(project)}.get(item.ref)
    return None if fresh is None else (fresh.signature, fresh.reason)


# == snapshot ====================================================================================
def _csv(frame, folder):
    from .window import safe_csv  # The CSV of File → Export: formulas quoted, numbers without locale.
    path = Path(folder) / "table.csv"
    safe_csv(path, frame, index=True)
    return path.read_bytes()


def _svg(project, item, folder):
    import matplotlib as mpl

    path = Path(folder) / "figure.svg"
    kind, key = item.ref[0], item.ref[1]
    previous = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = "0"  # Matplotlib writes this date instead of the clock: same figure, same bytes.
    try:
        with mpl.rc_context({"svg.hashsalt": "trama-report"}):
            if kind == "layout":
                project.export_layout(project.layouts[key], path, {"format": "svg"})
            else:
                from analisi.figure_export import export_figure
                from analisi.legacy_zip_layout import ZIP_LAYOUT as zip_layout
                run = project.runs[key]
                paper = run.options[zip_layout]["paper"] if zip_layout in run.options else None
                export_figure(run.result.figure, path, {"format": "svg"}, size_inches=paper)
    finally:
        if previous is None:
            os.environ.pop("SOURCE_DATE_EPOCH", None)
        else:
            os.environ["SOURCE_DATE_EPOCH"] = previous
    return path.read_bytes()


def section(project, item, label, folder):
    """The section of ``item`` for ``export_bundle``; raises ValueError when it can no longer be exported."""
    if not item.available:
        raise ValueError(item.reason)
    if item.kind == TABLE:
        _kind, index, table = item.ref
        frame = project.runs[index].result.tables[table]
        payload = _csv(frame, folder)
    else:
        payload = _svg(project, item, folder)
    return {"label": label, "kind": item.kind, "method": item.method, "options": item.options, "payload": payload}


def project_copy(project):
    """The bytes of a complete .alab copy of ``project``; its file, path and modified state are not touched."""
    from analisi.data import save_project

    with tempfile.TemporaryDirectory(prefix="trama-report-") as folder:
        path = Path(folder) / "project.alab"
        save_project(path, project.tables, layouts=project.layouts, info_sheets=tuple(project.info_sheets.values()))
        return path.read_bytes()
