"""Repeat a confirmed analysis on other data sheets of the same project.

Someone who keeps one worksheet per batch or experiment runs a recipe once, then repeats it on the other
sheets: each destination receives its own copy of the recipe (and, on request, of the compatible analyses that
read its results), linked to that sheet's measurements. The copies are ordinary Trama analyses: they recalculate,
follow exclusions and cell edits, are saved and reopened, exported and edited like any other.

Only analyses with an explicit contract can travel. ``CONTRACTS`` is the registry: for every supported method it
names the option fields that hold columns of the analysed table (nothing else is ever renamed, even when an
option or a literal has the same text as a column), which of those fields need numbers, and the result tables
the method produces. Two tables pass columns through (Transformed and Normalized have one column per selected
variable, with the same name): an analysis that reads them follows the renaming of its producer. The other tables
have fixed column names, so an analysis that reads them keeps its options as they are.

``plan_repeat(tables, origin, targets, follow=…)`` checks the recipe and the column choices and returns a
:class:`RepeatPlan` without copying anything. ``stage_repeat(tables, plan, cancel=…)`` returns a complete map of
sheets in which every destination is a new Dataset with the added recipes: new persistent identities, existing
slots, analyses, data, formulas, exclusions, Info and cell backgrounds untouched, every copied child linked to
the copied producer of the same destination. ``calculate_repeat`` calculates the added analyses with the real
engine before anything is written to a project. None of these functions changes its arguments or creates a
window; errors are :class:`RepeatError` (a ValueError) with a code for translation.

Layouts, result cell backgrounds, drawn shapes and free annotations stay with the original sheet. A graph format
is reused when it fits the remapped series: series named after a renamed column follow the new name, and series
the new graph does not draw are left out.
"""
from collections import Counter, deque
from copy import copy, deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

import pandas as pd

from .analysis_chain import ChainCancelled, MAX_ANALYSIS_NODES, ResultSource, result_frame
from .analysis_labels import MAX_LABEL, clean_label, valid_label
from .data import validate_analysis_links
from .graph_annotations import ANNOTATIONS
from .linked_tables import TABLES
from .graph_shapes import SHAPES
from .legacy_project_metadata import IMPORTED_METHODS, is_import_option, saved_name
from .legacy_restore import LEGACY_TITLE
from .linear_diagnostics import MEAN_BAND_SHEET, PREDICTION_BAND_SHEET, RESIDUALS_SHEET
from .pairwise_graph import SECTION as PAIRWISE_SECTION
from .worksheet_join import right_title
from .worksheet_join_app import stored_legacy_view
from . import linear_estimates, regression_range

ONE, MANY, OPTIONAL, OPTIONAL_MANY = "one", "many", "optional", "optional-many"
MAX_ROOT_ANALYSES = 256  # per data table, as for a new analysis in either window


@dataclass(frozen=True)
class ColumnField:
    """An option whose value is one column (``one``/``optional``) or a list of columns (``many``…)."""
    name: str
    kind: str
    numeric: bool = True

    @property
    def optional(self):
        return self.kind in (OPTIONAL, OPTIONAL_MANY)

    @property
    def multiple(self):
        return self.kind in (MANY, OPTIONAL_MANY)


@dataclass(frozen=True)
class Contract:
    """What travels for one method: its column fields, its result tables and which of them pass columns
    through (``{table: field}``: one column per entry of the field, with the same name)."""
    fields: tuple
    outputs: tuple
    passthrough: dict = field(default_factory=dict)

    def field(self, name):
        return next((item for item in self.fields if item.name == name), None)


CONTRACTS = {
    "Transform": Contract((ColumnField("Variables", MANY),), ("Transformed",), {"Transformed": "Variables"}),
    "Normalize": Contract((ColumnField("Variables", MANY),), ("Normalized",), {"Normalized": "Variables"}),
    "Descriptive statistics": Contract((ColumnField("Variables", MANY),), ("Summary",)),
    "Linear regression": Contract(
        (ColumnField("X", ONE), ColumnField("Y", ONE)),
        ("Regression", RESIDUALS_SHEET, regression_range.CURVE_SHEET, MEAN_BAND_SHEET, PREDICTION_BAND_SHEET,
         linear_estimates.SHEET)),
    "Nonlinear regression": Contract(
        (ColumnField("X", ONE), ColumnField("Y columns", MANY), ColumnField("Grouping variables", OPTIONAL_MANY,
                                                                              numeric=False),
         ColumnField("SD column", OPTIONAL)),
        ("Parameters", "Fit", "Residuals", regression_range.CURVE_SHEET, "Runs test", "Replicate lack of fit",
         "Band", "Band status")),
}


class RepeatError(ValueError):
    """A recipe or a choice that cannot be repeated.

    ``code`` names the reason for translation; ``sheet``, ``column``, ``method`` and ``slot`` say where.
    ``problems`` lists every blocking problem found at once (each a RepeatError)."""

    def __init__(self, code, message, *, sheet=None, column=None, method=None, slot=None, problems=(), **detail):
        super().__init__(message)
        self.code, self.sheet, self.column, self.method, self.slot = code, sheet, column, method, slot
        self.problems, self.detail = tuple(problems), detail


@dataclass(frozen=True)
class Step:
    """One analysis of the recipe, in calculation order. ``parent`` is the index of the step it reads."""
    table: str
    slot: int
    method: str
    options: dict
    parent: int | None = None
    source_table: str | None = None
    label: str | None = None
    style: dict | None = None
    uid: str | None = None


@dataclass(frozen=True)
class Requirement:
    """A column of the origin sheet the recipe reads, with the fields that read it."""
    column: str
    fields: tuple          # ((step index, field name), …)
    numeric: bool


@dataclass(frozen=True)
class Skipped:
    """A downstream analysis that does not travel, and why."""
    table: str
    slot: int
    method: str
    code: str
    message: str


@dataclass(frozen=True)
class Recipe:
    origin: tuple
    steps: tuple
    required: tuple
    skipped: tuple = ()

    @property
    def columns(self):
        return tuple(item.column for item in self.required)


@dataclass(frozen=True)
class Target:
    """The copy of the recipe for one destination sheet."""
    title: str
    columns: dict          # {origin column: destination column}
    slots: tuple           # new slot of every step, in step order
    labels: tuple          # literal name given to each copy, or None for the usual name
    options: tuple         # remapped options of every step
    styles: tuple          # remapped graph format of every step, or None
    base: int              # analyses the destination had when the plan was made


@dataclass(frozen=True)
class RepeatPlan:
    recipe: Recipe
    targets: tuple

    @property
    def analysis_count(self):
        return len(self.recipe.steps) * len(self.targets)

    def target(self, title):
        return next(target for target in self.targets if target.title == title)


# ---------------------------------------------------------------------------
# Reading a recipe


def _cancelled(cancel):
    if cancel is None:
        return
    stop = cancel.is_set() if hasattr(cancel, "is_set") else cancel()
    if stop:
        raise ChainCancelled


def _values(value):
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _field_columns(contract, options):
    """``[(field, column), …]`` of the columns the options read, in field order."""
    found = []
    for item in contract.fields:
        value = options.get(item.name)
        if value is None or value == "" or value == []:
            continue
        for column in _values(value) if item.multiple else [value]:
            found.append((item, column))
    return found


def _recipe_problem(method, options, *, root):
    """Why one analysis cannot travel, as ``(code, message)``, or None."""
    if not isinstance(method, str) or saved_name(method) in IMPORTED_METHODS:
        return "imported", "This analysis shows an imported view; analyse the data again first."
    contract = CONTRACTS.get(method)
    if contract is None:
        return "unsupported", (f"{method} cannot be repeated yet. Supported: "
                               f"{', '.join(CONTRACTS)}.")
    if not isinstance(options, dict):
        return "invalid-options", "The saved options of this analysis are not valid."
    if any(isinstance(key, str) and is_import_option(key) for key in options) or LEGACY_TITLE in options:
        return "external", "This analysis keeps data of an imported file; analyse the data again first."
    if right_title(options) is not None:
        return "other-sheet", "This analysis reads another worksheet."
    if options.get(PAIRWISE_SECTION):
        return "other-analysis", "This graph draws comparisons of another analysis."
    for item in contract.fields:
        value = options.get(item.name)
        if value is None or value == "" or value == []:
            if not item.optional:
                return "invalid-options", f"The field {item.name} of this analysis is empty."
            continue
        values = value if item.multiple else [value]
        if (item.multiple and not isinstance(value, list)) or any(not isinstance(v, str) or not v for v in values):
            return "invalid-options", f"The field {item.name} of this analysis is not a column choice."
        if len(set(values)) != len(values):
            return "invalid-options", f"The field {item.name} of this analysis repeats a column."
    return None


def _identities(tables):
    found = {}
    for title, dataset in tables.items():
        for slot, identifier in dataset.analysis_ids.items():
            if 0 <= slot < len(dataset.analyses):
                found.setdefault(identifier, (title, slot))
    return found


def _children(tables):
    """``{parent identity: [(title, slot), …]}`` through result inputs, in project order."""
    children = {}
    for title, dataset in tables.items():
        for slot, source in sorted(dataset.analysis_sources.items()):
            if 0 <= slot < len(dataset.analyses):
                children.setdefault(source.analysis_id, []).append((title, slot))
    return children


def _passthrough(step, recipe_steps):
    """Columns a step's input passes through from the origin sheet, as ``{input column: origin column}``.

    For the first step this is the identity on the sheet; for a child it follows the parent's pass-through
    table, so a child of Transformed reads the same variables as its producer, already renamed."""
    if step.parent is None:
        return None
    parent = recipe_steps[step.parent]
    contract = CONTRACTS[parent.method]
    name = contract.passthrough.get(step.source_table)
    if name is None:
        return {}
    upstream = _passthrough(parent, recipe_steps)
    columns = _values(parent.options.get(name) or [])
    return {column: (column if upstream is None else upstream.get(column)) for column in columns}


def _child_problem(step, recipe_steps):
    parent = recipe_steps[step.parent]
    contract = CONTRACTS[parent.method]
    if step.source_table not in contract.outputs:
        return "output", (f'{step.method} reads "{step.source_table}", which {parent.method} does not provide '
                          "in every copy.")
    through = _passthrough(step, recipe_steps)
    if step.source_table in contract.passthrough:
        for item, column in _field_columns(CONTRACTS[step.method], step.options):
            if through.get(column) is None:
                return "output", (f'{step.method} reads the column "{column}" of {step.source_table}, which does '
                                  "not come from the repeated sheet.")
    return None


def describe_repeat(tables, origin, *, follow=False):
    """The :class:`Recipe` that would be repeated from ``origin`` (``(sheet title, slot)``).

    With ``follow`` the compatible analyses that read its results (directly or further down) come along, in
    calculation order; the others are listed in ``skipped`` with the reason. Raises RepeatError when the
    selected analysis itself cannot be repeated."""
    try:
        title, slot = origin
    except (TypeError, ValueError):
        raise RepeatError("origin", "Select an analysis result or graph to repeat.") from None
    if title not in tables or type(slot) is not int or not 0 <= slot < len(tables[title].analyses):
        raise RepeatError("origin", "Select an analysis result or graph to repeat.")
    dataset = tables[title]
    method, options = dataset.analyses[slot]
    if dataset.analysis_sources.get(slot) is not None:
        raise RepeatError("reads-result", "This analysis reads the results of another analysis: repeat the "
                          "analysis it comes from and include the following steps.", sheet=title, method=method,
                          slot=slot)
    if stored_legacy_view(dataset):
        raise RepeatError("read-only", "This sheet keeps an archived view: copy its data into a new data table "
                          "first.", sheet=title, method=method, slot=slot)
    problem = _recipe_problem(method, options, root=True)
    if problem is not None:
        raise RepeatError(problem[0], problem[1], sheet=title, method=method, slot=slot)
    available = set(map(str, dataset.columns))
    contract = CONTRACTS[method]
    missing = [column for _, column in _field_columns(contract, options) if column not in available]
    if missing:
        raise RepeatError("missing-column", f"The analysis reads columns that are not in {title}: "
                          f"{', '.join(dict.fromkeys(missing))}.", sheet=title, method=method, slot=slot)

    def step_of(table, index, parent=None, source=None):
        data = tables[table]
        recipe_method, recipe_options = data.analyses[index]
        return Step(table, index, recipe_method, deepcopy(recipe_options), parent, source,
                    data.analysis_labels.get(index), deepcopy(data.graph_styles.get(index)),
                    data.analysis_ids.get(index))

    steps = [step_of(title, slot)]
    skipped = []
    if follow and steps[0].uid is not None:
        children = _children(tables)
        identities = _identities(tables)
        pending = deque([0])
        visited = {(title, slot)}
        while pending:
            index = pending.popleft()
            for child in children.get(steps[index].uid, ()):
                if child in visited:
                    continue
                visited.add(child)
                child_title, child_slot = child
                source = tables[child_title].analysis_sources[child_slot]
                candidate = step_of(child_title, child_slot, index, source.table)
                problem = _recipe_problem(candidate.method, candidate.options, root=False)
                if problem is None:
                    problem = _child_problem(candidate, steps)
                if problem is not None:
                    skipped.append(Skipped(child_title, child_slot, candidate.method, *problem))
                    for below in _descendants(child, tables, children, identities):
                        if below not in visited:
                            visited.add(below)
                            method_below = tables[below[0]].analyses[below[1]][0]
                            skipped.append(Skipped(*below, method_below, "parent-skipped",
                                                   "It reads an analysis that is not repeated."))
                    continue
                steps.append(candidate)
                pending.append(len(steps) - 1)
    required, by_column = [], {}
    for item, column in _field_columns(contract, steps[0].options):
        if column not in by_column:
            by_column[column] = [[], False]
            required.append(column)
        by_column[column][0].append((0, item.name))
        by_column[column][1] |= item.numeric
    for index, step in enumerate(steps[1:], 1):
        through = _passthrough(step, steps)
        for item, column in _field_columns(CONTRACTS[step.method], step.options):
            source_column = through.get(column) if through else None
            if source_column is not None:
                by_column[source_column][0].append((index, item.name))
                by_column[source_column][1] |= item.numeric
    requirements = tuple(Requirement(column, tuple(by_column[column][0]), by_column[column][1])
                         for column in required)
    return Recipe((title, slot), tuple(steps), requirements, tuple(skipped))


def _descendants(node, tables, children, identities):
    title, slot = node
    found, pending = [], deque([tables[title].analysis_ids.get(slot)])
    while pending:
        identifier = pending.popleft()
        for child in children.get(identifier, ()):
            if child not in found:
                found.append(child)
                pending.append(tables[child[0]].analysis_ids.get(child[1]))
    return found


# ---------------------------------------------------------------------------
# Destinations


def _numeric(series):
    if pd.api.types.is_bool_dtype(series):
        return False
    if pd.api.types.is_numeric_dtype(series):
        return True
    present = series.dropna()
    present = present[present.astype(str).str.strip() != ""]
    return bool(pd.to_numeric(present, errors="coerce").notna().all())


def destination_problem(tables, recipe, title):
    """Why ``title`` can never receive the recipe (whatever the columns), as a RepeatError, or None."""
    if title not in tables:
        return RepeatError("unknown-sheet", f'The project has no data sheet named "{title}".', sheet=title)
    if title == recipe.origin[0]:
        return RepeatError("source-sheet", "The recipe already runs on this sheet.", sheet=title)
    dataset = tables[title]
    if stored_legacy_view(dataset):
        return RepeatError("read-only", "This sheet keeps an archived read-only view.", sheet=title)
    roots = len(dataset.analyses) - len(dataset.analysis_sources)
    if roots + 1 > MAX_ROOT_ANALYSES:
        return RepeatError("budget", f"A table supports up to {MAX_ROOT_ANALYSES} analyses.", sheet=title,
                           limit=MAX_ROOT_ANALYSES)
    return None


def propose_columns(recipe, dataset):
    """For the assistant: the destination column with exactly the same name, when there is one. Nothing
    approximate is ever proposed; a similar name is used only when the user chooses it."""
    available = [str(name) for name in dataset.columns]
    return {column: column for column in recipe.columns if available.count(column) == 1}


def target_problems(tables, recipe, title, columns):
    """Every reason the column choice ``columns`` (``{origin column: destination column}``) of ``title``
    cannot be applied, as RepeatError objects (empty when it can)."""
    problem = destination_problem(tables, recipe, title)
    if problem is not None:
        return [problem]
    if not isinstance(columns, dict):
        return [RepeatError("mapping", "Choose a destination column for every column of the recipe.", sheet=title)]
    dataset = tables[title]
    found = []
    for column in columns:
        if column not in recipe.columns:
            found.append(RepeatError("unknown-column", f'The recipe does not read a column named "{column}".',
                                     sheet=title, column=str(column)))
    available = [str(name) for name in dataset.columns]
    used = Counter(value for key, value in columns.items() if key in recipe.columns and value)
    frame = None
    for requirement in recipe.required:
        chosen = columns.get(requirement.column)
        if not chosen:
            found.append(RepeatError("unmapped", f"Choose the column of {title} for {requirement.column}.",
                                     sheet=title, column=requirement.column))
        elif not isinstance(chosen, str) or chosen not in available:
            found.append(RepeatError("missing-column", f'{title} has no column "{chosen}" (for '
                                     f"{requirement.column}).", sheet=title, column=requirement.column,
                                     chosen=str(chosen)))
        elif used[chosen] > 1:
            found.append(RepeatError("duplicate", f'The column "{chosen}" of {title} is chosen for more than one '
                                     "column of the recipe.", sheet=title, column=requirement.column, chosen=chosen))
        elif requirement.numeric:
            if chosen in dataset.raw.columns:
                values = dataset.raw[chosen]
            else:
                if frame is None:
                    try:
                        frame = dataset.frame()
                    except (ValueError, TypeError, ZeroDivisionError) as error:
                        found.append(RepeatError("formula", f"The formulas of {title} cannot be calculated: "
                                                 f"{error}", sheet=title))
                        break
                values = frame[chosen]
            if isinstance(values, pd.DataFrame) or not _numeric(values):
                found.append(RepeatError("not-numeric", f'{requirement.column} needs numbers; "{chosen}" of {title} '
                                         "contains text.", sheet=title, column=requirement.column, chosen=chosen))
    return found


def _rename(value, columns, item):
    if item.multiple:
        return [columns.get(column, column) for column in value]
    return columns.get(value, value)


def remap_options(step, options, columns):
    """The options of ``step`` with only its column fields renamed by ``columns``."""
    result = deepcopy(options)
    for item in CONTRACTS[step.method].fields:
        value = result.get(item.name)
        if value is None or value == "" or value == []:
            continue
        result[item.name] = _rename(value, columns, item)
    return result


def remap_style(style, columns):
    """A graph format for the copy: drawings stay behind and series named after a renamed column follow it."""
    if not style:
        return None
    style = deepcopy(style)
    style.pop(SHAPES, None)
    style.pop(ANNOTATIONS, None)
    style.pop(TABLES, None)  # A linked table reads the sheet or result it was made for, not a repetition of it.
    series = style.get("series")
    if isinstance(series, dict):
        renamed = {}
        for key, options in series.items():
            kind, _, rest = key.partition(":") if isinstance(key, str) else (key, "", "")
            number, _, label = rest.partition(":")
            if label in columns:
                key = f"{kind}:{number}:{columns[label]}"
            renamed[key] = options
        style["series"] = renamed
    return style or None


def _display_names(dataset, title):
    names = set()
    for slot, (method, options) in enumerate(dataset.analyses):
        source = dataset.analysis_sources.get(slot)
        names.add(dataset.analysis_labels.get(slot) or (options.get(LEGACY_TITLE) if isinstance(options, dict)
                                                        else None)
                  or f"{method} of {source.table if source is not None else title}")
    return names


def _unique_label(base, taken):
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f" ({number})"
        text = base if len(base) + len(suffix) <= MAX_LABEL else base[:MAX_LABEL - len(suffix) - 1] + "…"
        if text + suffix not in taken:
            return text + suffix
        number += 1


def _target(tables, recipe, title, columns):
    dataset = tables[title]
    base = len(dataset.analyses)
    taken = _display_names(dataset, title)
    options, labels, styles = [], [], []
    for index, step in enumerate(recipe.steps):
        if step.parent is None:
            rename = {column: columns[column] for column in recipe.columns}
        else:
            name = CONTRACTS[recipe.steps[step.parent].method].passthrough.get(step.source_table)
            rename = {}
            if name is not None:
                # The pass-through table of the copied producer has the producer's renamed columns, in order.
                before = _values(recipe.steps[step.parent].options.get(name) or [])
                after = _values(options[step.parent].get(name) or [])
                rename = dict(zip(before, after))
        options.append(remap_options(step, step.options, rename))
        styles.append(remap_style(step.style, rename))
        shown = step.label or f"{step.method} of {step.source_table if step.parent is not None else title}"
        label = _unique_label(shown, taken)
        taken.add(label)
        labels.append(clean_label(label) if (step.label is not None or label != shown) else None)
    slots = tuple(range(base, base + len(recipe.steps)))
    return Target(title, dict(columns), slots, tuple(labels), tuple(options), tuple(styles), base)


def plan_repeat(tables, origin, targets, *, follow=False):
    """Prepare the repetition of ``origin`` on ``targets`` (``{sheet title: {origin column: column}}``).

    ``follow`` brings the compatible downstream analyses along. Nothing is copied and nothing changes. Raises
    RepeatError (a ValueError) for a recipe that cannot travel or for any incomplete, duplicate, unknown or
    incompatible choice, with every problem in ``problems``."""
    recipe = describe_repeat(tables, origin, follow=follow)
    if not isinstance(targets, dict) or not targets:
        raise RepeatError("no-targets", "Choose at least one data sheet.")
    problems = []
    for title, columns in targets.items():
        problems.extend(target_problems(tables, recipe, title, columns))
    added = len(recipe.steps) * len(targets)
    total = sum(len(dataset.analyses) for dataset in tables.values())
    if not problems and total + added > MAX_ANALYSIS_NODES:
        problems.append(RepeatError("budget", f"A project supports up to {MAX_ANALYSIS_NODES:,} analysis nodes.",
                                    limit=MAX_ANALYSIS_NODES))
    if problems:
        first = problems[0]
        raise RepeatError(first.code, str(first), sheet=first.sheet, column=first.column, problems=problems,
                          **first.detail)
    return RepeatPlan(recipe, tuple(_target(tables, recipe, title, columns) for title, columns in targets.items()))


# ---------------------------------------------------------------------------
# Staging


def _detached(dataset):
    """A new Dataset with the same content and containers of its own; the frame is shared copy-on-write."""
    twin = copy(dataset)
    twin.raw = dataset.raw.copy(deep=False)
    twin.formulas = dict(dataset.formulas)
    twin.analyses = [(method, deepcopy(options)) for method, options in dataset.analyses]
    twin.excluded = set(dataset.excluded)
    twin.graph_styles = deepcopy(dataset.graph_styles)
    twin.info = dict(dataset.info)
    twin.analysis_ids = dict(dataset.analysis_ids)
    twin.analysis_sources = dict(dataset.analysis_sources)
    twin.analysis_labels = dict(dataset.analysis_labels)
    twin.cell_backgrounds = dict(dataset.cell_backgrounds)
    twin.result_backgrounds = deepcopy(dataset.result_backgrounds)
    twin.text_styles = dataset.text_styles
    twin.result_text_styles = {slot: dict(sheets) for slot, sheets in dataset.result_text_styles.items()}
    return twin


def _check_unchanged(tables, plan):
    origin_title, origin_slot = plan.recipe.origin
    for step in plan.recipe.steps:
        dataset = tables.get(step.table)
        if (dataset is None or not step.slot < len(dataset.analyses)
                or tuple(dataset.analyses[step.slot]) != (step.method, step.options)):
            raise RepeatError("changed", "The project changed while the repetition was prepared: start again.",
                              sheet=step.table)
    for target in plan.targets:
        dataset = tables.get(target.title)
        if dataset is None or len(dataset.analyses) != target.base:
            raise RepeatError("changed", "The project changed while the repetition was prepared: start again.",
                              sheet=target.title)
    if origin_title not in tables:
        raise RepeatError("changed", "The project changed while the repetition was prepared: start again.")


def stage_repeat(tables, plan, *, cancel=None):
    """A complete map of sheets with the recipes of ``plan`` added, ready to be verified and committed.

    Destinations are new Dataset objects; the other sheets are the same objects (nothing changes in them). Every
    added analysis receives a new persistent identity and every copied child reads the copied producer of the
    same destination. ``cancel`` is a predicate without arguments (or an Event): it ends the work with
    ChainCancelled. The input never changes."""
    if not isinstance(plan, RepeatPlan):
        raise RepeatError("plan", "Prepare the repetition first.")
    _check_unchanged(tables, plan)
    taken = set(_identities(tables))
    for dataset in tables.values():
        taken.update(dataset.analysis_ids.values())
    staged = dict(tables)
    for target in plan.targets:
        _cancelled(cancel)
        twin = _detached(tables[target.title])
        ids = []
        for index, step in enumerate(plan.recipe.steps):
            _cancelled(cancel)
            identifier = str(uuid4())
            while identifier in taken:
                identifier = str(uuid4())
            taken.add(identifier)
            ids.append(identifier)
            slot = target.slots[index]
            twin.analyses.append((step.method, deepcopy(target.options[index])))
            twin.analysis_ids[slot] = identifier
            if step.parent is not None:
                twin.analysis_sources[slot] = ResultSource(ids[step.parent], step.source_table)
            if target.labels[index] is not None and valid_label(target.labels[index]):
                twin.analysis_labels[slot] = target.labels[index]
            if target.styles[index]:
                twin.graph_styles[slot] = deepcopy(target.styles[index])
        if twin.analysis_sources:  # a linked table keeps every identity, as the windows persist it
            for slot in range(len(twin.analyses)):
                if slot not in twin.analysis_ids:
                    identifier = str(uuid4())
                    while identifier in taken:
                        identifier = str(uuid4())
                    taken.add(identifier)
                    twin.analysis_ids[slot] = identifier
        staged[target.title] = twin
    _cancelled(cancel)
    validate_analysis_links(staged)
    return staged


# ---------------------------------------------------------------------------
# Calculation


@dataclass
class Calculated:
    """Results of the added analyses: ``results[(title, slot)]`` and the notes for the summary."""
    results: dict
    styles_dropped: list = field(default_factory=list)   # (title, slot) whose format did not fit and was left out
    series_dropped: list = field(default_factory=list)   # (title, slot) whose format kept only some series


def fit_style(figure, style):
    """The part of ``style`` the new graph can use: None when the format does not fit at all."""
    from .presentation import graph_series, validate_graph_style, validated_style

    if not style or figure is None or not figure.axes:
        return None, False
    from .point_style import POINTS

    style = deepcopy(style)
    axes = figure.axes[0]
    # The formatting of a single point belongs to one row of one worksheet: another sheet has other rows.
    reduced = style.pop(POINTS, None) is not None
    series = style.get("series")
    if isinstance(series, dict) and series:
        keys = {item.key for item in graph_series(axes)}
        kept = {key: options for key, options in series.items() if key in keys}
        reduced = reduced or len(kept) != len(series)
        if kept:
            style["series"] = kept
        else:
            style.pop("series")
    try:
        validated_style(style)
        validate_graph_style(axes, style)
    except (ValueError, TypeError, KeyError):
        return None, True
    return (style or None), reduced


def calculate_repeat(staged, plan, inputs, *, compute=None, cancel=None, progress=None):
    """Calculate every added analysis of every destination of ``plan`` in ``staged`` with the real engine.

    ``inputs[title]`` is the analysed frame of a destination (excluded cells masked), taken by the caller.
    ``compute(title, slot, method, options, style, frame, result)`` may finish a result as the window does
    (format, comparisons); by default the result is returned as calculated. Formats that do not fit the new graph
    are reduced or left out in ``staged``. Raises RepeatError("calculation") naming the sheet, the method and the
    problem of the first analysis that cannot be calculated, or ChainCancelled."""
    from .workbench import analyse

    results = {}
    outcome = Calculated(results)
    total = plan.analysis_count
    done = 0
    if progress is not None:
        progress(0, total)
    event = cancel if hasattr(cancel, "is_set") else None
    for target in plan.targets:
        dataset = staged[target.title]
        for index, step in enumerate(plan.recipe.steps):
            _cancelled(cancel)
            slot = target.slots[index]
            method, options = dataset.analyses[slot]
            try:
                if step.parent is None:
                    frame = inputs[target.title].copy(deep=True)
                else:
                    frame = result_frame(results[target.title, target.slots[step.parent]], step.source_table)
                result = analyse(method, frame, deepcopy(options), cancel=event)
                style = dataset.graph_styles.get(slot)
                if style:
                    fitted, reduced = fit_style(result.figure, style)
                    if fitted is None:
                        dataset.graph_styles.pop(slot, None)
                        outcome.styles_dropped.append((target.title, slot))
                    else:
                        dataset.graph_styles[slot] = fitted
                        if reduced:
                            outcome.series_dropped.append((target.title, slot))
                    style = fitted
                if compute is not None:
                    result = compute(target.title, slot, method, options, style, frame, result)
            except ChainCancelled:
                raise
            except Exception as error:
                message = str(error) or type(error).__name__
                raise RepeatError("calculation", f"{target.title}: {method} cannot be calculated. {message}",
                                  sheet=target.title, method=method, slot=slot, reason=message) from error
            results[target.title, slot] = result
            done += 1
            if progress is not None:
                progress(done, total)
    _cancelled(cancel)
    return outcome


def project_state(tables, titles):
    """A token of what the repetition reads and writes; a different token at commit means the project changed."""
    state = []
    for title in sorted(titles):
        dataset = tables.get(title)
        if dataset is None:
            state.append((title, None))
            continue
        try:
            digest = int(pd.util.hash_pandas_object(dataset.raw, index=True).sum())
        except (TypeError, ValueError):
            digest = None
        state.append((title, id(dataset), id(dataset.raw), dataset.raw.shape, tuple(map(str, dataset.raw.columns)),
                      digest, tuple(dataset.formulas.items()), tuple(sorted(dataset.excluded)), dataset.column_order,
                      len(dataset.analyses), repr(dataset.analyses)))
    return tuple(state)
