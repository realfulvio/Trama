"""Rename and merge category levels of a worksheet column in a single edit."""

from collections import Counter, deque
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from . import ttest_options, worksheet_join
from .analysis_chain import ResultSource, result_frame
from .category_order import MAX_LEVELS, WORKSHEET_ORDERS, ranks, validated_orders
from .graph_legend import MAX_LEGEND_KEY_LENGTH, typed_group_token
from .i18n import tr, ui
from .select_transform import CALCULATED, FILTERS, SELECT_TRANSFORM
from .variable_types import VARIABLE_TYPES, inferred_type
from .worksheet_join_app import stored_legacy_view


@dataclass(frozen=True)
class LevelEntry:
    """One distinct non-missing level observed in a worksheet column."""

    token: str
    value: object
    raw_label: str
    display_label: str
    count: int
    ambiguous: bool = False


@dataclass(frozen=True)
class MergeGroup:
    """Multiple source levels mapped onto the same target label."""

    target_token: str
    target_label: str
    sources: tuple[LevelEntry, ...]
    total_count: int


@dataclass(frozen=True)
class RecipeBlocker:
    """An analysis recipe that explicitly depends on one or more removed levels."""

    recipe_name: str
    field_label: str
    levels: tuple[str, ...]
    source_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class LevelEditPlan:
    """Validated level rename/merge and category-order changes ready to apply."""

    column: str
    value_map: dict[str, object]
    token_map: dict[str, str]
    new_order: list[str] | None
    merges: tuple[MergeGroup, ...]
    removed_labels: frozenset[str]
    has_changes: bool


class LevelEditError(ValueError):
    """Validation or blocking error carrying the offending level token when available."""

    def __init__(self, message, *, token=None, code="invalid"):
        super().__init__(message)
        self.token = token
        self.code = code


def _is_missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(math.isnan(value))
    try:
        result = pd.isna(value)
        return bool(result) if isinstance(result, (bool, np.bool_)) else False
    except (TypeError, ValueError):
        return False


def can_rename_levels(dataset, column):
    """Return True when ``column`` in ``dataset`` is an editable text/categorical multivariable column."""
    if dataset.table_format != "multivariable" or stored_legacy_view(dataset):
        return False
    if column not in dataset.raw.columns:
        return False
    stored = dataset.raw.attrs.get(VARIABLE_TYPES, {}).get(column)
    if stored in {"text", "categorical"}:
        return True
    if stored == "numeric":
        return False
    return inferred_type(dataset.raw[column]) != "numeric"


def _token_kind(token):
    return token.split(":", 1)[0]


def _build_entries(items):
    raw_counts = Counter(raw_label for _, _, raw_label, _ in items)
    stripped_counts = Counter(raw_label.strip() for token, _, raw_label, _ in items if token.startswith("str:"))
    entries = []
    for token, value, raw_label, count in items:
        is_str = token.startswith("str:")
        has_edge_space_or_ctrl = is_str and (
            raw_label != raw_label.strip() or any(ch in raw_label for ch in ("\t", "\n", "\r"))
        )
        collides_raw = raw_counts[raw_label] > 1
        collides_stripped = is_str and stripped_counts[raw_label.strip()] > 1
        ambiguous = collides_raw or has_edge_space_or_ctrl or collides_stripped
        if is_str and ambiguous:
            display_label = repr(raw_label)
        elif not is_str and collides_raw:
            display_label = f"{raw_label} ({_token_kind(token)})"
        else:
            display_label = raw_label
        entries.append(LevelEntry(
            token=token,
            value=value,
            raw_label=raw_label,
            display_label=display_label,
            count=count,
            ambiguous=ambiguous,
        ))
    return entries


def scan_column_levels(frame, column):
    """Scan non-missing values of ``column`` into ``LevelEntry`` objects in first-seen order."""
    if column not in frame.columns:
        raise ValueError(f"Unknown column: {column}")
    series = frame[column]
    dtype = series.dtype

    if isinstance(dtype, pd.StringDtype) or (
        isinstance(dtype, pd.CategoricalDtype) and all(isinstance(cat, str) for cat in dtype.categories)
    ):
        counts = series.value_counts(dropna=True, sort=False)
        items = []
        for raw_value, count in counts.items():
            int_count = int(count)
            if int_count <= 0:
                continue
            value = str(raw_value)
            token = f"str:{value}"
            if len(token) > MAX_LEGEND_KEY_LENGTH:
                raise ValueError(tr("worksheet_order.limit", limit=MAX_LEVELS))
            items.append((token, value, value, int_count))
            if len(items) > MAX_LEVELS:
                raise ValueError(tr("worksheet_order.limit", limit=MAX_LEVELS))
        return _build_entries(items)

    values_by_token = {}
    counts_by_token = {}
    labels_by_token = {}
    for value in series.to_numpy(dtype=object):
        if _is_missing(value):
            continue
        if type(value) is str:
            token = f"str:{value}"
        else:
            token = typed_group_token(value)
        if token not in counts_by_token:
            if len(token) > MAX_LEGEND_KEY_LENGTH:
                raise ValueError(tr("worksheet_order.limit", limit=MAX_LEVELS))
            if len(counts_by_token) >= MAX_LEVELS:
                raise ValueError(tr("worksheet_order.limit", limit=MAX_LEVELS))
            values_by_token[token] = value.item() if isinstance(value, np.generic) else value
            labels_by_token[token] = str(value)
            counts_by_token[token] = 1
        else:
            counts_by_token[token] += 1

    items = [
        (token, values_by_token[token], labels_by_token[token], counts_by_token[token])
        for token in counts_by_token
    ]
    return _build_entries(items)


def _deduplicate(tokens):
    return list(dict.fromkeys(tokens))


class LevelEditDraft:
    """Editable draft holding both level renames/merges and display order before applying."""

    def __init__(self, dataset, column):
        self.column = column
        self.can_rename = can_rename_levels(dataset, column)
        self.automatic = scan_column_levels(dataset.raw, column)
        self.saved = list(dataset.raw.attrs.get(WORKSHEET_ORDERS, {}).get(column, ()))
        priority = ranks(dataset.raw, column)
        self.initial = sorted(self.automatic, key=lambda entry: priority.get(entry.token, len(priority)))
        self.levels = list(self.initial)
        self.reset = False
        self._by_token = {entry.token: entry for entry in self.automatic}
        self._edits = {}

    def target_text(self, token):
        if token in self._edits:
            return self._edits[token]
        return self._by_token[token].raw_label

    def set_target(self, token, text):
        if token not in self._by_token:
            raise KeyError(token)
        if not self.can_rename:
            if text == self._by_token[token].raw_label:
                self._edits.pop(token, None)
                return
            raise LevelEditError(tr("category_levels.error.ineligible"), token=token, code="ineligible")
        if token == f"str:{text}":
            self._edits.pop(token, None)
        else:
            self._edits[token] = text

    def apply_mapping(self, mapping):
        """Convenience helper for programmatic callers/tests using tokens or unambiguous raw labels."""
        by_raw = {}
        for entry in self.levels:
            by_raw.setdefault(entry.raw_label, []).append(entry.token)
        for key, target in mapping.items():
            if key in self._by_token:
                self.set_target(key, target)
            elif key in by_raw and len(by_raw[key]) == 1:
                self.set_target(by_raw[key][0], target)
            else:
                raise KeyError(key)

    def move(self, row, step):
        target = row + step
        if not (0 <= row < len(self.levels) and 0 <= target < len(self.levels)):
            return row
        self.levels[row], self.levels[target] = self.levels[target], self.levels[row]
        self.reset = False
        return target

    def restore_automatic(self):
        self.levels = list(self.automatic)
        self.reset = True

    def has_pending_renames(self):
        return bool(self._edits)

    def result(self):
        """Compatibility helper returning only the order change when no renames exist."""
        plan = self.validate()
        return plan.new_order

    def validate(self):
        if self._edits and not self.can_rename:
            first_token = next(iter(self._edits))
            raise LevelEditError(tr("category_levels.error.ineligible"), token=first_token, code="ineligible")

        token_map = {}
        value_map = {}
        target_labels = {}
        grouped = {}
        new_labels = set()

        for entry in self.levels:
            token = entry.token
            if token in self._edits:
                text = self._edits[token]
                if not isinstance(text, str) or text == "":
                    raise LevelEditError(
                        tr("category_levels.error.empty", level=entry.display_label),
                        token=token,
                        code="empty",
                    )
                target_token = f"str:{text}"
                if len(target_token) > MAX_LEGEND_KEY_LENGTH:
                    raise LevelEditError(
                        tr("category_levels.error.too_long", level=entry.display_label,
                           limit=MAX_LEGEND_KEY_LENGTH - 4),
                        token=token,
                        code="too_long",
                    )
                target_value = text
                target_label = text
            else:
                target_token = token
                target_value = entry.value
                target_label = entry.raw_label

            token_map[token] = target_token
            if target_token != token:
                value_map[token] = target_value
            target_labels.setdefault(target_token, target_label)
            grouped.setdefault(target_token, []).append(entry)
            new_labels.add(target_label)

        merges = tuple(
            MergeGroup(
                target_token=target_token,
                target_label=target_labels[target_token],
                sources=tuple(sources),
                total_count=sum(item.count for item in sources),
            )
            for target_token, sources in grouped.items()
            if len(sources) >= 2
        )

        old_labels = {entry.raw_label for entry in self.levels}
        removed_labels = frozenset(old_labels - new_labels)

        initial_tokens = [entry.token for entry in self.initial]
        current_tokens = [entry.token for entry in self.levels]
        if self.reset:
            new_order = [] if self.saved else None
        elif current_tokens != initial_tokens:
            new_order = _deduplicate(token_map[token] for token in current_tokens)
        elif self.saved and value_map:
            mapped_saved = _deduplicate(token_map.get(token, token) for token in self.saved)
            new_order = mapped_saved if mapped_saved != self.saved else None
        else:
            new_order = None

        has_changes = bool(value_map) or new_order is not None
        return LevelEditPlan(
            column=self.column,
            value_map=value_map,
            token_map=token_map,
            new_order=new_order,
            merges=merges,
            removed_labels=removed_labels,
            has_changes=has_changes,
        )


def apply_level_plan(dataset, plan):
    """Apply ``plan`` to ``dataset`` in a single step, preserving types, exclusions, formats, and metadata."""
    if not plan.has_changes:
        return
    raw = dataset.raw.copy(deep=False)
    column = plan.column
    if plan.value_map:
        series = raw[column]
        dtype = series.dtype
        if isinstance(dtype, pd.StringDtype) or (
            isinstance(dtype, pd.CategoricalDtype) and all(isinstance(cat, str) for cat in dtype.categories)
        ):
            str_map = {token[4:]: str(target) for token, target in plan.value_map.items() if token.startswith("str:")}
            codes, uniques = pd.factorize(series, sort=False)
            mapped_uniques = np.array([str_map.get(str(value), str(value)) for value in uniques], dtype=object)
            result = np.empty(len(series), dtype=object)
            valid = codes >= 0
            result[valid] = mapped_uniques[codes[valid]]
            result[~valid] = pd.NA
            target_dtype = dtype if isinstance(dtype, pd.StringDtype) else "string"
            raw[column] = pd.Series(result, index=series.index, name=series.name, dtype=target_dtype)
        else:
            updated = []
            value_map = plan.value_map
            for orig in series.to_numpy(dtype=object):
                if _is_missing(orig):
                    updated.append(orig)
                else:
                    token = f"str:{orig}" if type(orig) is str else typed_group_token(orig)
                    updated.append(value_map.get(token, orig))
            raw[column] = pd.Series(updated, index=series.index, name=series.name, dtype=object)

    orders = dict(raw.attrs.get(WORKSHEET_ORDERS, {}))
    if plan.new_order is not None:
        if plan.new_order:
            orders[column] = list(plan.new_order)
            validated_orders(orders, raw.columns)
        else:
            orders.pop(column, None)
        if orders:
            raw.attrs[WORKSHEET_ORDERS] = orders
        else:
            raw.attrs.pop(WORKSHEET_ORDERS, None)

    dataset.raw = raw


# -- Recipe dependency & blocker inspection ------------------------------------------------------

PASSTHROUGH_TABLES = {worksheet_join.METHOD: worksheet_join.JOINED, SELECT_TRANSFORM: "Selected data"}

def _run_name(run):
    if getattr(run, "label", None):
        return run.label
    return ui(run.method)


def _source_columns(project, source, runs):
    """Output names of a live or reproducible saved input to a worksheet join."""
    pending = []
    while source is not None:
        parent = runs.get(source.analysis_id)
        if parent is None:
            return None
        if parent.result is not None and not parent.calculation_error:
            try:
                columns = list(result_frame(parent.result, source.table).columns)
            except ValueError:
                return None
            break
        if source.table != PASSTHROUGH_TABLES.get(parent.method):
            return None
        pending.append(parent)
        if parent.method == SELECT_TRANSFORM and "Variables" in parent.options:
            columns = ()
            break
        if parent.source is None:
            dataset = project.tables.get(parent.title)
            if dataset is None:
                return None
            columns = dataset.columns
            break
        source = parent.source
    else:
        return None
    for parent in reversed(pending):
        if parent.method == worksheet_join.METHOD:
            right = project.tables.get(worksheet_join.right_title(parent.options))
            if right is None:
                return None
            try:
                _, right_keys, _, _ = worksheet_join.validate(parent.options, columns, right.columns)
            except ValueError:
                return None
            columns, _ = worksheet_join.output_names(columns, right.columns, right_keys)
            continue
        names = parent.options.get("Variables", columns)
        calculated = parent.options.get(CALCULATED, ())
        if (not isinstance(names, (list, tuple)) or not isinstance(calculated, (list, tuple))
                or not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in calculated)):
            return None
        columns = [*names, *(item["name"].strip() for item in calculated)]
    return list(columns)


def _join_right_column(left_columns, right_columns, right_keys, column):
    names, carried = worksheet_join.output_names(left_columns, right_columns, right_keys)
    return names[len(left_columns) + carried.index(column)]


def _collect_downstream_columns(project, title, column):
    """Find column readers and any joins whose right output name still needs resolution."""
    targets, unresolved = [], []
    visited = set()
    queue = deque()
    children, schemas = {}, {}
    runs = {run.uid: run for run in project.runs}
    right_columns = project.tables[title].columns

    for run in project.runs:
        if run.source is not None:
            children.setdefault(run.source, []).append(run)
        elif run.title == title:
            queue.append((run, column))
        if run.method != worksheet_join.METHOD or worksheet_join.right_title(run.options) != title:
            continue
        try:
            left_keys, right_keys, kind, _ = worksheet_join.validate(run.options)
        except ValueError:
            continue
        if column in right_keys:
            # A Left join always uses the unchanged left key, even when the right row no longer matches.
            if kind != worksheet_join.LEFT:
                queue.append((run, left_keys[right_keys.index(column)]))
        elif column in right_columns:
            if run.source is None:
                left_columns = project.tables[run.title].columns
            else:
                if run.source not in schemas:
                    schemas[run.source] = _source_columns(project, run.source, runs)
                left_columns = schemas[run.source]
            if left_columns is None:
                unresolved.append(run)
            else:
                mapped = _join_right_column(left_columns, right_columns, right_keys, column)
                queue.append((run, mapped))

    while queue:
        run, col = queue.popleft()
        key = (run.uid, col)
        if key in visited:
            continue
        visited.add(key)
        targets.append((run, col))
        if output := _passthrough(run, col):
            queue.extend((child, col) for child in children.get(output, ()))

    return targets, unresolved, children


def _passthrough(run, column):
    table = PASSTHROUGH_TABLES.get(run.method)
    if table is None:
        return None
    if run.method == SELECT_TRANSFORM:
        variables = run.options.get("Variables")
        if isinstance(variables, (list, tuple)) and column not in variables:
            return None
    return ResultSource(run.uid, table)


def _hits(values, removed):
    found = []
    for item in values:
        if isinstance(item, str) and item in removed and item not in found:
            found.append(item)
    return found


def _pair_hits(pairs, removed):
    if not isinstance(pairs, (list, tuple)):
        return []
    found = []
    for pair in pairs:
        if isinstance(pair, (list, tuple)):
            for label in pair:
                if isinstance(label, str) and label in removed and label not in found:
                    found.append(label)
    return found


def _recipe_hits(run, col, removed):
    """Return list of ``(field_key_or_name, tuple_of_removed_levels)`` blocked in ``run``."""
    method = run.method
    o = run.options or {}
    blocks = []

    if method == SELECT_TRANSFORM and isinstance(o.get(FILTERS), list):
        references = (rule.get("value") for rule in o[FILTERS] if isinstance(rule, dict)
                      and rule.get("column") == col and rule.get("target") == "Text"
                      and rule.get("operator") in {"=", "!="})
        if hits := _hits(references, removed):
            blocks.append((FILTERS, tuple(hits)))

    elif (method == "t-test" and o.get("Group") == col and o.get("Design") in {"Welch", "Student", "Paired"}
          and o.get(ttest_options.INPUT, ttest_options.GROUPED) == ttest_options.GROUPED
          and isinstance(o.get("Group order"), (list, tuple))):
        if hits := _hits((str(label) for label in o["Group order"]), removed):
            blocks.append(("Group order", tuple(hits)))

    elif method == "One-way ANOVA" and o.get("Group") == col:
        posthoc = o.get("Post-hoc", "None")
        family = o.get("Comparison family", "All pairs")
        if posthoc == "Dunnett" or (posthoc in {"Tamhane T2", "Dunnett T3"} and family == "Versus control"):
            if hits := _hits([o.get("Control group")], removed):
                blocks.append(("Control group", tuple(hits)))
        elif posthoc in {"Tamhane T2", "Dunnett T3"} and family == "Selected pairs":
            if hits := _pair_hits(o.get("Selected pairs"), removed):
                blocks.append(("Selected pairs", tuple(hits)))
        if o.get("Linear trend"):
            if hits := _hits(o.get("Trend group order") or (), removed):
                blocks.append(("Trend group order", tuple(hits)))

    elif method in {"Kruskal–Wallis", "Friedman"} and o.get("Group") == col:
        mode = o.get("Dunn comparisons", "None")
        if mode == "Versus control":
            if hits := _hits([o.get("Control group")], removed):
                blocks.append(("Control group", tuple(hits)))
        elif mode == "Selected pairs":
            if hits := _pair_hits(o.get("Selected pairs"), removed):
                blocks.append(("Selected pairs", tuple(hits)))

    elif method == "ANCOVA" and o.get("Group") == col:
        if o.get("Comparisons") == "Against control":
            if hits := _hits([o.get("Control group")], removed):
                blocks.append(("Control group", tuple(hits)))

    elif method == "Multifactor ANOVA":
        factors = o.get("Factors") or ()
        if col in factors:
            control_raw = (o.get("Control level(s), separated by |") or "").strip()
            compare = o.get("Cell comparison factors") or o.get("Compare marginal means by")
            if control_raw and compare:
                if compare == col:
                    if hits := _hits([control_raw], removed):
                        blocks.append(("Control level(s), separated by |", tuple(hits)))
                elif isinstance(compare, list) and col in compare:
                    idx = compare.index(col)
                    parts = [item.strip() for item in control_raw.split("|")]
                    if len(compare) == 1 and len(parts) == 1:
                        candidate = parts[0]
                    elif idx < len(parts):
                        candidate = parts[idx]
                    else:
                        candidate = None
                    if hits := _hits([candidate], removed):
                        blocks.append(("Control level(s), separated by |", tuple(hits)))

            contrasts = o.get("Planned contrasts") or ()
            contrast_factors = o.get("Planned contrast factors") or ()
            if contrasts and col in contrast_factors:
                pos = contrast_factors.index(col)
                hits = []
                for contrast in contrasts:
                    if not isinstance(contrast, dict):
                        continue
                    for weight in contrast.get("weights") or ():
                        levels = weight.get("levels") if isinstance(weight, dict) else None
                        if isinstance(levels, (list, tuple)) and pos < len(levels):
                            lvl = levels[pos]
                            if isinstance(lvl, str) and lvl in removed and lvl not in hits:
                                hits.append(lvl)
                if hits:
                    blocks.append(("Planned contrasts", tuple(hits)))

    elif method == "Kaplan–Meier survival":
        groups = o.get("Grouping variables")
        if groups is None:
            groups = [o["Group"]] if o.get("Group") else []
        responses = o.get("Event columns")
        if responses is None:
            responses = [o["Event"]] if o.get("Event") else []
        if col in groups:
            single = len(groups) == 1 and len(responses) == 1
            correction = o.get("Pairwise correction", "None")
            scope = o.get("Pairwise comparison family",
                          "Versus control" if o.get("Pairwise control group") else "All pairs")

            def match_km(val):
                if not isinstance(val, str):
                    return []
                if single:
                    return [val] if val in removed else []
                found = []
                for lvl in removed:
                    if f"{col}={lvl!r}" in val and lvl not in found:
                        found.append(lvl)
                return found

            if correction != "None" and scope == "Versus control":
                if hits := match_km(o.get("Pairwise control group")):
                    blocks.append(("Pairwise control group", tuple(hits)))
            if correction != "None" and scope == "Selected pairs":
                hits = []
                for pair in o.get("Selected survival pairs") or ():
                    if isinstance(pair, (list, tuple)):
                        for item in pair:
                            for lvl in match_km(item):
                                if lvl not in hits:
                                    hits.append(lvl)
                if hits:
                    blocks.append(("Selected survival pairs", tuple(hits)))
            if o.get("Log-rank trend"):
                hits = []
                for item in o.get("Trend group order") or ():
                    for lvl in match_km(item):
                        if lvl not in hits:
                            hits.append(lvl)
                if hits:
                    blocks.append(("Trend group order", tuple(hits)))
            if o.get("Hazard ratio"):
                if hits := match_km(o.get("Hazard ratio numerator")):
                    blocks.append(("Hazard ratio numerator", tuple(hits)))

    elif method == "Restricted mean survival time" and o.get("Group") == col:
        if hits := _hits([o.get("Reference group")], removed):
            blocks.append(("Reference group", tuple(hits)))

    elif method == "Cohen's kappa" and col in {o.get("First rating"), o.get("Second rating")}:
        if hits := _hits(o.get("Category order") or (), removed):
            blocks.append(("Category order", tuple(hits)))

    elif method == "Ordinal logistic regression":
        if o.get("Response") == col:
            if hits := _hits(o.get("Category order") or (), removed):
                blocks.append(("Category order", tuple(hits)))
        if o.get("Response") == col or col in (o.get("Categorical predictors") or ()):
            hits = []
            for prof in o.get("Profiles") or ():
                if isinstance(prof, dict) and isinstance(prof.get("Values"), dict):
                    val = prof["Values"].get(col)
                    if isinstance(val, str) and val in removed and val not in hits:
                        hits.append(val)
            if hits:
                blocks.append(("Profiles", tuple(hits)))

    elif method in {"Weibull AFT", "Cox regression", "Linear regression", "Logistic validation"}:
        profiles = o.get("Profiles") or o.get("Linear prediction profiles") or o.get("Logistic profiles") or ()
        hits = []
        for prof in profiles:
            if isinstance(prof, dict) and isinstance(prof.get("Values"), dict):
                val = prof["Values"].get(col)
                if isinstance(val, str) and val in removed and val not in hits:
                    hits.append(val)
        if hits:
            blocks.append(("Profiles", tuple(hits)))

    return blocks


def find_blocking_recipes(project, title, plan):
    """Find recipes referencing removed levels. An unresolved join schema raises LevelEditError."""
    if not plan.removed_labels:
        return []
    label_to_tokens = {}
    for old_token, new_token in plan.token_map.items():
        if old_token != new_token:
            raw = old_token.split(":", 1)[1] if old_token.startswith(("str:", "int:", "float:", "bool:")) else None
            if raw is not None and raw in plan.removed_labels:
                label_to_tokens.setdefault(raw, []).append(old_token)

    blockers = []
    targets, unresolved, children = _collect_downstream_columns(project, title, plan.column)
    for run, col in targets:
        for field_name, levels in _recipe_hits(run, col, plan.removed_labels):
            tokens = []
            for lvl in levels:
                tokens.extend(label_to_tokens.get(lvl, ()))
            blockers.append(RecipeBlocker(
                recipe_name=_run_name(run),
                field_label=ui(field_name),
                levels=levels,
                source_tokens=tuple(dict.fromkeys(tokens)),
            ))
    if not blockers:
        for join in unresolved:
            if _unresolved_join_depends(join, plan, children):
                source = next((run for run in project.runs if run.uid == join.source.analysis_id), join)
                raise LevelEditError(tr("category_levels.error.join_source", recipe=source.name),
                                     code="join_source_unavailable")
    return blockers


def _unresolved_join_depends(join, plan, children):
    """Only ask for an unloaded schema when a consumer names a possible alias and a changed level."""
    column = plan.column
    pending = deque(children.get(ResultSource(join.uid, worksheet_join.JOINED), ()))
    visited = set()
    while pending:
        run = pending.popleft()
        if run.uid in visited:
            continue
        visited.add(run.uid)
        if any(_recipe_hits(run, alias, plan.removed_labels) for alias in _possible_aliases(run.options, column)):
            return True
        if table := PASSTHROUGH_TABLES.get(run.method):
            pending.extend(children.get(ResultSource(run.uid, table), ()))
    return False


def _possible_aliases(options, column):
    """Names that output_names could choose with a still unknown set of left columns."""
    yield column
    prefix = f"{column} [right"
    pending = [options]
    found = {column}
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value)
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, str) and value.startswith(prefix) and value.endswith("]") and value not in found:
            suffix = value[len(prefix):-1]
            number = suffix[1:]
            if not suffix or (suffix.startswith(" ") and number.isascii() and number.isdigit()
                              and not number.startswith("0") and number != "1"):
                found.add(value)
                yield value


def format_recipe_blockers(blockers):
    """Build a reproducible, localized error message naming blocked recipes, fields, and levels."""
    if not blockers:
        return ""
    first = blockers[0]
    levels_text = ", ".join(repr(lvl) for lvl in first.levels)
    message = tr(
        "category_levels.error.recipe_blocked",
        recipe=first.recipe_name,
        field=first.field_label,
        levels=levels_text,
    )
    if len(blockers) > 1:
        extra = tr("category_levels.error.recipe_blocked_more", count=len(blockers) - 1)
        message = f"{message} {extra}"
    return message
