"""Project state and calculations for the Qt window, without any Qt.

The classic window keeps the same logic inside ``tramastat.App``; this module reuses the engine
functions (``analyse``, ``load_workspace``, ``save_project``, the analysis-chain graph) directly so
that the Qt interface never imports Tk.
"""
from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import threading
from uuid import uuid4

import pandas as pd

from analisi.analysis_chain import (MAX_ANALYSIS_NODES, AnalysisGraph, ChainCancelled, ResultSource,
                                    evaluate_graph, result_frame)
from analisi.axis_breaks import AXIS_BREAKS, axis_breaks_reason
from analisi.data import (EDITABLE_PRISM_COLUMNS, EDITABLE_PRISM_EMF, EDITABLE_PRISM_FIXED_VALUES, Dataset,
                          info_references, load_tables, load_workspace, save_project)
from analisi.frequency import FREQUENCY, style_after_parameter_change as frequency_style
from analisi.grid_data import clear_block, grow_rows, paste_block
from analisi.i18n import tr, ui
from analisi.info import info_contexts, validate_info_sheets
from analisi.monte_carlo import MONTE_CARLO as MONTE_CARLO_METHOD, MonteCarloCancelled, monte_carlo
from analisi.pairwise_graph import (SECTION as PAIRWISE_SECTION, attach as attach_pairwise,
                                    comparison_rows as pairwise_rows, endpoint_resolver as pairwise_endpoint,
                                    graph_problem as pairwise_graph_problem, read_section as read_pairwise,
                                    source_problem as pairwise_source_problem, sync_letters_table)
from analisi.presentation import apply_style, compose_layout
from analisi.prism_emf_edit import LIMIT_SOURCE
from analisi.prism_layout_edit import PRISM_EDITABLE_PANELS, PRISM_PANEL_DATA, PRISM_PANEL_EDITS
from analisi.prism_restore import (BINARY_GRAPH_COLLECTION, BINARY_LAYOUT_COLLECTION, PRISM_GRAPH_LINK,
                                   PRISM_GRAPH_STYLE, PRISM_NOTES, PRISM_PREVIEW, PRISM_TITLE,
                                   SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT, SAVED_BINARY_RESULT,
                                   SAVED_EDITABLE_GRAPH, SAVED_XY)
from analisi.survival_plot import style_after_parameter_change as survival_style
from analisi.workbench import analyse
from analisi.worksheet_history import WorksheetHistory, WorksheetState
from analisi.xy_series import (XY_METHOD, assign_colors, prune_options, style_after_parameter_change as xy_style,
                               xy_series)

PROJECT_SUFFIXES = {".alab", ".prism", ".prismt", ".pzf", ".pzt", ".pzfx", ".xml"}
DATA_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx"}
OPEN_FILTER = "*.alab *.csv *.tsv *.txt *.xlsx *.prism *.prismt *.pzt *.pzfx *.pzf *.xml"
PRISM_GRAPH_METHODS = {SAVED_XY, SAVED_BINARY_GRAPH, SAVED_EDITABLE_GRAPH}
SAVED_VIEWS = {SAVED_BINARY_GRAPH, SAVED_BINARY_RESULT, SAVED_BINARY_LAYOUT, SAVED_EDITABLE_GRAPH}
HIERARCHY_GRAPH = "Hierarchy graph"
MAX_TABLES = 256


def run_view(method):
    """Which sheet shows a run first: its results, its graph or a saved layout."""
    if method == SAVED_BINARY_LAYOUT:
        return "saved-layout"
    return "graph" if method in PRISM_GRAPH_METHODS or method == HIERARCHY_GRAPH else "result"


def stored_prism_view(dataset):
    return (dataset.table_format in {BINARY_GRAPH_COLLECTION, BINARY_LAYOUT_COLLECTION}
            or any(method == SAVED_BINARY_RESULT for method, _ in dataset.analyses))


@dataclass
class Run:
    method: str
    title: str
    options: dict
    result: object = None
    slot: int = -1
    style: dict | None = None
    calculation_error: str | None = field(default=None, repr=False, compare=False)
    uid: str = field(default_factory=lambda: str(uuid4()), repr=False)
    source: ResultSource | None = None
    label: str | None = None

    @property
    def reference(self):
        return self.title, self.slot

    @property
    def name(self):
        source_title = self.source.table if self.source is not None else self.title
        return self.label or self.options.get(PRISM_TITLE) or f"{self.method} of {source_title}"

    @property
    def notes(self):
        return self.options.get(PRISM_NOTES)


class CalculationControl:
    """Progress and cancellation shared by the worker and the window. The worker never touches Qt."""

    def __init__(self):
        self.cancel = threading.Event()
        self._lock = threading.Lock()
        self._done = self._total = 0

    def report(self, done, total):
        with self._lock:
            self._done, self._total = max(self._done, done), total

    def progress(self):
        with self._lock:
            return self._done, self._total


def breaks_warning(figure, style):
    reason = axis_breaks_reason(figure) if figure is not None and (style or {}).get(AXIS_BREAKS) else None
    if not reason:
        return None
    return tr("axis_breaks.status.ignored", reason=reason)


def _attach_pairwise(result, frame, pairwise, method):
    if "message" in pairwise:
        attach_pairwise(result.figure, (), None, message=pairwise["message"])
        return
    tables = pairwise["tables"]
    if tables is None:
        try:
            tables = analyse(pairwise["method"], frame, pairwise["options"]).tables
        except Exception as error:
            attach_pairwise(result.figure, (), None, message=f"The comparison source could not be calculated. {error}")
            return
    rows = pairwise_rows(pairwise["method"], tables, pairwise["options"], pairwise_endpoint(method))
    message = None if rows else "The comparison source has no valid P values for this graph."
    attach_pairwise(result.figure, rows, pairwise["settings"], message=message)


def compute(run, frame, control=None, layout_data=None, pairwise=None):
    """Calculate one run on the worker thread (the same steps as ``tramastat.App.compute``)."""
    if run.method == MONTE_CARLO_METHOD and control is not None:
        result = monte_carlo(frame, run.options, progress=control.report, cancel=control.cancel)
    elif run.method == XY_METHOD:
        result = xy_series(frame, run.options, left_scale=(run.style or {}).get("yscale", "linear"))
    else:
        result = analyse(run.method, frame, run.options, layout_data=layout_data,
                         cancel=control.cancel if control is not None else None)
    if result.figure is not None and run.style:
        try:
            apply_style(result.figure, run.style)
        except ValueError as error:
            result.style_warning = str(error)
        else:
            result.style_warning = breaks_warning(result.figure, run.style)
    if pairwise is None or result.figure is None or not result.figure.axes:
        sync_letters_table(result)
    else:
        try:
            _attach_pairwise(result, frame, pairwise, run.method)
        finally:
            sync_letters_table(result)
    return result


def result_as_table(frame):
    """A result table as an editable worksheet: index levels become ordinary columns."""
    if not isinstance(frame.index, pd.RangeIndex):
        labels = frame.index
        columns = set(frame.columns)
        names = []
        for level, title in enumerate(labels.names, 1):
            column = title or ("Label" if labels.nlevels == 1 else f"Level {level}")
            while column in columns:
                column += " (index)"
            columns.add(column)
            names.append(column)
        if isinstance(labels, pd.MultiIndex):
            frame = frame.reset_index(names=names)
        else:
            frame = frame.set_axis(pd.Index([str(value) if isinstance(value, tuple) else value for value in labels],
                                            name=names[0], tupleize_cols=False)).reset_index()
    return frame.rename(columns=str)


@dataclass
class RefreshJob:
    """Immutable inputs of a background recalculation of linked analyses."""
    graph: AnalysisGraph
    selected: list
    roots: dict
    cached: dict
    clones: dict
    pairwise: dict
    layout_data: dict
    control: CalculationControl


class Project:
    def __init__(self, number=1):
        self.number = number
        self.tables = {}
        self.runs = []
        self.layouts = []
        self.info_sheets = {}
        self.path = None
        self.origin = None
        self.dirty = False
        self.history = WorksheetHistory()

    # -- identity -------------------------------------------------------------------------------
    @property
    def title(self):
        path = self.path or self.origin
        return path.name if path else tr("project.untitled", number=self.number)

    def is_empty(self):
        return not self.tables and not self.info_sheets and not self.dirty and self.path is None

    def unique_title(self, title):
        proposed, number = title, 2
        while proposed in self.tables:
            proposed = f"{title} ({number})"
            number += 1
        return proposed

    @staticmethod
    def runs_for(title, dataset):
        """The Run of every stored analysis of a table, with the identity, source and name it was saved with."""
        return [Run(method, title, options, slot=index, style=dataset.graph_styles.get(index),
                    uid=dataset.analysis_ids.get(index, str(uuid4())), source=dataset.analysis_sources.get(index),
                    label=dataset.analysis_labels.get(index))
                for index, (method, options) in enumerate(dataset.analyses)]

    # -- files ----------------------------------------------------------------------------------
    def load(self, path):
        """Open a project or import a data file into this project. Returns the titles added."""
        path = Path(path)
        if path.suffix.lower() == ".alab":
            loaded, layouts, info_sheets = load_workspace(path, include_info=True)
            self.tables, self.layouts = loaded, layouts
            self.info_sheets = {sheet.uid: sheet for sheet in info_sheets}
            self.runs = [run for name, table in loaded.items() for run in self.runs_for(name, table)]
            self.path = path
            self.history.clear()
            self.dirty = False
            return list(loaded)
        info_sheets = []
        tables = load_tables(path, restore_prism=True, info_sheets=info_sheets)
        if path.suffix.lower() in PROJECT_SUFFIXES and not self.tables:
            self.origin = path
        return self.add_tables(tables, info_sheets)

    def add_tables(self, tables, info_sheets=()):
        if not tables and not info_sheets:
            raise ValueError("No data tables were found.")
        if len(self.tables) + len(tables) > MAX_TABLES:
            raise ValueError("A project supports up to 256 data tables.")
        if info_sheets:
            sheets = {**self.info_sheets, **{sheet.uid: sheet for sheet in info_sheets}}
            validate_info_sheets(tuple(sheets.values()), {**self.tables, **dict.fromkeys(tables)})
            self.info_sheets = sheets
        contexts = info_contexts(self.info_sheets.values())
        titles = []
        for name, frame in tables.items():
            title = self.unique_title(name)
            titles.append(title)
            dataset = self.tables[title] = Dataset(frame.reset_index(drop=True),
                                                   info=contexts.get(title, contexts[None]))
            self.runs.extend(self.runs_for(title, dataset))
        self.dirty = True
        return titles

    def update_info_sheets(self, sheets):
        """Replace the Info sheets. Returns the runs to recalculate: those of tables whose formulas read a
        constant that changed (the classic window does the same)."""
        validate_info_sheets(tuple(sheets.values()), self.tables)
        scoped = info_contexts(sheets.values())
        contexts, stale = {}, []
        for title, dataset in self.tables.items():
            context = scoped.get(title, scoped[None])
            if context == dataset.info:
                continue
            contexts[title] = context
            names = {name for expression in dataset.formulas.values() for name in info_references(expression)}
            missing = object()
            if any(context.get(name, missing) != dataset.info.get(name, missing) for name in names):
                stale.append(title)
        self.info_sheets = sheets
        for title, context in contexts.items():
            self.tables[title].info = context
        self.dirty = True
        return [run for run in self.runs if run.title in stale]

    def change_info(self, sheet):
        """Store an edited Info sheet. Returns the runs to recalculate."""
        current = self.info_sheets[sheet.uid]
        if (sheet.table, sheet.fields) != (current.table, current.fields):
            return self.update_info_sheets({**self.info_sheets, sheet.uid: sheet})
        self.info_sheets[sheet.uid] = sheet
        self.dirty = True
        return []

    def move_info(self, uid, step):
        sheets = list(self.info_sheets.items())
        row = list(self.info_sheets).index(uid)
        if 0 <= row + step < len(sheets):
            sheets[row], sheets[row + step] = sheets[row + step], sheets[row]
            self.info_sheets = dict(sheets)
            self.dirty = True

    def apply_family(self, bundle):
        """Add a finished family copy, all or nothing. Returns the navigator reference of the copied focus."""
        for title in bundle.tables:
            if title in self.tables:
                raise ValueError(f'A data table named "{title}" already exists.')
        runs_before, layouts_before = len(self.runs), len(self.layouts)
        infos_before, dirty_before = self.info_sheets, self.dirty
        try:
            self.tables.update(bundle.tables)
            for title, dataset in bundle.tables.items():
                self.runs.extend(self.runs_for(title, dataset))
            self.layouts.extend(bundle.layouts)
            if bundle.infos:
                self.update_info_sheets({**self.info_sheets, **{sheet.uid: sheet for sheet in bundle.infos}})
            self.dirty = True
        except Exception:
            for title in bundle.tables:
                self.tables.pop(title, None)
            del self.runs[runs_before:]
            del self.layouts[layouts_before:]
            self.info_sheets, self.dirty = infos_before, dirty_before
            raise
        kind, key = bundle.focus
        if kind in {"result", "graph", "saved-layout"}:
            index = next((i for i, run in enumerate(self.runs) if run.reference == key), None)
            if index is not None:
                return kind, index
        elif kind == "layout":
            return kind, layouts_before + key
        elif kind in {"info", "data"} and (kind == "data" or key in self.info_sheets):
            return kind, key
        return "data", next(iter(bundle.tables))

    def new_table(self, name, rows=20, columns=3):
        frame = pd.DataFrame({f"Column {index + 1}": pd.Series([pd.NA] * rows, dtype="Float64")
                              for index in range(columns)})
        return self.add_tables({name: frame})[0]

    def save(self, path):
        path = Path(path)
        if path.suffix.lower() != ".alab":
            raise ValueError(tr("error.alab_name"))
        self.sync_links(persist=True)
        save_project(path, self.tables, layouts=self.layouts, info_sheets=tuple(self.info_sheets.values()))
        self.path = path
        self.dirty = False

    # -- analysis links -------------------------------------------------------------------------
    def chain_ids(self):
        linked = {run.uid for run in self.runs if run.source is not None}
        parents = {run.source.analysis_id for run in self.runs if run.source is not None}
        return linked | parents

    def sync_links(self, *, persist=False):
        linked = {run.uid for run in self.runs if run.source is not None}
        if not persist:
            return
        for run in self.runs:
            if run.slot < 0:
                continue
            dataset = self.tables[run.title]
            if linked or run.slot in dataset.analysis_ids:
                dataset.analysis_ids[run.slot] = run.uid
            if run.source is not None:
                dataset.analysis_sources[run.slot] = run.source
            else:
                dataset.analysis_sources.pop(run.slot, None)
            if run.label is not None:
                dataset.analysis_labels[run.slot] = run.label
            else:
                dataset.analysis_labels.pop(run.slot, None)

    def analysis_graph(self, *, replacement=None, additional=None):
        runs = list(self.runs)
        if replacement is not None:
            runs[replacement[0]] = replacement[1]
        if additional is not None:
            runs.append(additional)
        references = {run.reference: run.uid for run in runs}
        dependencies = {}
        for run in runs:
            settings, _ = read_pairwise(run.options)
            reference = (run.title, settings["slot"]) if settings else None
            if reference in references:
                dependencies[run.uid] = [references[reference]]
        return AnalysisGraph([(run.uid, run.source) for run in runs], dependencies=dependencies)

    def input_frame(self, run):
        if run.source is None:
            return self.tables[run.title].frame(mask_excluded=True)
        parent = next((other for other in self.runs if other.uid == run.source.analysis_id), None)
        if parent is None:
            raise ValueError(tr("chain.missing_source"))
        if parent.calculation_error or parent.result is None:
            raise ValueError(tr("chain.calculate_source"))
        return result_frame(parent.result, run.source.table)

    def pairwise_snapshot(self, run):
        """Resolve the comparison source of a graph on the window thread: the worker gets a consistent copy."""
        settings, problem = read_pairwise(run.options)
        if settings is None:
            return None if problem is None else {"message": problem}
        problem = pairwise_graph_problem(run.method, run.options)
        if problem:
            return {"message": problem}
        recipes = self.tables[run.title].analyses if run.title in self.tables else []
        slot = settings["slot"]
        if slot == run.slot or slot >= len(recipes):
            return {"message": "The comparison source is no longer in this table. "
                               "Open Pairwise Comparisons to choose another source."}
        method, options = recipes[slot]
        if method != settings["method"]:
            return {"message": f"The comparison source is now {method}. Open Pairwise Comparisons to choose a source."}
        problem = pairwise_source_problem(run.method, run.options, method, options)
        if problem:
            return {"message": f"{problem} The graph is shown without comparisons."}
        source = next((other for other in self.runs if other.title == run.title and other.slot == slot), None)
        if source is not None and source.source != run.source:
            return {"message": "The comparison source analyzes a different input table. "
                               "Choose an analysis of this graph's input, or remove the comparisons."}
        tables = source.result.tables if source is not None and source.result is not None else None
        return {"settings": settings, "method": method, "options": deepcopy(options), "tables": tables,
                "key": (run.title, slot)}

    def layout_panel_graphs(self, run):
        """Resolve a saved layout's panel links to unique editable graphs."""
        links = run.options.get(PRISM_PANEL_DATA)
        if run.method != SAVED_BINARY_LAYOUT or not isinstance(links, dict):
            return {}
        graphs = {}
        for item in self.runs:
            link = item.options.get(PRISM_GRAPH_LINK)
            if (item.method == SAVED_EDITABLE_GRAPH and item.title in self.tables and isinstance(link, str)
                    and isinstance(item.options.get(PRISM_GRAPH_STYLE), dict)):
                graphs[link] = None if link in graphs else item
        return {panel: graphs[link]
                for panel, link in links.items() if isinstance(link, str) and graphs.get(link)}

    def layout_panel_data(self, run):
        """Data of the editable graphs a saved layout draws again."""
        if run.method != SAVED_BINARY_LAYOUT or not isinstance(run.options.get(PRISM_PANEL_DATA), dict):
            return None
        return {panel: (self.tables[graph.title].frame(mask_excluded=True), graph.options[PRISM_GRAPH_STYLE])
                for panel, graph in self.layout_panel_graphs(run).items()}

    def layout_figure(self, layout):
        by_reference = {run.reference: run for run in self.runs}
        runs = [by_reference.get(reference) for reference in layout.panels]
        if not all(run is not None and run.result is not None and run.result.figure is not None for run in runs):
            return None
        return compose_layout(layout.name, layout.columns, tuple(run.result.figure for run in runs),
                              paper=layout.paper, background=layout.background)

    def layout_runs(self, layout):
        by_reference = {run.reference: run for run in self.runs}
        return [by_reference[reference] for reference in layout.panels if reference in by_reference]

    # -- recalculation --------------------------------------------------------------------------
    def plan_refresh(self, seeds):
        """Everything a worker needs to recalculate ``seeds`` and every analysis that reads them."""
        graph = self.analysis_graph()
        live = {run.uid: run for run in self.runs}
        unavailable = {run.uid for run in self.runs if run.result is None or run.calculation_error}
        selected = graph.affected([run.uid for run in seeds], unavailable=unavailable)
        cached = {run.uid: run.result for run in self.runs
                  if run.result is not None and not run.calculation_error and run.uid not in selected}
        frames, roots, clones, pairwise, layout_data = {}, {}, {}, {}, {}
        for identifier in selected:
            run = live[identifier]
            clone = clones[identifier] = copy(run)
            clone.options, clone.style = deepcopy(run.options), deepcopy(run.style)
            pairwise[identifier] = self.pairwise_snapshot(run)
            layout_data[identifier] = self.layout_panel_data(run)
            if run.source is None:
                if run.title not in frames:
                    frames[run.title] = self.tables[run.title].frame(mask_excluded=True)
                roots[identifier] = frames[run.title]
        return RefreshJob(graph, selected, roots, cached, clones, pairwise, layout_data, CalculationControl())

    @staticmethod
    def run_refresh(job):
        """Worker side: calculate without touching runs or confirmed results."""
        references = {clone.reference: identifier for identifier, clone in job.clones.items()}
        fresh = dict(job.cached)
        job.control.report(0, len(job.selected))

        def calculate(identifier, frame):
            snapshot = job.pairwise[identifier]
            if snapshot and (source := references.get(snapshot.get("key"))) in fresh:
                snapshot = {**snapshot, "tables": fresh[source].tables}
            return compute(job.clones[identifier], frame.copy(deep=True), control=job.control,
                           layout_data=job.layout_data[identifier], pairwise=snapshot)

        return evaluate_graph(job.graph, job.selected, job.roots, job.cached, calculate, cancel=job.control.cancel,
                              progress=job.control.report, on_result=lambda key, value: fresh.__setitem__(key, value))

    def apply_refresh(self, job, outcomes):
        """Publish finished outcomes. A failed recalculation keeps the previous result, marked as not current."""
        live = {run.uid: run for run in self.runs}
        errors = []
        for identifier, outcome in outcomes.items():
            run = live.get(identifier)
            if run is None:
                continue
            if outcome.error is None:
                run.result, run.calculation_error = outcome.result, None
            else:
                message = str(outcome.error)
                run.calculation_error = message
                errors.append(message)
        return errors

    def mark_pending(self, job, message):
        live = {run.uid: run for run in self.runs}
        for identifier in job.selected:
            if identifier in live and live[identifier].result is not None:
                live[identifier].calculation_error = message

    def restore_after_cancel(self, job, message):
        live = {run.uid: run for run in self.runs}
        for identifier in job.selected:
            if identifier in live:
                live[identifier].calculation_error = message if live[identifier].result is not None else None

    # -- analyses -------------------------------------------------------------------------------
    def candidate(self, title, method, options, *, index=None, source=None):
        """The Run a dialog asks for: a new analysis, or the edit of ``runs[index]`` keeping its identity."""
        if index is None:
            dataset = self.tables[title]
            if source is None and len(dataset.analyses) - len(dataset.analysis_sources) >= 256:
                raise ValueError("A table supports up to 256 analyses.")
            if len(self.runs) >= MAX_ANALYSIS_NODES:
                raise ValueError(tr("chain.node_budget"))
            return Run(method, title, options, source=source)
        run = self.runs[index]
        options = dict(options)
        if method == run.method:
            for key in (PRISM_TITLE, PRISM_NOTES, PAIRWISE_SECTION):
                if key in run.options:
                    options[key] = run.options[key]
            if options.get("Group") == run.options.get("Group") and "Group order" in run.options:
                options["Group order"] = run.options["Group order"]
            if method == XY_METHOD:
                for key in ("Series style", "Series side", "Series color", "Right title", "Right scale",
                            "Right minimum", "Right maximum", "Y minimum", "Y maximum"):
                    if key in run.options and key not in options:
                        options[key] = run.options[key]
                options = prune_options(options)
                options["Series color"] = assign_colors(options.get("Y columns") or [], options.get("Series color"))
        if method != run.method and any(run.reference in layout.panels for layout in self.layouts):
            raise ValueError("Change parameters for this method or create a new analysis for the layout.")
        style = run.style
        if method == run.method == FREQUENCY:
            style = frequency_style(style, run.options, options)
        elif method == run.method == "Kaplan–Meier survival":
            style = survival_style(style, run.options, options)
        elif method == run.method == XY_METHOD:
            style = xy_style(style, options)
        candidate = Run(method, run.title, options, slot=run.slot, style=style, uid=run.uid, source=run.source,
                        label=run.label)
        if candidate.source is not None or self.chain_ids():
            self.analysis_graph(replacement=(index, candidate))
        return candidate

    def add_result(self, run, result, index=None):
        """Confirm a calculated candidate. Returns its index and the analyses that read it."""
        run.result, run.calculation_error = result, None
        recipes = self.tables[run.title].analyses
        dependents = []
        if index is None:
            run.slot = len(recipes)
            self.runs.append(run)
            recipes.append((run.method, run.options))
            index = len(self.runs) - 1
        else:
            previous = self.runs[index]
            self.runs[index] = run
            recipes[run.slot] = run.method, run.options
            dependents = [other for other in self.runs if other is not run and (
                (other.source is not None and other.source.analysis_id == previous.uid)
                or (read_pairwise(other.options)[0] or {}).get("slot") == run.slot and other.title == run.title)]
        self.dirty = True
        self.sync_links(persist=True)
        return index, dependents

    # -- layouts --------------------------------------------------------------------------------------
    def layout_candidates(self, current=None):
        return [run for run in self.runs if (run.result is not None and run.result.figure is not None)
                or (current is not None and run.reference in current.panels)]

    def put_layout(self, layout, key=None):
        if key is None:
            if len(self.layouts) >= 128:
                raise ValueError(ui("A project supports up to 128 layouts."))
            self.layouts.append(layout)
            key = len(self.layouts) - 1
        else:
            self.layouts[key] = layout
        self.dirty = True
        return key

    # -- export ---------------------------------------------------------------------------------------
    def imported_vector_format(self, run):
        """The available vector export format for a recovered drawing."""
        preview = run.options.get(PRISM_PREVIEW)
        fmt = preview.get("format") if isinstance(preview, dict) else None
        if run.method in {SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT} and fmt in ("emf", "pdf"):
            return fmt
        dataset = self.tables.get(run.title)
        style = run.options.get(PRISM_GRAPH_STYLE)
        if (run.method == SAVED_EDITABLE_GRAPH and fmt == "emf" and dataset is not None
                and isinstance(style, dict)
                and (dataset.table_format in {EDITABLE_PRISM_EMF, EDITABLE_PRISM_COLUMNS} or LIMIT_SOURCE in style)):
            return fmt
        return None

    def export_imported_vector(self, run, path, *, current_layout=False):
        from analisi.prism_binary_graphs import export_binary_graph
        from analisi.prism_layout_edit import edit_panel_artwork, export_edited_layout

        options = run.options
        preview = options[PRISM_PREVIEW]
        if current_layout:
            export_edited_layout(path, preview, options.get(PRISM_EDITABLE_PANELS),
                                 options.get(PRISM_PANEL_EDITS), self.layout_panel_data(run))
            return
        if run.method == SAVED_EDITABLE_GRAPH:
            frame = self.tables[run.title].frame(mask_excluded=True)
            preview = edit_panel_artwork(frame, options[PRISM_GRAPH_STYLE], preview)
        export_binary_graph(path, preview, layout=run.method == SAVED_BINARY_LAYOUT)

    def layout_panel_figures(self, layout):
        runs = self.layout_runs(layout)
        if len(runs) != len(layout.panels) or any(run.result is None or run.result.figure is None for run in runs):
            raise ValueError(ui("Recalculate the layout panels before exporting the layout."))
        if any(run.calculation_error for run in runs):
            raise ValueError(tr("reference.stale_export"))
        return tuple(run.result.figure for run in runs)

    def layout_pdf_page(self, layout):
        from analisi.layout_pdf import PdfLayoutPage
        return PdfLayoutPage(layout.name, layout.columns, self.layout_panel_figures(layout), layout.paper,
                             layout.background)

    def export_layout(self, layout, path, settings=None):
        """PDF and SVG keep the panels vector; PNG and TIFF render the page (300 dpi unless ``settings`` say).

        ``settings`` come from Export with options; without them the format follows the file suffix.
        """
        from analisi.figure_export import export_figure, export_pdf_bundle
        from analisi.layout_geometry import WHITE
        if settings is None:
            suffix = Path(path).suffix.lower()
            fmt = {".pdf": "pdf", ".svg": "svg", ".tif": "tiff", ".tiff": "tiff"}.get(suffix, "png")
            settings = {"format": fmt} if fmt in {"pdf", "svg"} else {"format": fmt, "dpi": 300}
        fmt = settings["format"]
        if fmt == "pdf":
            export_pdf_bundle([self.layout_pdf_page(layout)], path, settings)
        elif fmt == "svg":
            from analisi.layout_svg import export_layout_svg
            export_layout_svg(layout.name, layout.columns, self.layout_panel_figures(layout), path, settings,
                              paper=layout.paper, background=layout.background)
        else:
            background = WHITE if settings.get("transparent") else layout.background
            figure = compose_layout(layout.name, layout.columns, self.layout_panel_figures(layout),
                                    paper=layout.paper, background=background)
            export_figure(figure, path, settings)

    def export_pdf_pages(self, refs, path, settings, names):
        from analisi.figure_export import export_pdf_bundle
        pages = [self.runs[key].result.figure if kind == "graph" else self.layout_pdf_page(self.layouts[key])
                 for kind, key in refs]
        export_pdf_bundle(pages, path, settings, names)
        return len(pages)

    # -- graph format -----------------------------------------------------------------------------
    def graph_format_problem(self, run):
        """Why this graph cannot be formatted, or None (as in the classic window)."""
        if run.method == SAVED_BINARY_GRAPH:
            return ui("Use Open editable graph when available, or export the original drawing in its saved "
                      "vector format.")
        if run.method == SAVED_EDITABLE_GRAPH and (
                self.tables[run.title].table_format in EDITABLE_PRISM_FIXED_VALUES or PRISM_PREVIEW in run.options):
            return ui("Use Edit graph data to change values in the recovered drawing.")
        if run.result is None or run.result.figure is None or not run.result.figure.axes:
            return ui("Calculate the graph first.")
        return None

    def format_inputs(self, run):
        """The style the dialog starts from and, for a native XY graph, its data and recipe."""
        style = deepcopy(run.style or {})
        xy = None
        if run.method == XY_METHOD:
            axis = dict(style.get("axis") or {})
            y_axis = dict(axis.get("y") or {})
            if "Y minimum" in run.options and "min" not in y_axis:
                y_axis["min"], y_axis["max"] = run.options["Y minimum"], run.options["Y maximum"]
                axis["y"] = y_axis
                style["axis"] = axis
            xy = {"frame": self.tables[run.title].frame(mask_excluded=True), "options": dict(run.options)}
        return style, xy

    def commit_style(self, run, style):
        """Store a style already drawn on the figure (the Inspector previews it before Apply)."""
        run.style = style
        run.result.style_warning = breaks_warning(run.result.figure, style)
        self.tables[run.title].graph_styles[run.slot] = style
        sync_letters_table(run.result)
        self.dirty = True

    def apply_format(self, run, style, *, xy_update=None, xy_result=None):
        if run.method == XY_METHOD and xy_update is not None:
            run.options = xy_update
            run.result = xy_result
            self.tables[run.title].analyses[run.slot] = (run.method, run.options)
        else:
            apply_style(run.result.figure, style)
        run.style = style
        run.result.style_warning = breaks_warning(run.result.figure, style)
        self.tables[run.title].graph_styles[run.slot] = style
        sync_letters_table(run.result)
        self.dirty = True

    def use_result_as_data(self, run, table):
        frame = run.result.tables[table]
        if frame.empty or frame.columns.empty:
            raise ValueError("The result does not contain a data table.")
        editable = result_as_table(frame)
        if run.method == SAVED_BINARY_RESULT:
            editable.attrs.clear()
        return self.add_tables({table: editable})[0]

    # -- worksheet edits ------------------------------------------------------------------------
    def editable(self, title):
        dataset = self.tables[title]
        if stored_prism_view(dataset):
            raise ValueError("Select a source table or use Result as Data to create an editable table.")
        return dataset

    def edit(self, title, label, change):
        """Apply ``change`` to a copy of the table, keep it with undo, and return the analyses to recalculate."""
        dataset = self.editable(title)
        candidate = copy(dataset)
        change(candidate)
        if candidate.formulas:
            candidate.frame()  # A formula that no longer evaluates rejects the edit.
        before = WorksheetState.capture(dataset)
        dataset.raw, dataset.formulas, dataset.excluded = candidate.raw, candidate.formulas, candidate.excluded
        after = WorksheetState.capture(dataset)
        if not self.history.record(title, label, before, after):
            return None
        self.dirty = True
        return self.table_runs(title)

    def table_runs(self, title):
        affected = [run for run in self.runs if run.title == title and run.source is None]
        if any(run.method == SAVED_EDITABLE_GRAPH for run in affected):
            affected.extend(run for run in self.runs
                            if run.title != title and run.method == SAVED_BINARY_LAYOUT
                            and any(graph.title == title for graph in self.layout_panel_graphs(run).values()))
        return affected

    def paste(self, title, top, left, rows, label="Paste"):
        return self.edit(title, label, lambda dataset: paste_block(dataset, top, left, rows))

    def clear(self, title, selection):
        return self.edit(title, "Clear cells", lambda dataset: clear_block(dataset, selection))

    def insert_rows(self, title, position, count=1):
        def change(dataset):
            raw = dataset.raw
            at = max(0, min(position, len(raw)))
            grown = grow_rows(raw, len(raw) + count)
            order = [*range(at), *range(len(raw), len(raw) + count), *range(at, len(raw))]
            frame = grown.iloc[order].reset_index(drop=True)
            frame.attrs = dict(raw.attrs)
            dataset.excluded = {(row + count if row >= at else row, column) for row, column in dataset.excluded}
            dataset.raw = frame
        return self.edit(title, "Insert rows", change)

    def delete_rows(self, title, rows):
        rows = sorted(set(rows))

        def change(dataset):
            raw = dataset.raw
            keep = [index for index in range(len(raw)) if index not in rows]
            frame = raw.iloc[keep].reset_index(drop=True)
            frame.attrs = dict(raw.attrs)
            mapping = {old: new for new, old in enumerate(keep)}
            dataset.excluded = {(mapping[row], column) for row, column in dataset.excluded if row in mapping}
            dataset.raw = frame
        return self.edit(title, "Delete rows", change)

    def insert_column(self, title, position, name):
        def change(dataset):
            raw = dataset.raw.copy()
            if not name.strip() or name in raw.columns or name in dataset.formulas:
                raise ValueError("Choose a new column name.")
            position_ = max(0, min(position, len(raw.columns)))
            raw.insert(position_, name, pd.Series([pd.NA] * len(raw), dtype="Float64"))
            raw.attrs = dict(dataset.raw.attrs)
            dataset.excluded = {(row, column + 1 if column >= position_ else column)
                                for row, column in dataset.excluded}
            dataset.raw = raw
        return self.edit(title, "Insert column", change)

    def delete_columns(self, title, columns):
        columns = sorted(set(columns))

        def change(dataset):
            raw = dataset.raw
            names = [raw.columns[index] for index in columns if index < len(raw.columns)]
            if not names:
                raise ValueError(tr_formula_only())
            frame = raw.drop(columns=names)
            frame.attrs = dict(raw.attrs)
            keep = [index for index in range(len(raw.columns)) if index not in columns]
            mapping = {old: new for new, old in enumerate(keep)}
            dataset.excluded = {(row, mapping[column]) for row, column in dataset.excluded if column in mapping}
            dataset.raw = frame
        return self.edit(title, "Delete columns", change)

    def rename_column(self, title, column, name):
        def change(dataset):
            raw = dataset.raw
            name_ = name.strip()
            if column >= len(raw.columns):
                raise ValueError(tr_formula_only())
            if not name_ or (name_ != raw.columns[column] and (name_ in raw.columns or name_ in dataset.formulas)):
                raise ValueError("Choose a new column name.")
            frame = raw.rename(columns={raw.columns[column]: name_})
            frame.attrs = dict(raw.attrs)
            dataset.raw = frame
        return self.edit(title, "Rename column", change)

    def set_formula(self, title, name, expression):
        """Add a calculated column, or change the expression of an existing one."""
        return self.edit(title, "Edit formula", lambda dataset: dataset.set_formula(name.strip(), expression))

    def toggle_exclusion(self, title, cells):
        def change(dataset):
            current = set(dataset.excluded)
            cells_ = {cell for cell in cells if cell[0] < len(dataset.raw) and cell[1] < len(dataset.raw.columns)}
            if cells_ and cells_ <= current:
                current -= cells_
            else:
                current |= cells_
            dataset.excluded = current
        return self.edit(title, "Exclude cells", change)

    def undo(self, *, redo=False):
        change = self.history.apply(self.tables, redo=redo)
        if change is None:
            return None, None
        self.dirty = True
        return change.title, self.table_runs(change.title)


def tr_formula_only():
    return "Calculated columns are changed with Formula."
