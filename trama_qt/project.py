"""Project state and calculations for the Qt window, without any Qt.

The classic window keeps the same logic inside ``tramastat.App``; this module reuses the engine
functions (``analyse``, ``load_workspace``, ``save_project``, the analysis-chain graph) directly so
that the Qt interface never imports Tk.
"""
from copy import copy, deepcopy
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

import numpy as np
import pandas as pd

from analisi import anova_comparison_plot, anova_diagnostics, anova_grouped_plot
from analisi.layout_panels import EMPTY_PANEL
from analisi.analysis_chain import (MAX_ANALYSIS_NODES, AnalysisGraph, ChainCancelled, ResultSource,
                                    evaluate_graph, result_frame)
from analisi.axis_breaks import AXIS_BREAKS, axis_breaks_reason
from analisi.linked_axes import linked_axes_status
from analisi.observation_labels import LABELS, label_status_line
from analisi.point_style import POINTS, point_styles_status
from analisi.data import (EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_EMF, EDITABLE_LEGACY_FIXED_VALUES,
                          EDITABLE_LEGACY_XY, MAX_CELLS, MAX_COLUMNS, MAX_ENTRY, Dataset, info_references,
                          load_tables, load_workspace, project_document, rename_formula_columns, save_project)
from analisi.ecdf_graph import METHOD as ECDF_GRAPH, style_after_parameter_change as ecdf_style
from analisi.frequency import FREQUENCY, style_after_parameter_change as frequency_style
from analisi.interaction_plot import METHOD as INTERACTION_PLOT, style_after_parameter_change as interaction_style
from analisi.raincloud_plot import METHOD as RAINCLOUD_PLOT, style_after_parameter_change as raincloud_style
from analisi.graph_annotations import ANNOTATIONS
from analisi.graph_shapes import SHAPES
from analisi import linked_tables
from analisi.linked_tables import TABLES, FrameSource, Problem, TableSpec
from analisi.worksheet_number_format import Renderer, automatic_text
from analisi.grid_headings import xy_replicate_groups, xy_source_roles
from analisi.grid_data import clear_block, edit_cell_value, grow_rows, paste_block
from analisi.category_levels import (LevelEditError, apply_level_plan, can_rename_levels, find_blocking_recipes,
                                     format_recipe_blockers)
from analisi.category_order import WORKSHEET_ORDERS, keep_source_columns
from analisi.variable_types import TYPES, VARIABLE_TYPES, convert_type
from analisi.numeric_series import NumericSeriesPlan, apply_numeric_series, plan_numeric_series, series_text
from analisi.i18n import tr, ui
from analisi.info import InfoSheet, info_contexts, validate_info_sheets
from analisi.legacy_notes import WORKSHEET_NOTES
from analisi.repeated_input import SAVED_REPLICATE_DISPLAY
from analisi.plot_function import OBSERVATION_COLUMNS, PLOT_FUNCTION
from analisi.pca_graphs import SAVED_DIRECTIONS as PCA_SAVED_DIRECTIONS, SAVED_VIEWPORT as PCA_SAVED_VIEWPORT
from analisi.pca_overlays import SAVED_APPEARANCE as PCA_OVERLAY_APPEARANCE
from analisi.pca_parallel_archive import ARCHIVE as PCA_PARALLEL_ARCHIVE
from analisi.monte_carlo import MONTE_CARLO as MONTE_CARLO_METHOD, MonteCarloCancelled, monte_carlo
from analisi.kmeans_archive import ARCHIVE as KMEANS_ARCHIVE
from analisi.kmeans_stability import METHOD as KMEANS_STABILITY, analysis as kmeans_stability
from analisi import logistic_validation
from analisi.pairwise_graph import (SECTION as PAIRWISE_SECTION, attach as attach_pairwise,
                                    comparison_rows as pairwise_rows, endpoint_resolver as pairwise_endpoint,
                                    graph_problem as pairwise_graph_problem, read_section as read_pairwise,
                                    source_problem as pairwise_source_problem, sync_letters_table)
from analisi.parallel_analyses import precompute as precompute_analyses
from analisi.presentation import Layout, apply_style, compose_layout, validate_graph_style
from analisi.legacy_emf_edit import LIMIT_SOURCE
from analisi.stats import FIXED_COEFFICIENTS, STARTING_COEFFICIENTS, STARTING_COEFFICIENTS_BY_SERIES
from analisi.legacy_fit_graph import FIT_GRAPH_SPEC, FIT_INTERVAL_BAND
from analisi.nonlinear_calibration import PADE_DRAWING
from analisi.legacy_xml_qc import QC_REFERENCE
from analisi.legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_DATA, LEGACY_PANEL_EDITS
from analisi.legacy_restore import (LEGACY_GRAPH_LINK,
                                   LEGACY_GRAPH_STYLE, LEGACY_LAYOUT_GRID, LEGACY_NOTES, LEGACY_PREVIEW, LEGACY_TITLE,
                                   SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT, SAVED_BINARY_RESULT,
                                   SAVED_EDITABLE_GRAPH, SAVED_XY, linked_curve_view, linked_panel_readers, panel_source_style,
                                   resolve_layout_panel_graphs)
from analisi.legacy_xml_binding import SCATCHARD
from analisi.shape_interaction import ShapeHistory
from analisi.select_transform import SELECT_TRANSFORM, seeded_transform_options
from analisi.survival_plot import style_after_parameter_change as survival_style
from analisi.survival_plot import SURVIVAL_GRAPH
from analisi.workbench import GROUPS, analyse
from analisi import worksheet_join
from analisi.worksheet_join_app import WorksheetJoinSources, stored_legacy_view
from analisi.worksheet_history import WorksheetChange, WorksheetHistory, WorksheetState
from analisi.worksheet_column_identity import (COLUMN_IDS, after_deletion as column_ids_after_deletion,
                                               after_insertion as column_ids_after_insertion,
                                               after_rename as column_ids_after_rename,
                                               store as store_column_ids)
from analisi.worksheet_row_identity import (ROW_SPANS, after_deletion, after_insertion, after_move, after_permutation,
                                           current_spans, move_row_index, row_move_slices, row_tokens,
                                           validate_permutation)
from analisi import source_link
from analisi.worksheet_sort import ASCENDING, plan_row_sort, sort_text, validate_sort_key
from .sheet_commands import SheetCommands
from analisi.xy_series import (XY_METHOD, assign_colors, retain_recipe_options,
                               style_after_parameter_change as xy_style, xy_series)
from .graph_style_presets import TRANSFERABLE, plan_preset_batch
from .strings import qt

PROJECT_SUFFIXES = {".alab", ".prism", ".prismt", ".pzf", ".pzt", ".pzfx", ".xml"}
DATA_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx"}
OPEN_FILTER = "*.alab *.csv *.tsv *.txt *.xlsx *.prism *.prismt *.pzt *.pzfx *.pzf *.xml"
LEGACY_GRAPH_METHODS = {SAVED_XY, SAVED_BINARY_GRAPH, SAVED_EDITABLE_GRAPH}
SAVED_VIEWS = {SAVED_BINARY_GRAPH, SAVED_BINARY_RESULT, SAVED_BINARY_LAYOUT, SAVED_EDITABLE_GRAPH, SCATCHARD}
HIERARCHY_GRAPH = "Hierarchy graph"
MAX_TABLES = 256
GRAPHING = (*GROUPS["Graphing"], PLOT_FUNCTION)
GRAPH_TYPE_METHODS = (*GRAPHING, "Histogram", FREQUENCY)


def run_view(method):
    """Which sheet shows a run first: its results, its graph or a saved layout."""
    if method == SAVED_BINARY_LAYOUT:
        return "saved-layout"
    if method in LEGACY_GRAPH_METHODS or method in {
            HIERARCHY_GRAPH, anova_comparison_plot.METHOD, anova_diagnostics.METHOD, anova_grouped_plot.METHOD}:
        return "graph"
    return "result"


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
    # Undo/Redo of the drawings of this graph only: never shared with the worksheet or another graph.
    shape_history: ShapeHistory = field(default_factory=ShapeHistory, repr=False, compare=False)

    @property
    def reference(self):
        return self.title, self.slot

    @property
    def name(self):
        source_title = self.source.table if self.source is not None else self.title
        return self.label or self.options.get(LEGACY_TITLE) or f"{self.method} of {source_title}"

    @property
    def notes(self):
        return self.options.get(LEGACY_NOTES)


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


def graph_warning(figure, style):
    """The notes about saved style sections that the graph cannot draw right now (breaks, linked axes)."""
    notes = [note for note in (breaks_warning(figure, style), linked_axes_status(figure, style),
                               point_styles_status(figure, (style or {}).get(POINTS)),
                               label_status_line(figure, (style or {}).get(LABELS))) if note]
    return " ".join(notes) or None


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


def compute(run, frame, control=None, layout_data=None, pairwise=None, *, result=None, join_data=None):
    """Calculate a run and apply its style and comparisons on the window's worker thread.

    ``join_data`` is the right worksheet of a join, read on the window thread by ``Project.join_data``: a frame,
    or the FieldError that explains why it cannot be read (the run then fails with that message)."""
    if isinstance(join_data, Exception):
        raise join_data
    if result is None:
        if run.method == MONTE_CARLO_METHOD and control is not None:
            result = monte_carlo(frame, run.options, progress=control.report, cancel=control.cancel)
        elif run.method == KMEANS_STABILITY and control is not None:  # one progress step per K-means fit
            result = kmeans_stability(frame, run.options, cancel=control.cancel, progress=control.report)
        elif run.method == logistic_validation.METHOD and control is not None:
            result = logistic_validation.analysis(frame, run.options, cancel=control.cancel, progress=control.report)
        elif run.method == XY_METHOD:
            result = xy_series(frame, run.options, left_scale=(run.style or {}).get("yscale", "linear"))
        else:
            result = analyse(run.method, frame, run.options, layout_data=layout_data,
                             cancel=control.cancel if control is not None else None, join_data=join_data)
    if result.figure is not None and run.style:
        try:
            apply_style(result.figure, run.style)
        except ValueError as error:
            result.style_warning = str(error)
        else:
            result.style_warning = graph_warning(result.figure, run.style)
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
    result = frame.rename(columns=str)
    result.attrs.pop(VARIABLE_TYPES, None)
    return result


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
    join_data: dict = field(default_factory=dict)  # uid -> right worksheet frame (or its FieldError) of a join


@dataclass(frozen=True)
class Snapshot:
    """A detached copy of what a project has confirmed, taken on the GUI thread and serialised elsewhere."""
    tables: dict
    layouts: list
    info_sheets: tuple
    sheet_metadata: dict = field(default_factory=dict)

    def to_bytes(self, batch=256):
        """The .alab bytes, identical to what Save writes. Safe on any thread: nothing here is shared with the
        project. The rows are encoded ``batch`` rows at a time: ``json.dumps`` holds the interpreter lock for the
        whole call, so one call on a 10,000 × 30 table would freeze the window for about a tenth of a second."""
        document = project_document(self.tables, layouts=self.layouts, info_sheets=self.info_sheets,
                                    sheet_metadata=self.sheet_metadata)
        marker = uuid4().hex
        rows = {}
        for index, record in enumerate(document["tables"]):
            placeholder = f"\x00{marker}:{index}\x00"
            rows[json.dumps(placeholder, ensure_ascii=False)] = record["rows"]
            record["rows"] = placeholder
        text = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        for placeholder, table in rows.items():
            pieces = [json.dumps(table[start:start + batch], ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":"))[1:-1] for start in range(0, len(table), batch)]
            text = text.replace(placeholder, "[" + ",".join(pieces) + "]", 1)
        data = text.encode("utf-8")
        if len(data) > MAX_ENTRY:
            raise ValueError("The project exceeds the 32 MiB limit.")
        return data


def _file_stamp(path):
    try:
        status = os.stat(path)
    except (OSError, TypeError):
        return None
    return [status.st_size, status.st_mtime_ns]


@dataclass(frozen=True, eq=False)
class StyleBatchChange:
    """One undoable multi-graph figure style step capturing only the affected runs' styles."""
    label: str
    before: dict
    after: dict
    seq: int = 0


@dataclass(frozen=True)
class LayoutChange:
    index: int
    before: Layout
    after: Layout
    seq: int


@dataclass(frozen=True)
class LayoutFamilyChange(LayoutChange):
    bundle: object
    runs: tuple


@dataclass(frozen=True)
class BatchStyleOutcome:
    """Outcome of applying a figure style preset to a selection of graphs."""
    preset_name: str
    selected_uids: tuple
    changed_uids: tuple
    unchanged_uids: tuple


class ProjectHistory(WorksheetHistory):
    """Project undo/redo for worksheet edits, figure style batches and layout edits."""

    def __init__(self, *, memory_budget=96 * 1024 * 1024):
        self._seq = 0
        super().__init__(memory_budget=memory_budget)

    def clear(self):
        super().clear()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_change(self, *, redo=False):
        if not self.can_apply(redo=redo):
            return None
        return self.changes[self.position if redo else self.position - 1]

    def record_style_batch(self, label, before, after):
        if not before or before == after:
            return False
        del self.changes[self.position:]
        self.changes.append(StyleBatchChange(label, deepcopy(before), deepcopy(after), self.next_seq()))
        self._trim()
        self.position = len(self.changes)
        return True

    def record_layout(self, index, before, after, *, family=None):
        del self.changes[self.position:]
        args = index, deepcopy(before), deepcopy(after), self.next_seq()
        self.changes.append(LayoutChange(*args) if family is None else LayoutFamilyChange(*args, *family))
        self._trim()
        self.position = len(self.changes)

    def _trim(self):
        while True:
            worksheet_changes = [change for change in self.changes if isinstance(change, WorksheetChange)]
            states = [state for change in worksheet_changes for state in (change.before, change.after)]
            sizes = {}
            exclusions = {}
            backgrounds = {}
            for state in states:
                key = id(state.raw)
                if key not in sizes:
                    sizes[key] = self.frame_sizes.get(key)
                    if sizes[key] is None:
                        sizes[key] = int(state.raw.memory_usage(deep=True).sum())
                exclusions[id(state.excluded)] = len(state.excluded) * 72
                if state.cell_backgrounds:
                    backgrounds[id(state.cell_backgrounds)] = len(state.cell_backgrounds) * 112
                if state.row_heights:
                    backgrounds[id(state.row_heights)] = len(state.row_heights) * 64
                for sheets in (state.result_backgrounds or {}).values():
                    for cells in sheets.values():
                        backgrounds[id(cells)] = len(cells) * 112
                if state.number_formats:
                    backgrounds[id(state.number_formats)] = len(state.number_formats) * 160
                for sheets in (state.result_number_formats or {}).values():
                    for formats in sheets.values():
                        backgrounds[id(formats)] = len(formats) * 160
                if state.text_styles:
                    backgrounds[id(state.text_styles)] = state.text_styles.run_count() * 200
                if state.source_link is not None:  # 16 bytes per confirmed file row.
                    backgrounds[id(state.source_link)] = len(state.source_link.digests) + 1024
                for sheets in (state.result_text_styles or {}).values():
                    for styles in sheets.values():
                        backgrounds[id(styles)] = styles.run_count() * 200
            style_bytes = sum(len(repr(change.before)) + len(repr(change.after))
                              for change in self.changes if isinstance(change, StyleBatchChange))
            for change in self.changes:
                if isinstance(change, LayoutFamilyChange):
                    for dataset in change.bundle.tables.values():
                        key = id(dataset.raw)
                        if key not in sizes:
                            size = self.frame_sizes.get(key)
                            sizes[key] = size if size is not None else int(dataset.raw.memory_usage(deep=True).sum())
            self.frame_sizes = sizes
            total_bytes = sum(sizes.values()) + sum(exclusions.values()) + sum(backgrounds.values()) + style_bytes
            if len(self.changes) == 1 or (len(self.changes) <= 24 and total_bytes <= self.memory_budget):
                return
            del self.changes[0]


class TableLookup:
    """Reads the sheets and results that linked tables point at, on the window thread.

    It never calculates: a result that is not there yet, or whose last calculation failed, is reported as such.
    The frame of a sheet is read once per lookup, so redrawing every table after an edit costs one pass."""

    def __init__(self, project):
        self.project = project
        self._sheets = {}

    def sheet(self, title):
        if title in self._sheets:
            return self._sheets[title]
        dataset = self.project.tables.get(title)
        if dataset is None:
            found = Problem("missing", tr("linked_table.detail.sheet", name=title))
        else:
            try:
                # Without formulas or a column order the stored frame is what the grid shows: no copy of a big sheet.
                frame = dataset.raw if not dataset.formulas and dataset.column_order is None else dataset.frame()
            except (ValueError, TypeError, ZeroDivisionError) as error:
                found = Problem("error", str(error))
            else:
                formats = Renderer(dataset.displayed_number_formats)

                def text(row, column, frame=frame, formats=formats):
                    value = frame.iat[row, column]
                    shown = formats.text(column, value)
                    return automatic_text(value) if shown is None else shown

                found = FrameSource(frame, text, spans=current_spans(dataset.raw))
        self._sheets[title] = found
        return found

    def result(self, analysis, table):
        run = next((other for other in self.project.runs if other.uid == analysis), None)
        if run is None:
            return Problem("missing", tr("linked_table.detail.analysis"))
        if run.calculation_error:
            return Problem("error", run.calculation_error)
        if run.result is None:
            return Problem("pending", tr("linked_table.detail.pending"))
        frame = run.result.tables.get(table)
        if frame is None:
            return Problem("missing", tr("linked_table.detail.result_table", name=table))
        formats = Renderer(self.project.tables[run.title].result_number_formats.get(run.slot, {}).get(table, {}))

        def label(position, frame=frame):
            value = frame.index[position]
            return " · ".join(automatic_text(part) for part in value) if isinstance(value, tuple) \
                else automatic_text(value)

        def text(row, column, frame=frame, formats=formats):
            value = frame.iat[row, column]
            shown = formats.text(column + 1, value)  # Position 0 of a result grid is the row-title column.
            return automatic_text(value) if shown is None else shown

        return FrameSource(frame, text, row_label=label, labelled=not isinstance(frame.index, pd.RangeIndex))


class Project(WorksheetJoinSources, SheetCommands):
    def __init__(self, number=1):
        self.number = number
        self.tables = {}
        self.runs = []
        self.layouts = []
        self.linked_graph_views = {}
        self.info_sheets = {}
        self.sheet_metadata = {}
        self.path = None
        self.origin = None
        self.revision = 0  # Grows at every change (each ``dirty = True``): recovery copies follow it.
        self.dirty = False
        self.history = ProjectHistory()
        self.undo_changed_data = True  # Set by ``undo``: False after undoing colours or number formats only.
        self.undo_style_uids = ()  # Set by ``undo``: affected run UIDs after undoing/redoing a style batch.
        self.undo_layout_index = None
        # Recovery copies (trama_qt/recovery.py): one key for the life of this project, a sequence of generations,
        # the original the copy refers to and the state that original had when it was opened or saved.
        self.recovery_key = uuid4().hex
        self.recovery_generation = 0
        self.recovered_from = None  # The original of a recovered copy (str), which stays on disk untouched.
        self.recovered_title = None
        self.recovery_base_title = None  # The title the copy was taken under (without "recovered").
        self.save_suggestion = None  # Where Save as proposes to put a recovered copy.
        self.source_stamp = None

    @property
    def dirty(self):
        return self._dirty

    @dirty.setter
    def dirty(self, value):
        self._dirty = bool(value)
        if value:
            self.revision += 1

    # -- identity -------------------------------------------------------------------------------
    @property
    def title(self):
        path = self.path or self.origin
        if path:
            return path.name
        return self.recovered_title or tr("project.untitled", number=self.number)

    @property
    def recovery_source(self):
        """The original this project stands for, as a string: the saved file, the imported file, or for a
        recovered copy the original it came from."""
        path = self.path or self.origin
        return str(path) if path is not None else self.recovered_from

    def is_empty(self):
        return not self.tables and not self.info_sheets and not self.layouts and not self.dirty and self.path is None

    def unique_title(self, title, *, occupied=None):
        occupied = self.tables if occupied is None else occupied
        proposed, number = title, 2
        while proposed in occupied:
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
    def load(self, path, *, initial_sheet=None, import_warnings=None, link_folder=None):
        """Open a project or import a data file into this project. Returns the titles added."""
        path = Path(path)
        if path.suffix.lower() == ".alab":
            loaded, layouts, info_sheets = load_workspace(path, include_info=True)
            folder = path.absolute().parent if link_folder is None else Path(link_folder).absolute()
            for dataset in loaded.values():
                if dataset.source_link is not None and dataset.source_link.relative:
                    dataset.source_link = replace(dataset.source_link, relative_folder=folder)
            from .frozen_output import restore
            runs = [run for name, table in loaded.items() for run in self.runs_for(name, table)]
            frozen = loaded.sheet_metadata.get("frozen_runs", {})
            for run in runs:
                if run.uid in frozen:
                    run.result = restore(frozen[run.uid])
            self.tables, self.layouts, self.runs = loaded, layouts, runs
            self.linked_graph_views.clear()
            self.sheet_metadata = loaded.sheet_metadata
            self.info_sheets = {sheet.uid: sheet for sheet in info_sheets}
            self.path = path
            self.history.clear()
            self.dirty = False
            self.source_stamp = _file_stamp(path)
            return list(loaded)
        info_sheets = []
        tables = load_tables(path, restore_legacy=True, info_sheets=info_sheets,
                             initial_sheet=initial_sheet, import_warnings=import_warnings)
        if path.suffix.lower() in PROJECT_SUFFIXES and not self.tables:
            self.origin = path
            self.source_stamp = _file_stamp(path)
        return self.add_tables(tables, info_sheets)

    def add_tables(self, tables, info_sheets=()):
        if not tables and not info_sheets:
            raise ValueError("No data tables were found.")
        if len(self.tables) + len(tables) > MAX_TABLES:
            raise ValueError("A project supports up to 256 data tables.")
        occupied, names = set(self.tables), {}
        for name in tables:
            title = self.unique_title(name, occupied=occupied)
            names[name] = title
            occupied.add(title)
        incoming = [replace(sheet, table=names[sheet.table]) if sheet.table in names else sheet
                    for sheet in info_sheets]
        for name, frame in tables.items():
            title = names[name]
            for number, (text, styles) in enumerate(frame.attrs.get(WORKSHEET_NOTES, ()), 1):
                note_title = tr("worksheet.imported_note", name=title[:122], number=number)
                incoming.append(InfoSheet(note_title, notes=text, table=title, note_styles=styles, floating=True))
        sheets = {**self.info_sheets, **{sheet.uid: sheet for sheet in incoming}}
        validate_info_sheets(tuple(sheets.values()), occupied)
        contexts = info_contexts(sheets.values())
        datasets, imported_runs = {}, []
        for name, frame in tables.items():
            title = names[name]
            source = frame.reset_index(drop=True)
            source.attrs.pop(WORKSHEET_NOTES, None)
            source.attrs.pop(ROW_SPANS, None)
            dataset = datasets[title] = Dataset(source, info=contexts.get(title, contexts[None]))
            imported_runs.extend(self.runs_for(title, dataset))
        self.info_sheets = sheets
        self.tables.update(datasets)
        self.runs.extend(imported_runs)
        self._add_imported_layouts(imported_runs)
        self.dirty = True
        return list(datasets)

    def _add_imported_layouts(self, runs):
        """Create editable pages only when every panel has a unique native graph in this import."""
        graphs = {}
        for run in runs:
            if linked_curve_view(run) and isinstance(link := run.options.get(LEGACY_GRAPH_LINK), str):
                graphs[link] = None if link in graphs else run.reference
        names = {layout.name for layout in self.layouts}
        for run in runs:
            if len(self.layouts) >= 128:
                break
            grid = run.options.get(LEGACY_LAYOUT_GRID) if run.method == SAVED_BINARY_LAYOUT else None
            if not isinstance(grid, dict):
                continue
            columns, links = grid.get("columns"), grid.get("links")
            if (type(columns) is not int or not 1 <= columns <= 4 or not isinstance(links, list)
                    or not 1 <= len(links) <= 12 or len(links) % columns
                    or any(not isinstance(link, str) or graphs.get(link) is None for link in links)):
                continue
            base = f"{run.name[:130]} · {tr('layout.imported_editable')}"
            name, number = base, 2
            while name in names:
                name, number = f"{base} ({number})", number + 1
            self.layouts.append(Layout(name, columns, [graphs[link] for link in links]))
            names.add(name)

    def update_info_sheets(self, sheets):
        """Replace the Info sheets. Returns the runs to recalculate: those of tables whose formulas read a
        constant that changed (the classic window does the same)."""
        validate_info_sheets(tuple(sheets.values()), self.tables)
        scoped = info_contexts(sheets.values())
        contexts, stale = {}, []
        for title, dataset in self.tables.items():
            if self.sheet_locked(("data", title)):
                continue
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
        return self.readers(stale)

    def change_info(self, sheet):
        """Store an edited Info sheet. Returns the runs to recalculate."""
        current = self.info_sheets[sheet.uid]
        if (sheet.table, sheet.fields, sheet.use_constants) != (current.table, current.fields, current.use_constants):
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

    def apply_family(self, bundle, *, prepared=None):
        """Add a finished family copy, all or nothing. Returns the navigator reference of the copied focus."""
        for title in bundle.tables:
            if title in self.tables:
                raise ValueError(f'A data table named "{title}" already exists.')
        if any(sheet.uid in self.info_sheets for sheet in bundle.infos):
            raise ValueError("An Info sheet of the copied family already exists.")
        runs_before, layouts_before = len(self.runs), len(self.layouts)
        infos_before, dirty_before = self.info_sheets, self.dirty
        try:
            self.tables.update(bundle.tables)
            if prepared is None:
                for title, dataset in bundle.tables.items():
                    self.runs.extend(self.runs_for(title, dataset))
            else:
                self.runs.extend(prepared)
            self.layouts.extend(bundle.layouts)
            if bundle.infos:
                additions = {}
                for sheet in bundle.infos:
                    if sheet.worksheet and sheet.worksheet.startswith("layout:"):
                        _, index = sheet.worksheet.split(":", 1)
                        sheet = replace(sheet, worksheet=f"layout:{layouts_before + int(index)}")
                    additions[sheet.uid] = sheet
                self.update_info_sheets(self.info_sheets | additions)
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
        tables = dict(self.tables)
        for title, dataset in self.tables.items():
            if dataset.source_link is not None:
                tables[title] = copy(dataset)
                tables[title].source_link = dataset.source_link.with_relative(path.absolute().parent)
        save_project(path, tables, layouts=self._layouts_for_save(), info_sheets=tuple(self.info_sheets.values()),
                     sheet_metadata=self.sheet_metadata)
        for title, dataset in tables.items():
            if dataset.source_link is not None:
                self.tables[title].source_link = dataset.source_link
        self.path = path
        self.dirty = False
        self.recovered_from = self.recovered_title = self.recovery_base_title = self.save_suggestion = None
        self.source_stamp = _file_stamp(path)

    def snapshot(self):
        """What a recovery copy holds, detached from the live project: data, formulas, exclusions, Info, recipes,
        confirmed styles, layouts and analysis links. Results are left out (they are recalculated as after an
        ordinary open), and so are drafts still open in the Inspector or in a dialog, which the project does not
        hold yet. Neither ``path`` nor ``dirty`` change. Cheap: frames are copied, nothing is serialised here."""
        tables = {}
        for title, dataset in self.tables.items():
            twin = copy(dataset)
            twin.raw = dataset.raw.copy(deep=True)
            twin.formulas = dict(dataset.formulas)
            twin.analyses = deepcopy(dataset.analyses)
            twin.excluded = set(dataset.excluded)
            twin.graph_styles = deepcopy(dataset.graph_styles)
            twin.info = dict(dataset.info)
            twin.analysis_ids = dict(dataset.analysis_ids)
            twin.analysis_sources = dict(dataset.analysis_sources)
            twin.analysis_labels = dict(dataset.analysis_labels)
            twin.row_heights = dict(dataset.row_heights)
            if twin.source_link is not None and self.recovery_source:
                twin.source_link = twin.source_link.with_relative(Path(self.recovery_source).absolute().parent)
            tables[title] = twin
        _persist_links(self.runs, tables, pinned=self._pinned_runs())
        return Snapshot(tables, deepcopy(self.layouts), deepcopy(tuple(self.info_sheets.values())),
                        deepcopy(self.sheet_metadata))

    # -- analysis links -------------------------------------------------------------------------
    def chain_ids(self):
        linked = {run.uid for run in self.runs if run.source is not None}
        parents = {run.source.analysis_id for run in self.runs if run.source is not None}
        return linked | parents

    def sync_links(self, *, persist=False):
        if persist:
            _persist_links(self.runs, self.tables, pinned=self._pinned_runs())

    def _pinned_runs(self):
        # View settings are addressed by run identity, including in projects with no linked analysis recipes.
        selected = {key.split(":", 1)[1] for key in self.sheet_metadata.get("sheets", {})
                    if key.split(":", 1)[0] in {"graph", "result", "saved-layout"}}
        for sheet in self.info_sheets.values():
            if sheet.worksheet:
                kind, identifier = sheet.worksheet.split(":", 1)
                if kind in {"graph", "result", "saved-layout"}:
                    selected.add(identifier)
        # A linked table reads a result by the identity of its analysis: that identity has to be saved with it.
        return selected | self.sheet_metadata.get("frozen_runs", {}).keys() | self.table_analyses()

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
        return resolve_layout_panel_graphs(run, self.runs, self.tables)

    def layout_panel_data(self, run):
        """Data of the editable graphs a saved layout draws again."""
        if not isinstance(run.options.get(LEGACY_PANEL_DATA), dict):
            return None
        return {panel: (self.tables[graph.title].frame(mask_excluded=True),
                        panel_source_style(graph.method, graph.options))
                for panel, graph in self.layout_panel_graphs(run).items()}

    def layout_figure(self, layout, *, show_empty=False):
        figures = self.layout_figures(layout)
        if figures is None:
            return None
        def label(letter):
            return qt("qt.layout_empty_preview", letter=letter)

        return compose_layout(layout.name, layout.columns, figures, paper=layout.paper, background=layout.background,
                              panel_size=layout.panel_size, axis_alignment=layout.axis_alignment,
                              tables=self.layout_table_specs(layout), empty_label=label if show_empty else None,
                              arrangement=layout.arrangement)

    # -- linked tables ----------------------------------------------------------------------------
    def table_analyses(self):
        """The identities of the analyses whose results a linked table of this project reads."""
        found = set()
        for run in self.runs:
            found |= linked_tables.source_analyses((run.style or {}).get(TABLES, ()))
        for layout in self.layouts:
            found |= linked_tables.source_analyses(layout.tables)
        return found

    def table_specs(self, records, lookup=None):
        """The linked tables ``records`` with the values they show now (or why they cannot show any)."""
        lookup = lookup or TableLookup(self)
        return tuple(TableSpec(record, linked_tables.resolve(record, lookup)) for record in records)

    def layout_table_specs(self, layout):
        return self.table_specs(layout.tables) if layout.tables else ()

    def sync_run_tables(self, run, lookup=None):
        """Make the figure of ``run`` show the linked tables of its style. True when the figure changed."""
        figure = None if run.result is None else run.result.figure
        if figure is None or self.frozen(run):
            return False
        records = (run.style or {}).get(TABLES, ())
        if not records and not getattr(figure, "_tramastat_tables_signature", ""):
            return False
        return linked_tables.sync_tables(figure, self.table_specs(records, lookup))

    def update_linked_tables(self):
        """Redraw the tables of every graph whose values or look changed; returns those runs.

        Called after every change that can alter what a table reads: a worksheet edit, an Undo, a recalculation,
        a deleted or renamed sheet. A project without linked tables does nothing."""
        if not any((run.style or {}).get(TABLES) or getattr(getattr(run.result, "figure", None),
                                                           "_tramastat_tables_signature", "")
                   for run in self.runs):
            return []
        lookup = TableLookup(self)
        return [run for run in self.runs if self.sync_run_tables(run, lookup)]

    def linked_table_report(self):
        """``(owner, record, resolved)`` of every linked table of the project: the owner is ``("graph", run)`` or
        ``("layout", index)``. A reading aid for the window and for tests; nothing is calculated."""
        lookup, report = TableLookup(self), []
        for run in self.runs:
            for record in (run.style or {}).get(TABLES, ()):
                report.append((("graph", run), record, linked_tables.resolve(record, lookup)))
        for index, layout in enumerate(self.layouts):
            for record in layout.tables:
                report.append((("layout", index), record, linked_tables.resolve(record, lookup)))
        return report

    def table_source_choices(self):
        """Everything a linked table can read: every worksheet and every result table that exists now."""
        choices = [{"kind": "sheet", "sheet": title, "label": title, "rows": len(dataset.raw),
                    "columns": len(dataset.columns)} for title, dataset in self.tables.items()]
        for run in self.runs:
            if run.result is None or run.calculation_error:
                continue
            for name, frame in run.result.tables.items():
                if len(frame) and len(frame.columns):
                    choices.append({"kind": "result", "analysis": run.uid, "table": name,
                                    "label": f"{run.name} · {name}", "rows": len(frame), "columns": len(frame.columns)})
        return choices

    def table_source_preview(self, choice, rows=200, columns=40):
        """``(row labels, column labels, cells)`` of the top left corner of a source, for the range picker."""
        found = self._lookup_choice(TableLookup(self), choice)
        frame = found.frame
        top = min(len(frame), rows)
        left = min(len(frame.columns), columns)
        row_labels = [str(row + 1) if choice["kind"] == "sheet" or not found.labelled else found.row_label(row)
                      for row in range(top)]
        return (row_labels, [str(name) for name in frame.columns[:left]],
                [[found.text(row, column) for column in range(left)] for row in range(top)])

    @staticmethod
    def _lookup_choice(lookup, choice):
        found = (lookup.sheet(choice["sheet"]) if choice["kind"] == "sheet"
                 else lookup.result(choice["analysis"], choice["table"]))
        if isinstance(found, Problem):
            raise ValueError(found.detail or found.state)
        return found

    def table_record(self, choice, box, *, mode="linked", position=(.05, .05), size=linked_tables.DEFAULT_SIZE,
                     headers=None, orientation="normal", grid=True, font=None, record_id=None):
        """A linked table record for the rectangle ``box`` = (top, left, bottom, right), 0-based positions in the
        data rows and columns of the source ``choice`` (see ``table_source_choices``).

        The size of the range is checked before any cell is read. A linked record holds only the reference
        (worksheet row identities; analysis identity, result table and row and column keys); a copy holds the text
        the cells show now. Raises ``ValueError`` for an empty or too large range or a source that cannot be read."""
        top, left, bottom, right = box
        linked_tables.check_size(bottom - top + 1, right - left + 1)
        lookup = TableLookup(self)
        found = self._lookup_choice(lookup, choice)
        frame = found.frame
        if top < 0 or left < 0 or bottom >= len(frame) or right >= len(frame.columns):
            raise ValueError(tr("linked_table.error.outside"))
        names = [str(name) for name in frame.columns]
        columns = names[left:right + 1]
        if any(names.count(name) != 1 for name in columns):
            raise ValueError(tr("linked_table.error.repeated_columns"))
        rows = list(range(top, bottom + 1))
        if choice["kind"] == "sheet":
            source = {"kind": "sheet", "sheet": choice["sheet"], "rows": linked_tables.row_tokens(
                self.tables[choice["sheet"]].raw, rows), "columns": columns}
            origin = choice["label"]
        else:
            labels = [found.row_label(row) for row in range(len(frame))] if found.labelled else []
            keyed = found.labelled and all(labels.count(labels[row]) == 1 for row in rows)
            source = {"kind": "result", "analysis": choice["analysis"], "table": choice["table"],
                      "rows": [labels[row] for row in rows] if keyed else rows,
                      "by": "keys" if keyed else "position", "columns": columns}
            if not keyed:
                source["rows_total"] = len(frame)
            origin = choice["label"]
        first = (source["rows"][0] if choice["kind"] == "result" and keyed else str(top + 1))
        origin = f"{origin}: {first}{'…' if len(rows) > 1 else ''} / {columns[0]}{'…' if len(columns) > 1 else ''}"
        record = {"id": record_id or linked_tables.new_id(), "mode": "linked", "source": source,
                  "position": list(position), "size": float(size), "orientation": orientation, "grid": grid,
                  "headers": headers or ("both" if len(rows) * len(columns) > 1 else "none"),
                  "origin": origin[:200]}
        if font:
            record["font"] = font
        if mode == "copy":
            resolved = linked_tables.resolve(record, lookup)
            if not resolved.ok:
                raise ValueError(resolved.detail or resolved.state)
            record.pop("source")
            record["mode"] = "copy"
            record["values"] = {"rows": list(resolved.row_labels), "columns": list(resolved.column_labels),
                                "cells": [list(line) for line in resolved.cells]}
        return linked_tables.validate_table(record)

    def layout_runs(self, layout):
        by_reference = {run.reference: run for run in self.runs}
        return [by_reference[reference] for reference in layout.panels if reference in by_reference]

    # -- joins ----------------------------------------------------------------------------------------
    def readers(self, titles):
        """The runs that read the worksheets ``titles``: their analyses and the joins that read them on the right."""
        titles = set(titles)
        return [run for run in self.runs if run.title in titles and run.source is None
                or run.method == worksheet_join.METHOD and worksheet_join.right_title(run.options) in titles]

    # -- recalculation --------------------------------------------------------------------------
    def plan_refresh(self, seeds):
        """Everything a worker needs to recalculate ``seeds`` and every analysis that reads them."""
        graph = self.analysis_graph()
        live = {run.uid: run for run in self.runs}
        unavailable = {run.uid for run in self.runs if run.result is None or run.calculation_error}
        selected = graph.affected([run.uid for run in seeds], unavailable=unavailable,
                                  blocked=self.sheet_metadata.get("frozen_runs", {}))
        cached = {run.uid: run.result for run in self.runs
                  if run.result is not None and not run.calculation_error and run.uid not in selected}
        frames, roots, clones, pairwise, layout_data, joins = {}, {}, {}, {}, {}, {}
        for identifier in selected:
            run = live[identifier]
            clone = clones[identifier] = copy(run)
            clone.options, clone.style = deepcopy(run.options), deepcopy(run.style)
            pairwise[identifier] = self.pairwise_snapshot(run)
            layout_data[identifier] = self.layout_panel_data(run)
            if run.method == worksheet_join.METHOD:
                joins[identifier] = self.join_data(run)
            if run.source is None:
                if run.title not in frames:
                    frames[run.title] = self.tables[run.title].frame(mask_excluded=True)
                roots[identifier] = frames[run.title]
        return RefreshJob(graph, selected, roots, cached, clones, pairwise, layout_data, CalculationControl(), joins)

    @staticmethod
    def run_refresh(job):
        """Worker side: calculate without touching runs or confirmed results."""
        references = {clone.reference: identifier for identifier, clone in job.clones.items()}
        fresh = dict(job.cached)
        job.control.report(0, len(job.selected))
        # The engine calculation of the root runs needs only their worksheet (a join, which also reads its
        # right worksheet, stays here). Comparisons and downstream tables are applied in dependency order.
        prepared = precompute_analyses(
            [(identifier, job.clones[identifier].method, frame, job.clones[identifier].options)
             for identifier, frame in job.roots.items()
             if job.layout_data[identifier] is None and identifier not in job.join_data],
            cancel=job.control.cancel,
        )

        def calculate(identifier, frame):
            outcome = prepared.get(identifier)
            if outcome is not None and outcome.error is not None:
                raise outcome.error
            snapshot = job.pairwise[identifier]
            if snapshot and (source := references.get(snapshot.get("key"))) in fresh:
                snapshot = {**snapshot, "tables": fresh[source].tables}
            options = {"control": job.control, "layout_data": job.layout_data[identifier], "pairwise": snapshot}
            if identifier in job.join_data:
                options["join_data"] = job.join_data[identifier]
            if outcome is not None:
                options["result"] = outcome.value
            return compute(job.clones[identifier], frame.copy(deep=True), **options)

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
        self.update_linked_tables()
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
    def graph_type_problem(self, run):
        """Only native graphs with an editable recipe can be converted in place."""
        if self.frozen(run):
            return qt("qt.sheet_frozen_notice")
        dataset = self.tables.get(run.title)
        if (dataset is None or stored_legacy_view(dataset) or run.method in LEGACY_GRAPH_METHODS
                or LEGACY_GRAPH_LINK in run.options or LEGACY_PREVIEW in run.options):
            return qt("qt.graph_type_read_only")
        if run.method not in GRAPH_TYPE_METHODS or run.slot < 0:
            return qt("qt.graph_type_requires_graph_recipe")
        return None

    def candidate(self, title, method, options, *, index=None, source=None, graph_type=False):
        """The Run a dialog asks for: a new analysis, or the edit of ``runs[index]`` keeping its identity."""
        if method == SELECT_TRANSFORM:
            options = seeded_transform_options(options)
        if index is None:
            dataset = self.tables[title]
            if source is None and len(dataset.analyses) - len(dataset.analysis_sources) >= 256:
                raise ValueError("A table supports up to 256 analyses.")
            if len(self.runs) >= MAX_ANALYSIS_NODES:
                raise ValueError(tr("chain.node_budget"))
            return Run(method, title, options, source=source)
        run = self.runs[index]
        if self.frozen(run):
            raise ValueError(qt("qt.sheet_frozen_notice"))
        options = dict(options)
        converted = graph_type and method != run.method
        if graph_type:
            problem = self.graph_type_problem(run)
            if problem:
                raise ValueError(problem)
            if method not in GRAPH_TYPE_METHODS:
                raise ValueError(qt("qt.graph_type_requires_graph_recipe"))
        if method == run.method:
            for key in (LEGACY_TITLE, LEGACY_NOTES, LEGACY_GRAPH_LINK, PAIRWISE_SECTION, SAVED_REPLICATE_DISPLAY,
                        PCA_OVERLAY_APPEARANCE, PCA_SAVED_DIRECTIONS, PCA_SAVED_VIEWPORT, PCA_PARALLEL_ARCHIVE,
                        KMEANS_ARCHIVE, FIT_GRAPH_SPEC, FIT_INTERVAL_BAND, PADE_DRAWING, SURVIVAL_GRAPH, QC_REFERENCE,
                        anova_grouped_plot.PRIMARY, OBSERVATION_COLUMNS):
                if key in run.options:
                    options[key] = run.options[key]
            if options.get("Model") == run.options.get("Model"):
                for key in (FIXED_COEFFICIENTS, STARTING_COEFFICIENTS, STARTING_COEFFICIENTS_BY_SERIES):
                    if key in run.options and key not in options:
                        options[key] = run.options[key]
            if options.get("Group") == run.options.get("Group") and "Group order" in run.options:
                options["Group order"] = run.options["Group order"]
            if method == XY_METHOD:
                options = retain_recipe_options(options, run.options)
                options["Series color"] = assign_colors(options.get("Y columns") or [], options.get("Series color"))
        if method != run.method and not converted and any(run.reference in layout.panels for layout in self.layouts):
            raise ValueError("Change parameters for this method or create a new analysis for the layout.")
        style = run.style
        if converted:
            for key in (LEGACY_TITLE, LEGACY_NOTES, PAIRWISE_SECTION):
                if key in run.options:
                    options[key] = deepcopy(run.options[key])
            # Only keep drawings in plot fractions. Data coordinates and axis formatting belong to the old type.
            previous_style = style or {}
            style = {key: deepcopy(previous_style[key]) for key in (*TRANSFERABLE, "title") if key in previous_style}
            for key in (ANNOTATIONS, SHAPES):
                records = [record for record in previous_style.get(key, ()) if record["units"] == "axes"]
                if records:
                    style[key] = deepcopy(records)
            if previous_style.get(TABLES):  # Placed on the figure and read by the analysis identity, which stays.
                style[TABLES] = deepcopy(previous_style[TABLES])
            style = style or None
        elif method == run.method == FREQUENCY:
            style = frequency_style(style, run.options, options)
        elif method == run.method == ECDF_GRAPH:
            style = ecdf_style(style, run.options, options)
        elif method == run.method == INTERACTION_PLOT:
            style = interaction_style(style, run.options, options)
        elif method == run.method == RAINCLOUD_PLOT:
            style = raincloud_style(style, run.options, options)
        elif method == run.method == "Kaplan–Meier survival":
            style = survival_style(style, run.options, options)
        elif method == run.method == XY_METHOD:
            style = xy_style(style, options)
        candidate = Run(method, run.title, options, slot=run.slot, style=style, uid=run.uid, source=run.source,
                        label=run.label)
        if candidate.source is not None or self.chain_ids():
            self.analysis_graph(replacement=(index, candidate))
        return candidate

    def add_result(self, run, result, index=None, *, graph_type=False):
        """Confirm a calculated candidate. Returns its index and the analyses that read it."""
        previous = self.runs[index] if index is not None else None
        converted = graph_type and previous is not None and run.method != previous.method
        if converted:
            self._check_graph_type_result(previous, result)
        run.result, run.calculation_error = result, None
        dataset = self.tables[run.title]
        recipes = dataset.analyses
        dependents = []
        if index is None:
            run.slot = len(recipes)
            self.runs.append(run)
            recipes.append((run.method, run.options))
            index = len(self.runs) - 1
        else:
            if previous.uid == run.uid and not converted:
                run.shape_history = previous.shape_history  # Same graph, same drawings: keep its Undo steps.
            self.runs[index] = run
            recipes[run.slot] = run.method, run.options
            if converted:
                dataset.analysis_ids[run.slot] = run.uid
                if run.style is None:
                    dataset.graph_styles.pop(run.slot, None)
                else:
                    dataset.graph_styles[run.slot] = run.style
            dependents = [other for other in self.runs if other is not run and (
                (other.source is not None and other.source.analysis_id == previous.uid)
                or (read_pairwise(other.options)[0] or {}).get("slot") == run.slot and other.title == run.title)]
        self.dirty = True
        self.sync_links(persist=True)
        self.update_linked_tables()
        return index, dependents

    def _check_graph_type_result(self, previous, result):
        """Keep the original graph until the new figure and any linked result tables are usable."""
        if result.figure is None:
            raise ValueError(qt("qt.graph_type_missing_figure"))
        tables = {run.source.table for run in self.runs
                  if run.source is not None and run.source.analysis_id == previous.uid}
        for table in sorted(tables):
            message = qt("qt.graph_type_linked_result", name=table)
            try:
                columns = result_frame(result, table).columns
                before = result_frame(previous.result, table).columns if previous.result is not None else ()
            except ValueError as error:
                raise ValueError(message) from error
            if not set(before).issubset(columns):
                raise ValueError(message)

    # -- layouts --------------------------------------------------------------------------------------
    def layout_candidates(self, current=None):
        return [run for index, run in enumerate(self.runs)
                if (not self.sheet_state(("graph", index)).get("hidden")
                    and run.result is not None and run.result.figure is not None)
                or (current is not None and run.reference in current.panels)]

    def put_layout(self, layout, key=None, *, family=None):
        if key is None:
            if len(self.layouts) >= 128:
                raise ValueError(ui("A project supports up to 128 layouts."))
            self.layouts.append(layout)
            key = len(self.layouts) - 1
        else:
            current = self.layouts[key]
            if current == layout:
                return key
            if family is not None:
                bundle, runs = family
                self.apply_family(bundle, prepared=runs)
            self.history.record_layout(key, current, layout, family=family)
            self.layouts[key] = layout
        self.dirty = True
        return key

    # -- export ---------------------------------------------------------------------------------------
    def imported_vector_format(self, run):
        """The available vector export format for a recovered drawing."""
        preview = run.options.get(LEGACY_PREVIEW)
        fmt = preview.get("format") if isinstance(preview, dict) else None
        if run.method in {SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT} and fmt in ("emf", "pdf"):
            return fmt
        dataset = self.tables.get(run.title)
        style = run.options.get(LEGACY_GRAPH_STYLE)
        if (run.method == SAVED_EDITABLE_GRAPH and fmt == "emf" and dataset is not None
                and isinstance(style, dict)
                and (dataset.table_format in {EDITABLE_LEGACY_EMF, EDITABLE_LEGACY_COLUMNS} or LIMIT_SOURCE in style)):
            return fmt
        return None

    def export_imported_vector(self, run, path, *, current_layout=False):
        from analisi.legacy_binary_graphs import export_binary_graph
        from analisi.legacy_layout_edit import edit_panel_artwork, export_edited_layout

        options = run.options
        preview = options[LEGACY_PREVIEW]
        if current_layout:
            export_edited_layout(path, preview, options.get(LEGACY_EDITABLE_PANELS),
                                 options.get(LEGACY_PANEL_EDITS), self.layout_panel_data(run))
            return
        if run.method == SAVED_EDITABLE_GRAPH:
            frame = self.tables[run.title].frame(mask_excluded=True)
            preview = edit_panel_artwork(frame, options[LEGACY_GRAPH_STYLE], preview)
        export_binary_graph(path, preview, layout=run.method == SAVED_BINARY_LAYOUT)

    def set_linked_graph_views(self, views):
        used = {link for layout in self.layouts for _, link in layout.graph_links}
        changed = False
        for link, view in views.items():
            if link in used and view != self.linked_graph_views.get(link):
                self.linked_graph_views.pop(link, None)
                self.linked_graph_views[link] = view
                changed = True
        while len(self.linked_graph_views) > 24:
            self.linked_graph_views.pop(next(iter(self.linked_graph_views)))
        return changed

    def _layouts_for_save(self):
        from analisi.layout_picture import capture_picture

        pictures = {}
        layouts = []
        for layout in self.layouts:
            if not layout.graph_links:
                layouts.append(layout)
                continue
            links = dict(layout.graph_links)
            records = []
            for slot, *picture in layout.arrangement.pictures:
                link = links.get(slot)
                view = self.linked_graph_views.get(link)
                if view is not None and view.figure is not None:
                    clear = slot in layout.arrangement.clear_backgrounds
                    key = (link, clear)
                    if key not in pictures:
                        pictures[key] = capture_picture(view.figure, clear_background=clear)
                    picture = pictures[key]
                records.append((slot, *picture))
            layouts.append(replace(layout, arrangement=replace(layout.arrangement, pictures=tuple(records))))
        return layouts

    def layout_link_issues(self, layout):
        problems = []
        for slot, link in layout.graph_links:
            view = self.linked_graph_views.get(link)
            message = view.error if view is not None else qt("qt.layout_link_checking")
            if message:
                problems.append(qt("qt.layout_link_status", panel=chr(ord("A") + slot),
                                   file=Path(link.path).name, error=message))
        return problems

    def layout_figures(self, layout):
        """One figure per panel, including empty slots. None for the page means a graph is still missing."""
        by_reference = {run.reference: run for run in self.runs}
        links = dict(layout.graph_links)
        figures = []
        for index, reference in enumerate(layout.panels):
            if reference is None:
                view = self.linked_graph_views.get(links.get(index))
                if view is not None and view.figure is not None:
                    figures.append(view.figure)
                elif (picture := layout.arrangement.picture(index)) is None:
                    figures.append(EMPTY_PANEL)
                else:
                    from analisi.layout_picture import picture_figure
                    figures.append(picture_figure(picture, transparent=index in layout.arrangement.clear_backgrounds))
            else:
                run = by_reference.get(reference)
                if run is None or run.result is None or run.result.figure is None:
                    return None
                figures.append(run.result.figure)
        return tuple(figures)

    def layout_panel_figures(self, layout):
        figures = self.layout_figures(layout)
        if figures is None:
            raise ValueError(ui("Recalculate the layout panels before exporting the layout."))
        if any(run.calculation_error for run in self.layout_runs(layout)):
            raise ValueError(tr("reference.stale_export"))
        if problems := self.layout_link_issues(layout):
            raise ValueError(problems[0])
        return figures

    def layout_pdf_page(self, layout):
        from analisi.layout_pdf import PdfLayoutPage
        return PdfLayoutPage(layout.name, layout.columns, self.layout_panel_figures(layout), layout.paper,
                             layout.background, layout.panel_size, layout.axis_alignment,
                             self.layout_table_specs(layout), layout.arrangement)

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
                              paper=layout.paper, background=layout.background, panel_size=layout.panel_size,
                              axis_alignment=layout.axis_alignment, tables=self.layout_table_specs(layout),
                              arrangement=layout.arrangement)
        else:
            background = WHITE if settings.get("transparent") else layout.background
            figure = compose_layout(layout.name, layout.columns, self.layout_panel_figures(layout),
                                    paper=layout.paper, background=background, panel_size=layout.panel_size,
                                    axis_alignment=layout.axis_alignment, tables=self.layout_table_specs(layout),
                                    arrangement=layout.arrangement)
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
        if self.frozen(run):
            return qt("qt.sheet_frozen_notice")
        if run.method == SAVED_BINARY_GRAPH:
            return ui("Use Open editable graph when available, or export the original drawing in its saved "
                      "vector format.")
        if run.method == SAVED_EDITABLE_GRAPH and (
                self.tables[run.title].table_format in EDITABLE_LEGACY_FIXED_VALUES or LEGACY_PREVIEW in run.options):
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

    def record_shapes(self, run, style):
        """One step of the graph's drawing history when ``style`` changes its shapes."""
        before_pos = run.shape_history.position
        before_len = len(run.shape_history.changes)
        run.shape_history.record((run.style or {}).get(SHAPES, []), (style or {}).get(SHAPES, []))
        if run.shape_history.position != before_pos or len(run.shape_history.changes) != before_len:
            seqs = getattr(run.shape_history, "_trama_seqs", None)
            if seqs is None:
                seqs = run.shape_history._trama_seqs = [0] * max(0, len(run.shape_history.changes) - 1)
            del seqs[before_pos:]
            seqs.append(self.history.next_seq())
            if len(seqs) > len(run.shape_history.changes):
                del seqs[:-len(run.shape_history.changes)]

    def commit_style(self, run, style, *, record_shapes=True):
        """Store a style already drawn on the figure (the Inspector and the canvas tools preview it first)."""
        if record_shapes:
            self.record_shapes(run, style)
        run.style = style
        run.result.style_warning = graph_warning(run.result.figure, style)
        self.tables[run.title].graph_styles[run.slot] = style
        sync_letters_table(run.result)
        self.dirty = True

    def _apply_style_updates(self, targets, styles_by_uid):
        """Validate every target figure first, then redraw all of them with full rollback on error."""
        for uid, run in targets:
            problem = self.graph_format_problem(run)
            if problem:
                raise ValueError(problem)
            candidate = {} if styles_by_uid[uid] is None else styles_by_uid[uid]
            validate_graph_style(run.result.figure.axes[0], candidate)
        applied = []
        try:
            for uid, run in targets:
                previous = deepcopy(run.style)
                target = styles_by_uid[uid]
                applied.append((run, previous))
                apply_style(run.result.figure, deepcopy(target or {}))
        except Exception:
            for prev_run, prev_style in reversed(applied):
                try:
                    apply_style(prev_run.result.figure, deepcopy(prev_style or {}))
                except Exception:
                    pass
            raise
        for uid, run in targets:
            target = deepcopy(styles_by_uid[uid])
            run.style = target
            run.result.style_warning = graph_warning(run.result.figure, target)
            if target is None:
                self.tables[run.title].graph_styles.pop(run.slot, None)
            else:
                self.tables[run.title].graph_styles[run.slot] = target
            sync_letters_table(run.result)
        self.update_linked_tables()
        self.sync_links(persist=True)

    def commit_style_batch(self, selected_uids, preset, *, expected=None, label="Apply figure style to graphs"):
        """Apply ``preset`` atomically to ``selected_uids`` as one undoable project transaction.

        Zero effective changes leave the project clean with no new history entry. If any target
        changed, fails validation or fails while drawing, all confirmed styles stay untouched.
        """
        by_uid = {run.uid: run for run in self.runs}
        ids = list(selected_uids)
        styles_by_id = {}
        seen = set()
        for uid in ids:
            if uid in seen:
                raise ValueError("A graph was selected more than once.")
            seen.add(uid)
            run = by_uid.get(uid)
            if run is None:
                raise ValueError("One or more graphs changed while the dialog was open. Nothing was applied."
                                 if expected is not None else "A selected graph is no longer available.")
            if expected is not None:
                snapshot = expected.get(uid)
                if snapshot is None:
                    raise ValueError("One or more graphs changed while the dialog was open. Nothing was applied.")
                exp_run, exp_result, exp_figure, exp_style = snapshot
                cur_figure = run.result.figure if run.result is not None else None
                if (run is not exp_run or run.result is not exp_result or cur_figure is not exp_figure
                        or (run.style or {}) != exp_style or run.calculation_error):
                    raise ValueError("One or more graphs changed while the dialog was open. Nothing was applied.")
            if run.calculation_error:
                raise ValueError("Recalculate the graph first.")
            problem = self.graph_format_problem(run)
            if problem:
                raise ValueError(problem)
            styles_by_id[uid] = run.style
        planned = plan_preset_batch(styles_by_id, ids, preset)
        changed_uids = tuple(planned.keys())
        unchanged_uids = tuple(uid for uid in ids if uid not in planned)
        if not changed_uids:
            return BatchStyleOutcome(preset["name"], tuple(ids), (), unchanged_uids)
        targets = [(uid, by_uid[uid]) for uid in changed_uids]
        before = {uid: deepcopy(run.style) for uid, run in targets}
        after = {uid: deepcopy(planned[uid]) for uid, _ in targets}
        self._apply_style_updates(targets, after)
        self.history.record_style_batch(label, before, after)
        self.dirty = True
        return BatchStyleOutcome(preset["name"], tuple(ids), changed_uids, unchanged_uids)

    def apply_format(self, run, style, *, xy_update=None, xy_result=None):
        if run.method == XY_METHOD and xy_update is not None:
            run.options = xy_update
            run.result = xy_result
            self.tables[run.title].analyses[run.slot] = (run.method, run.options)
        else:
            apply_style(run.result.figure, style)
        self.record_shapes(run, style)
        run.style = style
        run.result.style_warning = graph_warning(run.result.figure, style)
        self.tables[run.title].graph_styles[run.slot] = style
        sync_letters_table(run.result)
        self.sync_run_tables(run)
        self.sync_links(persist=True)
        self.dirty = True

    def change_graph_style_option(self, run, key, value, label):
        """Store a single drawing-style edit in the figure-style history."""
        style = deepcopy(run.style or {})
        if value:
            style[key] = value
        else:
            style.pop(key, None)
        if style == (run.style or {}):
            return False
        before = {run.uid: deepcopy(run.style)}
        after = {run.uid: style}
        self._apply_style_updates([(run.uid, run)], after)
        self.history.record_style_batch(label, before, deepcopy(after))
        self.dirty = True
        return True

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
        if self.sheet_locked(("data", title)):
            raise ValueError(qt("qt.sheet_frozen_notice"))
        if stored_legacy_view(dataset):
            raise ValueError("Select a source table or use Result as Data to create an editable table.")
        return dataset

    def can_reorder_rows(self, title):
        return (title in self.tables and not self.sheet_locked(("data", title))
                and reorder_rows_allowed(self.tables[title]))

    def edit(self, title, label, change):
        """Apply ``change`` to a copy of the table, keep it with undo, and return the analyses to recalculate."""
        dataset = self.editable(title)
        candidate = copy(dataset)
        change(candidate)
        if (len(candidate.raw.columns) > len(dataset.raw.columns)
                and candidate.raw.attrs.get(COLUMN_IDS) == dataset.raw.attrs.get(COLUMN_IDS)):
            # Pasting a block or filling a numeric series can also create source columns.
            names = candidate.raw.columns.difference(dataset.raw.columns, sort=False)
            store_column_ids(candidate.raw, column_ids_after_insertion(dataset.raw, *names))
        added_rows = len(candidate.raw) - len(dataset.raw)
        if added_rows > 0 and candidate.raw.attrs.get(ROW_SPANS) == dataset.raw.attrs.get(ROW_SPANS):
            candidate.raw.attrs[ROW_SPANS] = after_insertion(dataset.raw, len(dataset.raw), added_rows)
        if candidate.formulas:
            candidate.frame()  # A formula that no longer evaluates rejects the edit.
        before = WorksheetState.capture(dataset)
        dataset.raw, dataset.formulas, dataset.excluded = candidate.raw, candidate.formulas, candidate.excluded
        dataset.column_order = candidate.column_order
        dataset.cell_backgrounds = candidate.cell_backgrounds
        dataset.number_formats = candidate.number_formats
        dataset.row_heights = candidate.row_heights
        dataset.text_styles = candidate.text_styles
        dataset.source_link = candidate.source_link
        dataset.worksheet_titles = candidate.worksheet_titles
        after = WorksheetState.capture(dataset)
        if not self.history.record(title, label, before, after):
            return None
        self.dirty = True
        self.update_linked_tables()
        return self.table_runs(title)

    def set_row_heights(self, title, rows, height):
        """Presentation-only: change or reset row heights with undo and zero recalculations."""
        if self.sheet_locked(("data", title)):
            raise ValueError(qt("qt.sheet_frozen_notice"))
        dataset = self.tables[title]
        if stored_legacy_view(dataset):
            raise ValueError("Select a source table or use Result as Data to create an editable table.")
        rows = tuple(dict.fromkeys(rows))
        if not rows or any(type(row) is not int or not 0 <= row < len(dataset.raw) for row in rows):
            raise ValueError(qt("qt.rows_virtual_or_invalid"))
        before = WorksheetState.capture(dataset)
        dataset.set_row_heights(rows, height)
        return self._record_background(title, dataset, before, "Row height")

    def set_table_background(self, title, box, color):
        if self.sheet_locked(("data", title)):
            raise ValueError(qt("qt.sheet_frozen_notice"))
        dataset = self.tables[title]
        before = WorksheetState.capture(dataset)
        dataset.set_background(box, color)
        return self._record_background(title, dataset, before)

    def set_result_background(self, title, slot, name, box, shape, color):
        dataset = self.tables[title]
        before = WorksheetState.capture(dataset)
        dataset.set_result_background(slot, name, box, shape, color)
        return self._record_background(title, dataset, before)

    def set_table_text_style(self, title, box, changes):
        """Text of the cells in ``box``: display only, so no analysis is recalculated. One undoable step.

        ``changes=None`` restores the text of the cells (their font, size, colour, style and alignment) and
        leaves backgrounds and number formats alone. False when nothing changed."""
        if self.sheet_locked(("data", title)):
            raise ValueError(qt("qt.sheet_frozen_notice"))
        dataset = self.tables[title]
        before = WorksheetState.capture(dataset)
        if changes is None:
            dataset.clear_text_style(box)
        else:
            dataset.set_text_style(box, changes)
        return self._record_background(title, dataset, before, "Text format")

    def set_result_text_style(self, title, slot, name, box, shape, changes):
        dataset = self.tables[title]
        before = WorksheetState.capture(dataset)
        dataset.set_result_text_style(slot, name, box, shape, changes)
        return self._record_background(title, dataset, before, "Text format")

    def _record_background(self, title, dataset, before, label="Cell background"):
        if self.history.record(title, label, before, WorksheetState.capture(dataset)):
            self.dirty = True
            return True
        return False

    def worksheet_title_graphs(self, title):
        return [run for run in self.table_runs(title) if run.method == XY_METHOD and run.source is None]

    def set_worksheet_titles(self, title, settings):
        dataset = self.editable(title)
        before = WorksheetState.capture(dataset)
        dataset.worksheet_titles = settings
        return self._record_background(title, dataset, before, qt("qt.format_data_table"))

    def worksheet_replicate_limits(self, title):
        dataset = self.tables[title]
        groups = xy_replicate_groups(dataset.raw, dataset.table_format)
        if not groups or dataset.source_link is not None:
            return None
        current = len(groups[0][1])
        fixed = len(dataset.columns) - len(groups) * current
        max_width = min(MAX_COLUMNS, MAX_CELLS // max(1, len(dataset.raw)))
        return current, max(current, min(256, (max_width - fixed) // len(groups)))

    def worksheet_x_error(self, title):
        """Return the editable X block, or None if the worksheet has no explicit X column."""
        dataset = self.tables[title]
        if dataset.source_link is not None or any(key.startswith("legacy_") for key in dataset.raw.attrs):
            return None
        roles = xy_source_roles(dataset.raw, dataset.table_format)
        if roles and len(roles["x"]) in (1, 2):
            x = roles["x"][0]
            error = roles["x"][1] if len(roles["x"]) == 2 else None
            if x in dataset.raw and (error is None or
                                    (error in dataset.raw and
                                     dataset.columns.index(error) == dataset.columns.index(x) + 1)):
                return x, error
        return None

    def set_worksheet_xy_structure(self, title, count, settings, *, x_error=None):
        """Update an XY worksheet's structure as one undoable edit."""
        dataset = self.editable(title)
        raw = dataset.raw
        removed = []
        additions = {}
        x_block = self.worksheet_x_error(title)
        if count is not None:
            limits = self.worksheet_replicate_limits(title)
            if limits is None or type(count) is not int or not 2 <= count <= limits[1] or count == limits[0]:
                raise ValueError(qt("qt.replicate_count_unavailable"))
            for group, members in xy_replicate_groups(raw, dataset.table_format):
                removed.extend(members[count:])
                if count > len(members):
                    additions[members[-1]] = [f"{group} [{index}]" for index in range(len(members) + 1, count + 1)]
        if x_error is not None:
            if x_block is None or bool(x_block[1]) == x_error:
                raise ValueError(qt("qt.x_error_unavailable"))
            x, existing = x_block
            if x_error:
                additions[x] = [f"{x} [Error]"]
            else:
                removed.append(existing)
        for name in removed:
            if raw[name].notna().any():
                key = "qt.x_error_not_empty" if x_block and name == x_block[1] else "qt.replicate_not_empty"
                raise ValueError(qt(key, column=name))
        self._check_column_rename(title, removed)

        added = [name for names in additions.values() for name in names]
        width = len(dataset.columns) + len(added) - len(removed)
        if width > MAX_COLUMNS or width * len(raw) > MAX_CELLS:
            raise ValueError(qt("qt.table_structure_limit"))
        if set(added) & set(dataset.columns):
            raise ValueError(qt("qt.table_column_collision"))
        dropped = set(removed)

        def ordered(names):
            return [column for name in names if name not in dropped for column in (name, *additions.get(name, ()))]

        def change(candidate):
            raw_order = ordered(raw.columns)
            frame = raw.reindex(columns=raw_order)
            frame.attrs = dict(raw.attrs)
            for name in added:
                frame[name] = pd.Series(pd.NA, index=frame.index, dtype="Float64")
            keep_source_columns(frame)
            ids = column_ids_after_insertion(raw, *added)
            store_column_ids(frame, ids)
            roles = (xy_source_roles(raw, dataset.table_format) if x_error is not None
                     else raw.attrs.get("worksheet_roles"))
            if roles is not None:
                frame.attrs["worksheet_roles"] = {"x": ordered(roles["x"]), "y": [ordered(group) for group in roles["y"]]}
            indices = {name: column for column, name in enumerate(raw_order)}
            candidate.excluded = {(row, indices[raw.columns[column]]) for row, column in dataset.excluded
                                  if raw.columns[column] not in dropped}
            candidate.raw = frame
            if dataset.column_order is not None:
                candidate.column_order = tuple(ordered(dataset.column_order))
            candidate.cell_backgrounds = {cell: color for cell, color in dataset.cell_backgrounds.items()
                                          if cell[1] not in dropped}
            candidate.number_formats = {name: spec for name, spec in dataset.number_formats.items()
                                        if name not in dropped}
            candidate.text_styles = dataset.text_styles.drop(removed)
            dropped_ids = {ids[name] for name in removed}
            captions = {token: text for token, text in settings.columns.items() if token not in dropped_ids}
            for previous, names in additions.items():
                if ids[previous] in captions:
                    for name in names:
                        captions[ids[name]] = captions[ids[previous]]
            individual = {token: text for token, text in settings.individual.items() if token not in dropped_ids}
            candidate.worksheet_titles = replace(settings, columns=captions, individual=individual)

        return self.edit(title, qt("qt.format_data_table"), change)

    def set_table_number_format(self, title, names, spec):
        """Display-only: no analysis is recalculated. One undoable step; False when nothing changed."""
        if self.sheet_locked(("data", title)):
            raise ValueError(qt("qt.sheet_frozen_notice"))
        dataset = self.tables[title]
        before = WorksheetState.capture(dataset)
        dataset.set_number_format(names, spec)
        changed = self._record_background(title, dataset, before, "Number format")
        self.update_linked_tables()  # A table linked to these cells shows them as the grid does.
        return changed

    def set_result_number_format(self, title, slot, name, positions, spec):
        dataset = self.tables[title]
        before = WorksheetState.capture(dataset)
        dataset.set_result_number_format(slot, name, positions, spec)
        changed = self._record_background(title, dataset, before, "Number format")
        self.update_linked_tables()
        return changed

    def table_runs(self, title):
        affected = self.readers([title])
        if any(isinstance(run.options.get(LEGACY_GRAPH_LINK), str) for run in affected):
            affected.extend(linked_panel_readers(title, self.runs, self.tables))
        return affected

    def paste(self, title, top, left, rows, label="Paste"):
        return self.edit(title, label, lambda dataset: paste_block(dataset, top, left, rows))

    def edit_cell(self, title, row, column, text):
        return self.edit(title, "Edit cell", lambda dataset: edit_cell_value(dataset, row, column, text))

    def clear(self, title, selection):
        return self.edit(title, "Clear cells", lambda dataset: clear_block(dataset, selection))

    def create_numeric_series(self, title, plan_or_start_row, column=None, *, mode=None,
                              start_text=None, count=None, step_text=None, confirm_replace=False):
        dataset = self.editable(title)
        if isinstance(plan_or_start_row, NumericSeriesPlan):
            plan = plan_or_start_row
        else:
            plan = plan_numeric_series(
                dataset,
                plan_or_start_row,
                column,
                mode=mode,
                start_text=start_text,
                count=count,
                step_text=step_text,
                locked=self.sheet_locked(("data", title)),
                read_only=stored_legacy_view(dataset),
            )
        if plan.occupied_count > 0 and not confirm_replace:
            raise ValueError(series_text("err.confirm_required"))
        return self.edit(title, "Create numeric series", lambda candidate: apply_numeric_series(candidate, plan))

    def insert_rows(self, title, position, count=1):
        def change(dataset):
            raw = dataset.raw
            at = max(0, min(position, len(raw)))
            grown = grow_rows(raw, len(raw) + count)
            order = [*range(at), *range(len(raw), len(raw) + count), *range(at, len(raw))]
            frame = grown.iloc[order].reset_index(drop=True)
            frame.attrs = dict(raw.attrs)
            if count > 0:
                frame.attrs[ROW_SPANS] = after_insertion(raw, at, count)
            _remap_row_metadata(dataset, lambda row: row + count if row >= at else row)
            dataset.text_styles = dataset.text_styles.insert_rows(at, count)
            dataset.raw = frame
        return self.edit(title, "Insert rows", change)

    def delete_rows(self, title, rows):
        rows = sorted(set(rows))

        def change(dataset):
            raw = dataset.raw
            keep = [index for index in range(len(raw)) if index not in rows]
            frame = raw.iloc[keep].reset_index(drop=True)
            frame.attrs = dict(raw.attrs)
            if len(frame) != len(raw):
                frame.attrs[ROW_SPANS] = after_deletion(raw, rows)
            mapping = {old: new for new, old in enumerate(keep)}
            _remap_row_metadata(dataset, mapping.get)
            dataset.text_styles = dataset.text_styles.delete_rows(row for row in rows if 0 <= row < len(raw))
            dataset.raw = frame
        return self.edit(title, "Delete rows", change)

    def move_rows(self, title, start, stop, destination):
        dataset = self.editable(title)
        if not reorder_rows_allowed(dataset):
            raise ValueError(qt("qt.rows_reorder_unavailable"))
        length = len(dataset.raw)
        if (type(start) is not int or type(stop) is not int or type(destination) is not int
                or not (0 <= start < stop <= length) or not (0 <= destination <= length)):
            raise ValueError(qt("qt.rows_virtual_or_invalid"))
        if start <= destination <= stop:
            return None

        def change(candidate):
            raw = candidate.raw
            order = np.concatenate([np.arange(first, last)
                                    for first, last in row_move_slices(length, start, stop, destination)])
            frame = raw.iloc[order].reset_index(drop=True)
            frame.attrs = dict(raw.attrs)
            frame.attrs[ROW_SPANS] = after_move(raw, start, stop, destination)
            _remap_row_metadata(candidate, lambda row: move_row_index(row, start, stop, destination))
            candidate.text_styles = candidate.text_styles.move_rows(length, start, stop, destination)
            candidate.raw = frame

        return self.edit(title, "Move rows", change)

    def sort_rows(self, title, key, direction=ASCENDING, *, plan=None, expected_revision=None, expected_raw=None):
        """Sort all rows of worksheet ``title`` atomically by a non-calculated source column."""
        if expected_revision is not None and self.revision != expected_revision:
            raise ValueError(sort_text("err.stale"))
        if title not in self.tables:
            raise ValueError(sort_text("err.stale"))
        dataset = self.editable(title)
        if expected_raw is not None and dataset.raw is not expected_raw:
            raise ValueError(sort_text("err.stale"))
        if not reorder_rows_allowed(dataset):
            raise ValueError(qt("qt.rows_reorder_unavailable"))
        length = len(dataset.raw)
        if plan is None:
            resolved = plan_row_sort(dataset, key, direction, locked=False, reorder_allowed=True)
        else:
            validate_sort_key(dataset, plan.key_name)
            if plan.row_count != length:
                raise ValueError(sort_text("err.stale"))
            order_arr = validate_permutation(plan.order, length)
            inverse = np.empty(length, dtype=np.intp)
            if length:
                inverse[order_arr] = np.arange(length, dtype=np.intp)
            changed = not np.array_equal(order_arr, np.arange(length, dtype=np.intp))
            resolved = plan if (plan.order is order_arr and plan.changed == changed) else type(plan)(
                key_name=plan.key_name,
                raw_column=plan.raw_column,
                display_column=plan.display_column,
                direction=plan.direction,
                row_count=length,
                order=order_arr,
                inverse=inverse,
                changed=changed,
            )
        if not resolved.changed:
            return None
        return self._permute_rows(title, resolved.order, resolved.inverse, "Sort rows")

    def reverse_rows(self, title):
        dataset = self.editable(title)
        if not reorder_rows_allowed(dataset):
            raise ValueError(qt("qt.rows_reorder_unavailable"))
        length = len(dataset.raw)
        if length < 2:
            return None
        order = np.arange(length - 1, -1, -1, dtype=np.intp)
        return self._permute_rows(title, order, order, "Reverse rows")

    def _permute_rows(self, title, order, inverse, label):
        def change(candidate):
            raw = candidate.raw
            length = len(raw)
            inv_list = inverse.tolist()
            frame = raw.iloc[order].reset_index(drop=True)
            frame.attrs = dict(raw.attrs)
            frame.attrs[ROW_SPANS] = after_permutation(raw, order)
            _remap_row_metadata(candidate, lambda row: inv_list[row] if 0 <= row < length else None)
            candidate.text_styles = candidate.text_styles.reorder_rows(length, order, inverse=inverse)
            candidate.raw = frame

        return self.edit(title, label, change)

    def insert_column(self, title, position, name):
        def change(dataset):
            raw = dataset.raw.copy()
            if not name.strip() or name in raw.columns or name in dataset.formulas:
                raise ValueError("Choose a new column name.")
            if dataset.column_order is None:
                position_ = max(0, min(position, len(raw.columns)))
            else:
                order = dataset.column_order
                at = max(0, min(position, len(order)))
                position_ = sum(index is not None for index in dataset.source_indices[:at])
                dataset.column_order = (*order[:at], name, *order[at:])
            raw.insert(position_, name, pd.Series([pd.NA] * len(raw), dtype="Float64"))
            raw.attrs = dict(dataset.raw.attrs)
            store_column_ids(raw, column_ids_after_insertion(dataset.raw, name))
            dataset.excluded = {(row, column + 1 if column >= position_ else column)
                                for row, column in dataset.excluded}
            dataset.raw = raw
        return self.edit(title, "Insert column", change)

    def delete_columns(self, title, columns):
        columns = sorted(set(columns))

        def change(dataset):
            raw = dataset.raw
            indices = dataset.source_indices
            sources = {indices[index] for index in columns if 0 <= index < len(indices)} - {None}
            if not sources:
                raise ValueError(tr_formula_only())
            if dataset.formulas and len(sources) == len(raw.columns):
                raise ValueError("Keep at least one source column in a worksheet with formulas.")
            names = raw.columns[sorted(sources)]
            frame = raw.drop(columns=names)
            frame.attrs = dict(raw.attrs)
            keep_source_columns(frame)
            store_column_ids(frame, column_ids_after_deletion(raw, names))
            if roles := raw.attrs.get("worksheet_roles"):
                x_members = [name for name in roles["x"] if name in frame]
                if xy_source_roles(raw, dataset.table_format) and len(roles["x"]) == 2:
                    if roles["x"][0] in names and roles["x"][1] in frame:
                        raise ValueError(qt("qt.x_error_requires_x"))
                    self._check_column_rename(title, [name for name in roles["x"] if name in names])
                y_groups = [[name for name in group if name in frame] for group in roles["y"]]
                frame.attrs["worksheet_roles"] = {"x": x_members, "y": [group for group in y_groups if group]}
            keep = [index for index in range(len(raw.columns)) if index not in sources]
            mapping = {old: new for new, old in enumerate(keep)}
            dataset.excluded = {(row, mapping[column]) for row, column in dataset.excluded if column in mapping}
            if dataset.column_order is not None:
                dataset.column_order = tuple(name for name in dataset.column_order if name not in names)
            dataset.raw = frame
            if dataset.cell_backgrounds:
                dataset.cell_backgrounds = {cell: color for cell, color in dataset.cell_backgrounds.items()
                                            if cell[1] not in names}
            if any(name in dataset.number_formats for name in names):
                dataset.number_formats = {name: spec for name, spec in dataset.number_formats.items()
                                          if name not in names}
            dataset.text_styles = dataset.text_styles.drop(names)
        return self.edit(title, "Delete columns", change)

    def _check_column_rename(self, title, names):
        def uses_name(value, name):
            if isinstance(value, str):
                return value == name
            if isinstance(value, dict):
                return name in value or any(uses_name(item, name) for item in value.values())
            if isinstance(value, (tuple, list)):
                return any(uses_name(item, name) for item in value)
            return False

        readers = self.readers([title])
        for name in names:
            if any(uses_name(run.options, name) for run in readers):
                raise ValueError(tr("variables.error.reference", name=name))

    def rename_column(self, title, column, name):
        def change(dataset):
            raw = dataset.raw
            name_ = name.strip()
            indices = dataset.source_indices
            if not 0 <= column < len(indices) or (source := indices[column]) is None:
                raise ValueError(tr_formula_only())
            previous = raw.columns[source]
            if not name_ or (name_ != previous and (name_ in raw.columns or name_ in dataset.formulas)):
                raise ValueError("Choose a new column name.")
            if name_ == previous:
                return
            rename = {previous: name_}
            formulas = {key: rename_formula_columns(expr, rename) for key, expr in dataset.formulas.items()}
            if formulas != dataset.formulas:
                self._check_column_rename(title, rename)
                dataset.formulas = formulas
            frame = raw.rename(columns=rename)
            frame.attrs = dict(raw.attrs)
            keep_source_columns(frame, rename)
            store_column_ids(frame, column_ids_after_rename(raw, rename))
            if roles := xy_source_roles(raw, dataset.table_format):
                is_x_pair = len(roles["x"]) == 2 and previous in roles["x"]
                if is_x_pair:
                    self._check_column_rename(title, rename)
                if is_x_pair or "worksheet_roles" in raw.attrs:
                    frame.attrs["worksheet_roles"] = {"x": [rename.get(key, key) for key in roles["x"]],
                                                       "y": [[rename.get(key, key) for key in group] for group in roles["y"]]}
            if dataset.column_order is not None:
                order = dataset.column_order
                dataset.column_order = (*order[:column], name_, *order[column + 1:])
            dataset.raw = frame
            if previous != name_ and dataset.cell_backgrounds:
                dataset.cell_backgrounds = {(row, name_ if key == previous else key): color
                                            for (row, key), color in dataset.cell_backgrounds.items()}
            if previous != name_ and previous in dataset.number_formats:
                dataset.number_formats = {name_ if key == previous else key: spec
                                          for key, spec in dataset.number_formats.items()}
            dataset.text_styles = dataset.text_styles.rename(previous, name_)
        return self.edit(title, "Rename column", change)

    def change_variables(self, title, changes):
        """Apply source names and explicit variable types as a single worksheet edit."""
        dataset = self.editable(title)
        if dataset.table_format != "multivariable":
            raise ValueError(tr("variables.error.worksheet"))
        raw = dataset.raw
        current = raw.attrs.get(VARIABLE_TYPES, {})
        changes = {name: (label if label == name else label.strip(), kind)
                   for name, (label, kind) in changes.items()}
        if any(name not in raw or kind not in (*TYPES, "auto") for name, (_, kind) in changes.items()):
            raise ValueError(tr("variables.error.worksheet"))
        names = {name: changes.get(name, (name, None))[0] for name in raw}
        if (any(not label or len(label) > 160 for name, label in names.items() if label != name)
                or len(set(names.values()) | dataset.formulas.keys()) != len(names) + len(dataset.formulas)):
            raise ValueError(tr("variables.error.names"))
        rename = {name: label for name, label in names.items() if label != name}
        kinds = {name: kind for name, (_, kind) in changes.items() if kind != current.get(name, "auto")}
        if not (rename or kinds):
            return None

        if rename:
            self._check_column_rename(title, rename)

        def change(candidate):
            frame = raw.rename(columns=rename)
            keep_source_columns(frame, rename)
            if rename:
                store_column_ids(frame, column_ids_after_rename(raw, rename))
            if rename and (roles := raw.attrs.get("worksheet_roles")) is not None:
                frame.attrs["worksheet_roles"] = {"x": [names[name] for name in roles["x"]],
                                                   "y": [[names[name] for name in group] for group in roles["y"]]}
            types = dict(frame.attrs.get(VARIABLE_TYPES, {}))
            orders = dict(frame.attrs.get(WORKSHEET_ORDERS, {}))
            for source, kind in kinds.items():
                name = names[source]
                frame[name] = convert_type(raw[source], kind)
                if kind == "auto":
                    types.pop(name, None)
                else:
                    types[name] = kind
                if frame[name].dtype != raw[source].dtype:
                    orders.pop(name, None)
            for key, values in ((VARIABLE_TYPES, types), (WORKSHEET_ORDERS, orders)):
                if values:
                    frame.attrs[key] = values
                else:
                    frame.attrs.pop(key, None)
            candidate.raw = frame
            if rename and candidate.formulas:
                candidate.formulas = {key: rename_formula_columns(expr, rename)
                                      for key, expr in candidate.formulas.items()}
            if candidate.column_order is not None:
                candidate.column_order = tuple(names.get(name, name) for name in candidate.column_order)
            candidate.cell_backgrounds = {(row, names.get(name, name)): color
                                          for (row, name), color in candidate.cell_backgrounds.items()}
            candidate.number_formats = {names.get(name, name): spec for name, spec in candidate.number_formats.items()}
            candidate.text_styles = candidate.text_styles.rename_many(names)

        return self.edit(title, tr("variables.title"), change)

    def category_level_blockers(self, title, plan):
        """Return any recipes reading ``(title, plan.column)`` blocked by removed levels."""
        return find_blocking_recipes(self, title, plan)

    def apply_category_levels(self, title, plan):
        """Apply validated level renames/merges and category order in one undoable edit."""
        dataset = self.editable(title)
        if plan.value_map and not can_rename_levels(dataset, plan.column):
            raise LevelEditError(tr("category_levels.error.ineligible"), code="ineligible")
        blockers = self.category_level_blockers(title, plan)
        if blockers:
            token = blockers[0].source_tokens[0] if blockers[0].source_tokens else None
            raise LevelEditError(format_recipe_blockers(blockers), token=token, code="recipe_blocked")
        if not plan.has_changes:
            return None
        label = tr("category_levels.history_label") if plan.value_map else tr("command.category_order").removesuffix("…")
        return self.edit(title, label, lambda candidate: apply_level_plan(candidate, plan))

    def set_formula(self, title, name, expression):
        """Add a calculated column, or change the expression of an existing one."""
        return self.edit(title, "Edit formula", lambda dataset: dataset.set_formula(name.strip(), expression))

    def toggle_exclusion(self, title, cells):
        def change(dataset):
            current = set(dataset.excluded)
            indices = dataset.source_indices
            cells_ = {(row, indices[column]) for row, column in cells
                      if 0 <= row < len(dataset.raw) and 0 <= column < len(indices) and indices[column] is not None}
            if cells_ and cells_ <= current:
                current -= cells_
            else:
                current |= cells_
            dataset.excluded = current
        return self.edit(title, "Exclude cells", change)

    # -- worksheets linked to a CSV or TSV file (analisi.source_link) ------------------------------------------
    def attach_source(self, title, spec):
        """Link a worksheet just imported from ``spec.path`` (part of the import: not a separate Undo step)."""
        dataset = self.tables[title]
        dataset.source_link = source_link.new_link(spec, dataset.raw, dataset.excluded)
        self.dirty = True

    def source_sheet(self, title):
        """``(raw, excluded)`` of a worksheet, to compare with its file away from the window thread."""
        dataset = self.editable(title)
        return dataset.raw, frozenset(dataset.excluded)

    def update_from_source(self, title, plan, *, choice=None, decisions=None, replace_rows=False):
        """Apply a plan of ``analisi.source_link.plan_update``: one Undo step and one recalculation of the analyses
        that read the worksheet. Conflicts are decided all at once (``choice``) or row by row (``decisions``, by
        conflict identity); the engine checks them before anything changes. Raises ValueError, changing nothing,
        when the worksheet changed after the plan or a decision is missing or foreign to the plan."""
        dataset = self.editable(title)
        if dataset.raw is not plan.raw or (plan.relink is None and dataset.source_link is not plan.link):
            raise ValueError("The worksheet changed after the file was read. Update again.")
        arrangement = source_link.arrange(plan, choice=choice, decisions=decisions, replace_rows=replace_rows)
        length = len(dataset.raw)
        if not arrangement.changes_data(length) and not plan.new_columns:
            link = source_link.confirmed_link(plan, arrangement, _with_spans(dataset.raw))
            if source_link.same_link(link, dataset.source_link):
                return None
            before = WorksheetState.capture(dataset)
            dataset.source_link = link
            return [] if self._record_background(title, dataset, before, "Update from file") else None
        new_raw = source_link.build_frame(plan, arrangement)
        mapping = arrangement.mapping()
        link = source_link.confirmed_link(plan, arrangement, new_raw)

        def change(candidate):
            _remap_row_metadata(candidate, mapping.get)
            if plan.options.mark_excluded:  # The exclusion mark of the file decides for the cells it sends.
                imported = {position for position, name in enumerate(new_raw.columns) if name in plan.names}
                taken = set(np.flatnonzero(arrangement.take >= 0).tolist())
                candidate.excluded = ({(row, column) for row, column in candidate.excluded
                                       if not (row in taken and column in imported)}
                                      | source_link.file_exclusions(plan, arrangement, new_raw.columns))
            candidate.text_styles = source_link.reindex_styles(candidate.text_styles, arrangement, length)
            candidate.raw = new_raw
            candidate.source_link = link

        return self.edit(title, "Update from file", change)

    def unlink_source(self, title):
        """Remove the link and keep the cells and the results. One Undo step, no recalculation."""
        dataset = self.editable(title)
        if dataset.source_link is None:
            return False
        before = WorksheetState.capture(dataset)
        dataset.source_link = None
        return self._record_background(title, dataset, before, "Unlink source file")

    def source_references(self, title, rows):
        """What disappears with the worksheet ``rows`` (0-based): excluded cells, backgrounds, styled text, row
        heights, styled or labelled points of graphs and values of the columns added in the project."""
        dataset = self.tables[title]
        rows = set(rows)
        if not rows:
            return {}
        imported = set(dataset.source_link.imported_names(dataset.raw)) if dataset.source_link else set()
        project_columns = [position for position, name in enumerate(dataset.raw.columns) if name not in imported]
        counts = {
            "excluded": sum(1 for row, _ in dataset.excluded if row in rows),
            "backgrounds": sum(1 for row, _ in dataset.cell_backgrounds if row in rows),
            "heights": sum(1 for row in dataset.row_heights if row in rows),
            "text": _styled_rows(dataset.text_styles, rows, len(dataset.raw)),
            "values": int(dataset.raw.iloc[sorted(rows), project_columns].notna().to_numpy().sum())
            if project_columns else 0,
        }
        tokens = set(row_tokens(dataset.raw, sorted(rows)))
        points = 0
        for run in self.runs:
            if run.title == title:
                points += _count_tokens(run.style or dataset.graph_styles.get(run.slot) or {}, tokens)
        counts["points"] = points
        return {name: count for name, count in counts.items() if count}

    def _remove_layout_family(self, change):
        bundle, runs = change.bundle, change.runs
        titles = bundle.tables.keys()
        uids = {run.uid for run in runs}
        refs = {run.reference for run in runs}
        info_ids = {sheet.uid for sheet in bundle.infos}
        owners = {f"{kind}:{uid}" for kind in ("graph", "result", "saved-layout") for uid in uids}
        owners.update(f"info:{uid}" for uid in info_ids)

        def reads_copy(records):
            return bool(uids.intersection(linked_tables.source_analyses(records))) or any(
                record.get("source", {}).get("kind") == "sheet"
                and record["source"]["sheet"] in titles for record in records)

        # Existing navigator references are indices. Removing a suffix leaves all other references valid.
        if (len(runs) > len(self.runs)
                or any(old is not current for old, current in zip(runs, self.runs[-len(runs):], strict=True))
                or any(self.tables.get(title) is not dataset for title, dataset in bundle.tables.items())
                or any(self.info_sheets.get(sheet.uid) != sheet for sheet in bundle.infos)
                or any(sheet.uid not in info_ids and (sheet.table in titles or sheet.worksheet in owners)
                       for sheet in self.info_sheets.values())
                or any(run.title in titles or run.source and run.source.analysis_id in uids
                       or run.method == worksheet_join.METHOD and worksheet_join.right_title(run.options) in titles
                       or reads_copy((run.style or {}).get(TABLES, ())) for run in self.runs[:-len(runs)])
                or any(refs.intersection(layout.panels) or reads_copy(layout.tables)
                       for index, layout in enumerate(self.layouts) if index != change.index)):
            raise ValueError(tr("layout.undo_unavailable"))
        for title in titles:
            del self.tables[title]
        del self.runs[-len(runs):]
        if info_ids:
            self.update_info_sheets({uid: sheet for uid, sheet in self.info_sheets.items() if uid not in info_ids})
        records = self.sheet_metadata.get("sheets", {})
        for title in titles:
            records.pop(f"data:{title}", None)
        for uid in uids:
            for kind in ("graph", "result", "saved-layout"):
                records.pop(f"{kind}:{uid}", None)
            self.sheet_metadata.get("frozen_runs", {}).pop(uid, None)

    def can_apply_history(self, change):
        if isinstance(change, WorksheetChange):
            return not self.sheet_locked(("data", change.title))
        if isinstance(change, StyleBatchChange):
            return self.sheet_metadata.get("frozen_runs", {}).keys().isdisjoint(change.before)
        if isinstance(change, LayoutFamilyChange):
            return not self.sheet_locked(("layout", change.index))
        return isinstance(change, LayoutChange)

    def undo(self, *, redo=False):
        self.undo_style_uids = ()
        self.undo_layout_index = None
        change = self.history.next_change(redo=redo)
        if change is None or not self.can_apply_history(change):
            return None, None
        if isinstance(change, LayoutChange):
            expected, target = (change.before, change.after) if redo else (change.after, change.before)
            if change.index >= len(self.layouts) or self.layouts[change.index] != expected:
                raise ValueError(tr("layout.undo_unavailable"))
            if isinstance(change, LayoutFamilyChange):
                if redo:
                    self.apply_family(change.bundle, prepared=change.runs)
                else:
                    self._remove_layout_family(change)
            self.layouts[change.index] = deepcopy(target)
            self.history.position += 1 if redo else -1
            self.dirty = True
            self.undo_layout_index = change.index
            return None, []
        if isinstance(change, StyleBatchChange):
            by_uid = {run.uid: run for run in self.runs}
            target_styles = change.after if redo else change.before
            targets = []
            for uid in target_styles:
                run = by_uid.get(uid)
                if run is None:
                    raise ValueError("A styled graph is no longer in this project.")
                targets.append((uid, run))
            self._apply_style_updates(targets, target_styles)
            self.history.position += 1 if redo else -1
            self.dirty = True
            self.undo_changed_data = False
            self.undo_style_uids = tuple(target_styles.keys())
            return None, []
        change = self.history.apply(self.tables, redo=redo)
        if change is None:
            return None, None
        dataset = self.tables[change.title]
        if dataset.source_link is not None and self.path is not None:
            dataset.source_link = dataset.source_link.with_relative(self.path.absolute().parent)
        self.dirty = True
        # False for colours and number formats: the window can refresh the open grid in place.
        self.undo_changed_data = change.before.data_changed(change.after)
        self.update_linked_tables()  # Number formats are undone too, and a linked table shows them.
        if self.undo_changed_data:
            return change.title, self.table_runs(change.title)
        if change.before.worksheet_titles.columns != change.after.worksheet_titles.columns:
            return change.title, self.worksheet_title_graphs(change.title)
        return change.title, []


def _with_spans(raw):
    """``raw`` with its row identities written down (a link always names them)."""
    if ROW_SPANS in raw.attrs:
        return raw
    copy_ = raw.copy(deep=False)
    copy_.attrs = dict(raw.attrs)
    copy_.attrs[ROW_SPANS] = current_spans(raw)
    return copy_


def _styled_rows(styles, rows, length):
    if not styles:
        return 0
    mask = np.zeros(length, dtype=bool)
    for column in styles.runs.values():
        for start, stop, _ in column:
            mask[max(0, start):min(length, stop)] = True
    return int(mask[sorted(rows)].sum())


def _count_tokens(value, tokens):
    """How many records of a graph style point at one of the worksheet row ``tokens`` (styled or labelled points)."""
    if isinstance(value, dict):
        own = 1 if value.get("row_token") in tokens else 0
        return own + sum(_count_tokens(item, tokens) for key, item in value.items() if key != "row_token")
    if isinstance(value, (list, tuple)):
        return sum(_count_tokens(item, tokens) for item in value)
    return 0


def reorder_rows_allowed(dataset):
    return not (stored_legacy_view(dataset)
                or dataset.table_format == EDITABLE_LEGACY_XY
                or dataset.table_format in EDITABLE_LEGACY_FIXED_VALUES)


def _remap_row_metadata(dataset, remap):
    if dataset.excluded:
        dataset.excluded = {(new_row, col) for row, col in dataset.excluded
                            if (new_row := remap(row)) is not None}
    if dataset.cell_backgrounds:
        dataset.cell_backgrounds = {(new_row, name): color
                                    for (row, name), color in dataset.cell_backgrounds.items()
                                    if (new_row := remap(row)) is not None}
    if dataset.row_heights:
        dataset.row_heights = {new_row: height for row, height in dataset.row_heights.items()
                               if (new_row := remap(row)) is not None}


def _persist_links(runs, tables, *, pinned=()):
    """Write the identity, source and name of every analysis into the tables that store its recipe: on the live
    project before Save, on a detached copy for a recovery copy."""
    linked = {run.uid for run in runs if run.source is not None}
    for run in runs:
        if run.slot < 0:
            continue
        dataset = tables[run.title]
        if linked or run.uid in pinned or run.slot in dataset.analysis_ids:
            dataset.analysis_ids[run.slot] = run.uid
        if run.source is not None:
            dataset.analysis_sources[run.slot] = run.source
        else:
            dataset.analysis_sources.pop(run.slot, None)
        if run.label is not None:
            dataset.analysis_labels[run.slot] = run.label
        else:
            dataset.analysis_labels.pop(run.slot, None)


def tr_formula_only():
    return "Calculated columns are changed with Formula."
