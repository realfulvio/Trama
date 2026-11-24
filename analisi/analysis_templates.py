"""Reusable analysis templates: the method of a project without its observations (``.tramatpl``).

A template keeps what is needed to run the same work on new data: for every data table the expected
columns (names, kinds and worksheet roles) and the native table format, the calculated columns, the
analyses with their options, persistent names, graph styles and the links between them, and the native
layouts. It never keeps rows, excluded cells, results, attributes left by an import, file or host
references, history, Info sheets, drawn shapes or free annotations.

The file is UTF-8 JSON, an object whose ``schema`` is 1. Identities are local to the file (``A1``,
``A2``…): links and layout panels go through them, and every instance receives new persistent
identities. This module never creates a window, never changes its arguments and reads or writes only
the path it is given.

``write_template(path, tables, layouts=…)`` validates and writes atomically; ``read_template(path)``
validates without calculating anything; ``instantiate_template(template, sources, mapping)`` copies new
data under the canonical column names and returns ``(tables, layouts)`` ready to calculate.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
import json
from math import isfinite
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from uuid import NAMESPACE_URL, uuid4, uuid5

import pandas as pd

from .analysis_chain import ChainCancelled, MAX_ANALYSIS_NODES, ResultSource
from .analysis_labels import valid_label
from .family_workflow import same_file  # Also through links or another spelling of the path.
from .data import (EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_EMF, EDITABLE_LEGACY_STACKS, EDITABLE_LEGACY_XY,
                   MAX_CELLS, MAX_COLUMNS, MAX_ENTRY, Dataset, _formula_tree, _project_column_kind,
                   _validated_column_order, _validated_worksheet_roles, _worksheet_roles,
                   formula_calculation_order, info_references,
                   validate_analysis_links)
from .graph_annotations import ANNOTATIONS
from .graph_shapes import SHAPES
from .layout_geometry import AUTO_PAPER, WHITE
from .legacy_project_metadata import IMPORTED_METHODS, is_import_option, saved_name
from .presentation import Layout, validated_style

SCHEMA = 1
KIND = "trama-analysis-template"
SUFFIX = ".tramatpl"
MAX_TEMPLATE_BYTES = MAX_ENTRY
MAX_TABLES = 256
MAX_LAYOUTS = 128
MAX_NAME = 1024
MAX_DEPTH = 32
KINDS = ("numeric", "text", "mixed")
IMPORTED_FORMATS = {EDITABLE_LEGACY_XY, EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_STACKS, EDITABLE_LEGACY_EMF,
                    "Imported graph collection", "Imported layout collection"}
_LOCAL_ID = re.compile(r"A[1-9][0-9]{0,5}")
_ROOT_KEYS = {"schema", "kind", "tables", "layouts"}
_TABLE_KEYS = {"name", "format", "columns", "roles", "formulas", "analyses", "column_order"}
_COLUMN_KEYS = {"name", "kind"}
_ANALYSIS_KEYS = {"id", "method", "options", "source", "label", "style"}
_SOURCE_KEYS = {"id", "table"}
_LAYOUT_KEYS = {"name", "columns", "panels", "paper", "background", "panel_size", "axis_alignment"}


class TemplateError(ValueError):
    """A template cannot be written, read or applied.

    ``code`` names the reason for translation; ``field`` names what the user should look at: a table, a
    template column (``(table, column)``), the file, or None. ``problems`` lists every blocking problem
    found while preparing a template, each a :class:`Problem`.
    """

    def __init__(self, code, message, *, field=None, problems=(), **detail):
        super().__init__(message)
        self.code, self.field, self.problems, self.detail = code, field, tuple(problems), detail


@dataclass(frozen=True)
class Problem:
    """Something to remove or replace before saving, with where it is.

    ``place`` is ``("table", title)``, ``("formula", title, name)``, ``("analysis", title, slot)``,
    ``("layout", index)`` or ``("project",)``."""
    code: str
    place: tuple
    message: str
    detail: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Omission:
    """Something the template leaves out on purpose (shown by the confirmation, never blocking)."""
    code: str
    place: tuple
    count: int = 1


@dataclass(frozen=True)
class TableSpec:
    name: str
    table_format: str
    columns: tuple            # ((name, kind), …) of the observed columns, in template order
    roles: dict | None
    formulas: tuple           # ((name, expression), …)
    analyses: tuple           # AnalysisSpec, in slot order
    column_order: tuple[str, ...] | None = None

    @property
    def column_names(self):
        return tuple(name for name, _ in self.columns)


@dataclass(frozen=True)
class AnalysisSpec:
    id: str
    method: str
    options: dict
    source: tuple | None = None   # (local id of the parent, result table name)
    label: str | None = None
    style: dict | None = None


@dataclass(frozen=True)
class LayoutSpec:
    name: str
    columns: int
    panels: tuple                 # local analysis ids
    paper: str = AUTO_PAPER
    background: str = WHITE
    panel_size: str = "original"
    axis_alignment: str = "none"


@dataclass(frozen=True)
class AnalysisTemplate:
    """A template read from a file. Nothing in it refers to the project it came from."""
    tables: tuple
    layouts: tuple

    @property
    def table_names(self):
        return tuple(table.name for table in self.tables)

    def table(self, name):
        return next(table for table in self.tables if table.name == name)

    @property
    def analysis_count(self):
        return sum(len(table.analyses) for table in self.tables)

    @property
    def link_count(self):
        return sum(1 for table in self.tables for analysis in table.analyses if analysis.source is not None)


@dataclass(frozen=True)
class TemplatePlan:
    """What ``write_template`` would write, from metadata only: the confirmation shows it."""
    template: AnalysisTemplate | None
    problems: tuple
    omissions: tuple
    rows: int                     # observations left out (they never travel)

    @property
    def ok(self):
        return not self.problems


# ---------------------------------------------------------------------------
# Validation helpers


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise ChainCancelled


def _fail(code, message, *, field=None, **detail):
    raise TemplateError(code, message, field=field, **detail)


def _text(value, what, *, limit=MAX_NAME, field=None):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail("type", f"{what} must be text of 1 to {limit} characters.", field=field, what=what)
    return value


def _json_value(value, depth=0):
    """JSON-native, finite and not too deep: what an option may hold."""
    if depth > MAX_DEPTH:
        raise ValueError("Saved options are nested too deeply.")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Saved options contain a number that is not finite.")
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Saved option names must be text.")
            _json_value(item, depth + 1)
        return
    raise ValueError("Saved options contain a value that cannot be written as text.")


def _plain(value):
    """Tuples become lists so that a template read back compares equal to the one written."""
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _column_roles(method):
    """Option names whose values are columns of the analysed table, from the field specification."""
    from .workbench import METHODS, MULTIPLE, OPTIONAL, OPTIONAL_MULTIPLE

    return {name for name, kind in METHODS.get(method, {}).items()
            if kind is None or kind in (OPTIONAL, MULTIPLE, OPTIONAL_MULTIPLE)}


def _referenced_columns(method, options):
    names = []
    for role in _column_roles(method):
        value = options.get(role)
        values = value if isinstance(value, list) else [value]
        names.extend(item for item in values if isinstance(item, str) and item)
    return names


def _recipe_problem(method, options, columns, *, root):
    """Why a recipe cannot travel in a template, or None. ``columns`` are those of its own table."""
    from .workbench import METHODS

    if not isinstance(method, str) or saved_name(method) in IMPORTED_METHODS:
        return "imported-analysis", "This analysis shows an imported view; remove it or analyse the data again."
    if method not in METHODS:
        return "unknown-method", f"The analysis {method!r} is not available in this version of Trama."
    if not isinstance(options, dict):
        return "invalid-options", "The saved options of this analysis are not valid."
    if any(isinstance(key, str) and is_import_option(key) for key in options):
        return "imported-analysis", "This analysis keeps data of an imported file; analyse the data again."
    try:
        _json_value(options)
    except ValueError as error:
        return "invalid-options", str(error)
    if root:
        missing = sorted(set(_referenced_columns(method, options)) - set(columns))
        if missing:
            return "missing-column", f"The analysis uses columns that are not in its table: {', '.join(missing)}."
    return None


# ---------------------------------------------------------------------------
# Writing


def _local_ids(tables):
    ids, number = {}, 0
    for title, dataset in tables.items():
        for slot in range(len(dataset.analyses)):
            number += 1
            ids[title, slot] = f"A{number}"
    return ids


def plan_template(tables, layouts=(), info_sheets=None, *, cancel=None):
    """Prepare the template of a project without writing it.

    Returns a :class:`TemplatePlan` with the template, the blocking problems (each with where it is) and
    what is left out on purpose. Reads only metadata: its cost does not depend on the number of rows.
    """
    if info_sheets is None:
        info_sheets = getattr(tables, "info_sheets", ())
    layouts = tuple(layouts)
    problems, omissions = [], []
    if not tables:
        problems.append(Problem("empty", ("project",), "The project has no data table."))
    if len(tables) > MAX_TABLES:
        problems.append(Problem("too-many", ("project",), f"A template holds up to {MAX_TABLES} data tables."))
    if len(layouts) > MAX_LAYOUTS:
        problems.append(Problem("too-many", ("project",), f"A template holds up to {MAX_LAYOUTS} layouts."))
    if info_sheets:
        omissions.append(Omission("info-sheets", ("project",), len(info_sheets)))
    local = _local_ids(tables)
    if len(local) > MAX_ANALYSIS_NODES:
        problems.append(Problem("too-many", ("project",), "The project exceeds the analysis node budget."))
    by_identity = {}
    for title, dataset in tables.items():
        for slot, identifier in dataset.analysis_ids.items():
            if (title, slot) in local:
                by_identity.setdefault(identifier, (title, slot))
    imported = set()
    rows = 0
    specs = []
    for title, dataset in tables.items():
        _cancelled(cancel)
        raw = dataset.raw
        rows += len(raw)
        place = ("table", title)
        if dataset.table_format in IMPORTED_FORMATS:
            problems.append(Problem("imported-table", place, "This sheet keeps an imported view; copy its data "
                                    "into a new data table first."))
        if dataset.excluded:
            omissions.append(Omission("excluded", place, len(dataset.excluded)))
        if len(raw):
            omissions.append(Omission("rows", place, len(raw)))
        columns = tuple((str(name), _project_column_kind(raw[name])) for name in raw.columns)
        try:
            roles = _worksheet_roles(raw)
            roles = None if roles is None else deepcopy(_validated_worksheet_roles(roles, raw.columns))
        except ValueError:
            roles = None
            problems.append(Problem("roles", place, "The X and Y roles of this table refer to missing columns."))
        formulas = []
        for name, expression in dataset.formulas.items():
            if info_references(expression):
                problems.append(Problem("info-formula", ("formula", title, name),
                                        "This formula reads an Info sheet, which a template does not carry; "
                                        "replace INFO() with a value or remove the formula.",
                                        {"name": name}))
            formulas.append((name, expression))
        known = [name for name, _ in columns] + [name for name, _ in formulas]
        analyses = []
        for slot, (method, options) in enumerate(dataset.analyses):
            spot = ("analysis", title, slot)
            source = dataset.analysis_sources.get(slot)
            problem = _recipe_problem(method, options, known, root=source is None)
            if problem is not None:
                if problem[0] == "imported-analysis":
                    imported.add((title, slot))
                problems.append(Problem(problem[0], spot, problem[1]))
                continue
            link = None
            if source is not None:
                parent = by_identity.get(source.analysis_id)
                if parent is None:
                    problems.append(Problem("broken-source", spot, "This analysis reads the results of an "
                                            "analysis that is no longer in the project."))
                    continue
                link = (local[parent], source.table)
            style = dataset.graph_styles.get(slot)
            if style is not None:
                style = deepcopy(style)
                for key, code in ((SHAPES, "shapes"), (ANNOTATIONS, "annotations")):
                    if style.get(key):
                        omissions.append(Omission(code, spot, len(style[key])))
                    style.pop(key, None)
                try:
                    style = _plain(validated_style(style))
                    _json_value(style)
                except (ValueError, TypeError) as error:
                    problems.append(Problem("invalid-style", spot, f"The graph format is not valid: {error}"))
                    continue
                style = style or None
            label = dataset.analysis_labels.get(slot)
            analyses.append(AnalysisSpec(local[title, slot], method, _plain(deepcopy(options)), link, label, style))
        specs.append(TableSpec(title, dataset.table_format, columns, roles, tuple(formulas), tuple(analyses),
                               dataset.column_order))
    for title, dataset in tables.items():  # A comparison drawn on a graph reads another analysis by slot.
        for slot, (method, options) in enumerate(dataset.analyses):
            if (title, slot) in imported:
                continue
            from .pairwise_graph import read_section
            try:
                settings, _ = read_section(options) if isinstance(options, dict) else (None, None)
            except (ValueError, TypeError, KeyError):
                settings = None
            if settings is not None and (title, settings["slot"]) in imported:
                problems.append(Problem("imported-analysis", ("analysis", title, slot),
                                        "This graph draws comparisons of an imported view."))
    try:
        validate_analysis_links(tables)
    except ValueError as error:
        problems.append(Problem("links", ("project",), str(error)))
    layout_specs = []
    for index, layout in enumerate(layouts):
        panels = []
        for panel in layout.panels:
            reference = tuple(panel)
            if reference not in local:
                problems.append(Problem("broken-layout", ("layout", index), "A panel of this layout shows a "
                                        "graph that is no longer in the project."))
                break
            if reference in imported:
                problems.append(Problem("imported-layout", ("layout", index), "A panel of this layout shows an "
                                        "imported view; replace it with a graph of the data."))
                break
            panels.append(local[reference])
        else:
            layout_specs.append(LayoutSpec(layout.name, layout.columns, tuple(panels), layout.paper,
                                           layout.background, layout.panel_size, layout.axis_alignment))
    template = None if problems else AnalysisTemplate(tuple(specs), tuple(layout_specs))
    return TemplatePlan(template, tuple(problems), tuple(omissions), rows)


def template_payload(template):
    """The JSON object of a template (schema 1)."""
    tables = []
    for table in template.tables:
        record = {"name": table.name, "format": table.table_format,
                  "columns": [{"name": name, "kind": kind} for name, kind in table.columns]}
        if table.roles is not None:
            record["roles"] = deepcopy(table.roles)
        record["formulas"] = [[name, expression] for name, expression in table.formulas]
        if table.column_order is not None:
            record["column_order"] = list(table.column_order)
        analyses = []
        for analysis in table.analyses:
            item = {"id": analysis.id, "method": analysis.method, "options": deepcopy(analysis.options)}
            if analysis.source is not None:
                item["source"] = {"id": analysis.source[0], "table": analysis.source[1]}
            if analysis.label is not None:
                item["label"] = analysis.label
            if analysis.style:
                item["style"] = deepcopy(analysis.style)
            analyses.append(item)
        record["analyses"] = analyses
        tables.append(record)
    layouts = []
    for layout in template.layouts:
        record = {"name": layout.name, "columns": layout.columns, "panels": list(layout.panels),
                  "paper": layout.paper, "background": layout.background}
        if layout.panel_size != "original":
            record["panel_size"] = layout.panel_size
        if layout.axis_alignment != "none":
            record["axis_alignment"] = layout.axis_alignment
        layouts.append(record)
    return {"schema": SCHEMA, "kind": KIND, "tables": tables, "layouts": layouts}


def write_template(path, tables, *, layouts=(), info_sheets=None, source_path=None, cancel=None):
    """Validate the template of ``tables`` and ``layouts`` and write it atomically to ``path``.

    ``source_path`` is the file of the open project: writing over it (also through an alias) is refused.
    Nothing of the arguments changes. Returns the :class:`TemplatePlan` that was written. Raises
    :class:`TemplateError` (a ValueError) with every blocking problem before anything is written.
    """
    path = Path(path)
    if path.suffix.lower() != SUFFIX:
        _fail("file-name", f"Choose a file name ending in {SUFFIX}.", field="file")
    if source_path is not None and same_file(path, source_path):
        _fail("current-path", "Choose another file: the open project cannot be replaced by its template.",
              field="file")
    plan = plan_template(tables, layouts, info_sheets, cancel=cancel)
    if not plan.ok:
        first = plan.problems[0]
        _fail("blocked", first.message, problems=plan.problems, place=first.place)
    _cancelled(cancel)
    text = json.dumps(template_payload(plan.template), ensure_ascii=False, allow_nan=False, indent=1)
    data = text.encode("utf-8")
    if len(data) > MAX_TEMPLATE_BYTES:
        _fail("too-large", "The template exceeds the 32 MiB limit.", field="file")
    tmp = None
    try:
        with NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".tramatpl-", delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(data + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _cancelled(cancel)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return plan


# ---------------------------------------------------------------------------
# Reading


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TemplateError("duplicate-key", f"The template repeats the field {key!r}.", field="file", key=key)
        result[key] = value
    return result


def _constant(name):
    raise TemplateError("number", f"The template contains the number {name}, which is not allowed.", field="file")


def _record(value, keys, required, what):
    if not isinstance(value, dict):
        _fail("type", f"{what} must be a JSON object.", field="file", what=what)
    unknown = set(value) - keys
    if unknown:
        _fail("unknown-field", f"{what} has an unknown field: {sorted(unknown)[0]}.", field="file",
              what=what, key=sorted(unknown)[0])
    missing = [key for key in required if key not in value]
    if missing:
        _fail("missing-field", f"{what} has no {missing[0]!r} field.", field="file", what=what, key=missing[0])
    return value


def _list(value, what, limit):
    if not isinstance(value, list) or len(value) > limit:
        _fail("type", f"{what} must be a list of at most {limit} items.", field="file", what=what)
    return value


def _parse_tables(records):
    tables, ids, names = [], {}, set()
    for position, record in enumerate(_list(records, "tables", MAX_TABLES), 1):
        what = f"Table {position}"
        _record(record, _TABLE_KEYS, ("name", "format", "columns", "formulas", "analyses"), what)
        name = _text(record["name"], f"{what} name", field="file")
        if name in names:
            _fail("duplicate-table", f"Two tables are named {name!r}.", field="file", table=name)
        names.add(name)
        what = f"Table {name!r}"
        table_format = _text(record["format"], f"{what} format", limit=160, field="file")
        if saved_name(table_format) in IMPORTED_FORMATS:
            _fail("imported-table", f"{what} uses an imported sheet format.", field="file", table=name)
        columns = []
        for item in _list(record["columns"], f"{what} columns", MAX_COLUMNS):
            _record(item, _COLUMN_KEYS, ("name", "kind"), f"A column of {what}")
            column = _text(item["name"], f"A column name of {what}", field="file")
            if item["kind"] not in KINDS:
                _fail("type", f"Column {column!r} of {what} has an unknown kind.", field="file")
            columns.append((column, item["kind"]))
        if not columns:
            _fail("type", f"{what} has no columns.", field="file")
        column_names = [column for column, _ in columns]
        if len(set(column_names)) != len(column_names):
            _fail("duplicate-column", f"{what} repeats a column name.", field="file", table=name)
        roles = record.get("roles")
        if roles is not None:
            roles = _validated_worksheet_roles(roles, column_names)
        formulas = []
        for item in _list(record["formulas"], f"{what} formulas", MAX_COLUMNS):
            if (not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str)
                    or not isinstance(item[1], str)):
                _fail("type", f"A formula of {what} is not a name and an expression.", field="file")
            formula_name, expression = item
            _text(formula_name, f"A formula name of {what}", field="file")
            if formula_name in column_names or formula_name in dict(formulas):
                _fail("duplicate-column", f"The formula {formula_name!r} of {what} repeats a column name.",
                      field="file", table=name)
            try:
                _formula_tree(expression)
            except (ValueError, SyntaxError) as error:
                _fail("formula", f"The formula {formula_name!r} of {what} is not valid: {error}", field="file")
            if info_references(expression):
                _fail("info-formula", f"The formula {formula_name!r} of {what} reads an Info sheet.", field="file")
            formulas.append((formula_name, expression))
        column_order = None
        if "column_order" in record:
            column_order = _validated_column_order(record["column_order"], column_names, dict(formulas))
        known = column_names + [formula_name for formula_name, _ in formulas]
        analyses = []
        for item in _list(record["analyses"], f"{what} analyses", MAX_ANALYSIS_NODES):
            _record(item, _ANALYSIS_KEYS, ("id", "method", "options"), f"An analysis of {what}")
            identifier = item["id"]
            if not isinstance(identifier, str) or not _LOCAL_ID.fullmatch(identifier):
                _fail("type", f"An analysis of {what} has an invalid identifier.", field="file")
            if identifier in ids:
                _fail("duplicate-id", f"The identifier {identifier} is used twice.", field="file")
            source = item.get("source")
            if source is not None:
                _record(source, _SOURCE_KEYS, ("id", "table"), f"The input of {identifier}")
                if not isinstance(source["id"], str) or not _LOCAL_ID.fullmatch(source["id"]):
                    _fail("type", f"The input of {identifier} has an invalid identifier.", field="file")
                ResultSource(str(uuid5(NAMESPACE_URL, source["id"])), source["table"])  # Same limits.
                source = (source["id"], source["table"])
            problem = _recipe_problem(item["method"], item["options"], known, root=source is None)
            if problem is not None:
                _fail(problem[0], f"{identifier} ({what}): {problem[1]}", field="file", analysis=identifier)
            label = item.get("label")
            if label is not None and not valid_label(label):
                _fail("type", f"The name of {identifier} is not valid.", field="file")
            style = item.get("style")
            if style is not None:
                if not isinstance(style, dict) or SHAPES in style or ANNOTATIONS in style:
                    _fail("type", f"The graph format of {identifier} is not valid.", field="file")
                validated_style(deepcopy(style))
                _json_value(style)
            ids[identifier] = (name, len(analyses))
            analyses.append(AnalysisSpec(identifier, item["method"], item["options"], source, label, style or None))
        tables.append(TableSpec(name, table_format, tuple(columns), roles, tuple(formulas), tuple(analyses),
                                column_order))
    if not tables:
        _fail("type", "The template has no data table.", field="file")
    if len(ids) > MAX_ANALYSIS_NODES:
        _fail("too-many", "The template exceeds the analysis node budget.", field="file")
    return tables, ids


def _parse_layouts(records, ids):
    layouts = []
    for position, record in enumerate(_list(records, "layouts", MAX_LAYOUTS), 1):
        _record(record, _LAYOUT_KEYS, ("name", "columns", "panels"), f"Layout {position}")
        panels = _list(record["panels"], f"The panels of layout {position}", 12)
        if any(not isinstance(panel, str) or panel not in ids for panel in panels):
            _fail("missing-reference", f"A panel of layout {position} refers to a missing analysis.", field="file")
        try:
            layout = Layout(record["name"], record["columns"], [ids[panel] for panel in panels],
                            record.get("paper", AUTO_PAPER), record.get("background", WHITE),
                            record.get("panel_size", "original"), record.get("axis_alignment", "none"))
        except (ValueError, TypeError) as error:
            _fail("type", f"Layout {position}: {error}", field="file")
        layouts.append(LayoutSpec(layout.name, layout.columns, tuple(panels), layout.paper, layout.background,
                                  layout.panel_size, layout.axis_alignment))
    return layouts


def _skeleton(template, *, ids=None):
    """Empty datasets with the structure of ``template``: the engine checks links and cycles on them."""
    ids = ids or {}
    identity = {}
    for table in template.tables:
        for analysis in table.analyses:
            identity[analysis.id] = ids.get(analysis.id) or str(uuid5(NAMESPACE_URL, "trama-template:" + analysis.id))
    tables = {}
    for table in template.tables:
        frame = pd.DataFrame({name: pd.Series([], dtype="Float64" if kind == "numeric" else "string")
                              for name, kind in table.columns})
        dataset = Dataset(frame, analyses=[(analysis.method, analysis.options) for analysis in table.analyses],
                          table_format=table.table_format)
        dataset.analysis_ids = {slot: identity[analysis.id] for slot, analysis in enumerate(table.analyses)}
        dataset.analysis_sources = {slot: ResultSource(identity[analysis.source[0]], analysis.source[1])
                                    for slot, analysis in enumerate(table.analyses) if analysis.source is not None}
        tables[table.name] = dataset
    return tables, identity


def read_template(path):
    """Read and validate a template. Nothing is calculated and no other file is touched.

    Raises :class:`TemplateError` (a ValueError) for a file that is too large, not JSON, of an unknown
    schema, with repeated fields, wrong types, unknown or imported analyses, or missing or cyclic links.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as error:
        raise TemplateError("io", f"The template cannot be read: {error.strerror or error}", field="file") from error
    if size > MAX_TEMPLATE_BYTES:
        _fail("too-large", "The template exceeds the 32 MiB limit.", field="file")
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_TEMPLATE_BYTES + 1)
    except OSError as error:
        raise TemplateError("io", f"The template cannot be read: {error.strerror or error}", field="file") from error
    if len(data) > MAX_TEMPLATE_BYTES:
        _fail("too-large", "The template exceeds the 32 MiB limit.", field="file")
    try:
        payload = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_object_pairs, parse_constant=_constant)
    except TemplateError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise TemplateError("json", "The file is not a Trama analysis template (invalid JSON).", field="file") from error
    if not isinstance(payload, dict) or "schema" not in payload:
        _fail("json", "The file is not a Trama analysis template.", field="file")
    if type(payload["schema"]) is not int or payload["schema"] != SCHEMA:
        _fail("schema", "This template was made by a newer version of Trama (unknown schema).", field="file",
              schema=payload["schema"] if isinstance(payload["schema"], (int, str)) else None)
    _record(payload, _ROOT_KEYS, ("schema", "tables"), "The template")
    if payload.get("kind", KIND) != KIND:
        _fail("json", "The file is not a Trama analysis template.", field="file")
    try:
        tables, ids = _parse_tables(payload["tables"])
        layouts = _parse_layouts(payload.get("layouts", []), ids)
        template = AnalysisTemplate(tuple(tables), tuple(layouts))
        for table in template.tables:
            for analysis in table.analyses:
                if analysis.source is not None and analysis.source[0] not in ids:
                    _fail("missing-reference", f"{analysis.id} reads a missing analysis.", field="file")
        validate_analysis_links(_skeleton(template)[0])
    except TemplateError:
        raise
    except (ValueError, TypeError, KeyError) as error:
        raise TemplateError("invalid", f"The template is not valid: {error}", field="file") from error
    return template


# ---------------------------------------------------------------------------
# Applying


def mapping_problems(template, sources, mapping):
    """Every reason ``mapping`` cannot be applied, as ``TemplateError`` objects (empty when it can)."""
    found = []
    tables = {table.name: table for table in template.tables}
    if not isinstance(mapping, dict):
        return [TemplateError("mapping", "The mapping must assign a source to every table.")]
    for name in mapping:
        if name not in tables:
            found.append(TemplateError("unknown-table", f"The template has no table named {name!r}.",
                                       field=name, table=name))
    for name, table in tables.items():
        entry = mapping.get(name)
        if entry is None:
            found.append(TemplateError("no-source", f"Choose a source for {name}.", field=name, table=name))
            continue
        try:
            source_name, columns = entry
        except (TypeError, ValueError):
            found.append(TemplateError("mapping", f"The mapping of {name} is not a source and its columns.",
                                       field=name, table=name))
            continue
        if source_name not in sources:
            found.append(TemplateError("no-source", f"The source {source_name!r} of {name} is not available.",
                                       field=name, table=name, source=str(source_name)))
            continue
        frame = sources[source_name]
        if not isinstance(columns, dict):
            found.append(TemplateError("mapping", f"The columns of {name} are not a mapping.", field=name, table=name))
            continue
        for column in columns:
            if column not in table.column_names:
                found.append(TemplateError("unknown-column", f"{name} has no column {column!r} to fill.",
                                           field=(name, column), table=name, column=str(column)))
        used = Counter(value for key, value in columns.items() if key in table.column_names and value)
        for column, kind in table.columns:
            chosen = columns.get(column)
            if not chosen:
                found.append(TemplateError("unmapped", f"Choose the source column for {column} in {name}.",
                                           field=(name, column), table=name, column=column))
            elif chosen not in frame.columns:
                found.append(TemplateError("missing-column", f"{source_name} has no column {chosen!r} "
                                           f"(for {column} in {name}).", field=(name, column), table=name,
                                           column=column, source=str(chosen)))
            elif used[chosen] > 1:
                found.append(TemplateError("duplicate", f"The column {chosen!r} is assigned twice in {name}.",
                                           field=(name, column), table=name, column=column, source=str(chosen)))
            elif kind == "numeric" and not _numeric(frame[chosen]):
                found.append(TemplateError("not-numeric", f"{column} in {name} needs numbers; {chosen!r} "
                                           f"contains text.", field=(name, column), table=name, column=column,
                                           source=str(chosen)))
        if len(frame) * (len(table.columns) + len(table.formulas)) > MAX_CELLS:
            found.append(TemplateError("too-large", f"The source of {name} exceeds the table size limit.",
                                       field=name, table=name))
    return found


def _numeric(series):
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return True
    present = series.dropna()
    present = present[present.astype(str).str.strip() != ""]
    return bool(pd.to_numeric(present, errors="coerce").notna().all())


def _copy_column(series, kind):
    values = series.reset_index(drop=True).copy(deep=True)
    if kind == "numeric":
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            values = values.replace("", pd.NA) if values.dtype == object or pd.api.types.is_string_dtype(values) \
                else values
            values = pd.to_numeric(values, errors="coerce", dtype_backend="numpy_nullable")
        return values
    if kind == "text" and not pd.api.types.is_string_dtype(values):
        return values.astype("string")
    if kind == "mixed":
        return values.astype(object)
    return values


def instantiate_template(template, sources, mapping, *, avoid=(), cancel=None):
    """Build new data tables and layouts from ``template`` and new data.

    ``sources`` maps a source name to a DataFrame; ``mapping`` is ``{template table: (source name,
    {template column: source column})}``. Every observed column must be assigned, a source column at most
    once per table; extra source columns are ignored. Data are copied under the canonical names, in the
    template order, with new rows from 0. Every analysis receives a new identity (never one in ``avoid``).
    Neither the template nor the sources change. Raises :class:`TemplateError` (a ValueError) when the
    mapping is incomplete or ambiguous.
    """
    problems = mapping_problems(template, sources, mapping)
    if problems:
        error = problems[0]
        raise TemplateError(error.code, str(error), field=error.field, problems=problems, **error.detail)
    taken = set(avoid)
    ids = {}
    for table in template.tables:
        for analysis in table.analyses:
            fresh = str(uuid4())
            while fresh in taken:
                fresh = str(uuid4())
            taken.add(fresh)
            ids[analysis.id] = fresh
    where = {analysis.id: (table.name, slot) for table in template.tables
             for slot, analysis in enumerate(table.analyses)}
    tables = {}
    for table in template.tables:
        _cancelled(cancel)
        source_name, columns = mapping[table.name]
        frame = sources[source_name]
        raw = pd.DataFrame({column: _copy_column(frame[columns[column]], kind) for column, kind in table.columns})
        raw.index = pd.RangeIndex(len(raw))
        if table.roles is not None:
            raw.attrs["worksheet_roles"] = deepcopy(table.roles)
        analyses = [(analysis.method, deepcopy(analysis.options)) for analysis in table.analyses]
        dataset = Dataset(raw, analyses=analyses, table_format=table.table_format)
        expressions = dict(table.formulas)
        try:
            order = formula_calculation_order(table.formulas)
        except ValueError as error:
            raise TemplateError("formula", str(error), field=table.name, table=table.name) from error
        for name in order:
            _cancelled(cancel)
            try:
                dataset.set_formula(name, expressions[name])
            except (ValueError, TypeError, ZeroDivisionError) as error:
                raise TemplateError("formula", f"The formula {name} of {table.name} cannot be calculated on "
                                    f"the new data: {error}", field=table.name, table=table.name,
                                    column=name) from error
        dataset.formulas = {name: dataset.formulas[name] for name in expressions}
        dataset.column_order = table.column_order
        dataset.analysis_ids = {slot: ids[analysis.id] for slot, analysis in enumerate(table.analyses)}
        dataset.analysis_sources = {slot: ResultSource(ids[analysis.source[0]], analysis.source[1])
                                    for slot, analysis in enumerate(table.analyses) if analysis.source is not None}
        dataset.analysis_labels = {slot: analysis.label for slot, analysis in enumerate(table.analyses)
                                   if analysis.label is not None}
        dataset.graph_styles = {slot: deepcopy(analysis.style) for slot, analysis in enumerate(table.analyses)
                                if analysis.style}
        tables[table.name] = dataset
    _cancelled(cancel)
    validate_analysis_links(tables)
    layouts = [Layout(layout.name, layout.columns, [where[panel] for panel in layout.panels], layout.paper,
                      layout.background, layout.panel_size, layout.axis_alignment) for layout in template.layouts]
    return tables, layouts


def default_mapping(template, sources, assignments=None):
    """Proposals for the assistant: a source per table (``assignments`` or the exact, unique table name),
    and per column the source column with exactly the same name when only one has it. Nothing approximate."""
    result = {}
    names = list(sources)
    for table in template.tables:
        source = (assignments or {}).get(table.name)
        if source is None and names.count(table.name) == 1:
            source = table.name
        columns = {}
        if source in sources:
            available = [str(name) for name in sources[source].columns]
            for column in table.column_names:
                if available.count(column) == 1:
                    columns[column] = column
        result[table.name] = (source, columns)
    return result


def ignored_columns(template, sources, mapping):
    """Source columns that the mapping leaves out, per template table (shown in the summary)."""
    result = {}
    for table in template.tables:
        source, columns = mapping.get(table.name, (None, {}))
        if source in sources:
            used = set(columns.values())
            result[table.name] = [str(name) for name in sources[source].columns if name not in used]
    return result
