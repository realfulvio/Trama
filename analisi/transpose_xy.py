"""Transpose X and Y: swap the roles of X and Y, one stacked block per Y set.

Every set of ``Y sets`` becomes a block of the result, in the configured order. A source row with an effective X
and an effective Y gives one output row where the new X is the source Y (or the mean of the effective replicate
subcolumns) and the new Y is the source X. Duplicated X values and rows sharing a title are kept, rows without X or
Y are left out, and the other Y columns of a block stay blank. The transformations (Log10, Reciprocal) run after the
swap: "X transform" acts on the new X, "Y transform" on the new Y.

Y set modes
    Single           one source column.
    Replicates       two or more subcolumns; the value is their mean over the cells that are present (blank and
                     excluded cells are ignored, an all-blank row has no value). The mean is scaled when a plain
                     sum would overflow.
    Summary mean     the column that holds the mean; SD, SEM and N play no part.

TramaStat conventions: provenance is reported in "Source rows" (1-based worksheet positions, so duplicated pandas
indexes are harmless); ``Order`` is either the worksheet order or a stable ascending sort of each block on the final
X. At most 40 sets and ``MAX_CELLS`` result cells.
"""
import re

import numpy as np
import pandas as pd

from .data import MAX_CELLS, _worksheet_roles
from .processing import FieldError, _column
from .reporting import Result, _report

TRANSPOSE_XY = "Transpose X and Y"
X, Y_SETS, ROW_TITLE, X_TRANSFORM, Y_TRANSFORM, ORDER, PLOT = (
    "X", "Y sets", "Row title", "X transform", "Y transform", "Order", "Plot")
SINGLE, REPLICATES, SUMMARY_MEAN = MODES = ("Single", "Replicates", "Summary mean")
TRANSFORMS = ("None", "Log10", "Reciprocal")
SOURCE_ORDER, ASCENDING = ORDERS = ("Source order", "Ascending X within each set")
MAX_SETS = 40
SETS_LIST = "Transpose sets"  # Dialog kind of the Y sets field: a list of {"name", "mode", "columns"}.
OPTIONS = {X: None, Y_SETS: SETS_LIST, ROW_TITLE: "Optional", X_TRANSFORM: TRANSFORMS,
           Y_TRANSFORM: TRANSFORMS, ORDER: ORDERS, PLOT: False}
TABLE, SOURCE_SHEET, SETTINGS = "Transposed XY", "Source rows", "Settings"

_REPLICATE = re.compile(r"(.+) \[([1-9]\d*)\]")
_MEAN = re.compile(r"(.+) \[Mean\](?: \(\d+\))?")
_SUMMARY = re.compile(r".+ \[(?:Mean|SD|SEM|N|Center|Plus|Minus|Lower|Upper|CV%?|Value|Error)\](?: \(\d+\))?")


def propose_sets(frame, x=None):
    """Y sets suggested by the XY roles of the table, or by its "Name [n]" and "Name [Mean]" titles."""
    roles = _worksheet_roles(frame)
    if roles and roles.get("y"):
        groups = [[name for name in group if name in frame] for group in roles["y"]]
        groups = [group for group in groups if group]
    else:
        found, groups = {}, []
        for name in frame.columns:
            match = _REPLICATE.fullmatch(str(name))
            if match:
                found.setdefault(match.group(1), []).append(name)
            elif not _SUMMARY.fullmatch(str(name)) or _MEAN.fullmatch(str(name)):
                groups.append([name])
        groups = [*groups, *found.values()]
        order = {name: i for i, name in enumerate(frame.columns)}
        groups.sort(key=lambda group: order[group[0]])
    sets = []
    for group in groups:
        means = [name for name in group if _MEAN.fullmatch(str(name))]
        if means:
            name = _MEAN.fullmatch(str(means[0])).group(1)
            sets.append({"name": name, "mode": SUMMARY_MEAN, "columns": [means[0]]})
        elif len(group) > 1:
            match = _REPLICATE.fullmatch(str(group[0]))
            sets.append({"name": match.group(1) if match else str(group[0]), "mode": REPLICATES,
                         "columns": list(group)})
        else:
            sets.append({"name": str(group[0]), "mode": SINGLE, "columns": list(group)})
    proposed, used = [], set()
    for item in sets:
        if item["columns"][0] == x or not all(pd.api.types.is_numeric_dtype(frame[c]) for c in item["columns"]):
            continue
        name, n = item["name"], 2
        while name in used or name in {X, ROW_TITLE}:
            name, n = f"{item['name']} ({n})", n + 1
        used.add(name)
        proposed.append({**item, "name": name})
    return proposed


def proposed_x(frame):
    roles = _worksheet_roles(frame)
    if roles and roles.get("x") and roles["x"][0] in frame:
        return roles["x"][0]
    return None


def _sets(frame, options, x, title):
    raw = options.get(Y_SETS)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise FieldError(Y_SETS, "Add at least one Y set.")
    if len(raw) > MAX_SETS:
        raise FieldError(Y_SETS, f"At most {MAX_SETS} Y sets are supported.")
    reserved = {X, *( [ROW_TITLE] if title else [])}
    taken = {x, *([title] if title else [])}
    names, columns = set(), set()
    sets = []
    for position, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise FieldError(Y_SETS, f"Y set {position} is not valid.")
        name = item.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            raise FieldError(Y_SETS, f"Y set {position} needs a name.")
        if name in names:
            raise FieldError(Y_SETS, f'The name "{name}" is used by more than one Y set.')
        if name in reserved or name in taken:
            raise FieldError(Y_SETS, f'The name "{name}" collides with the X or Row title column.')
        names.add(name)
        mode = item.get("mode")
        if mode not in MODES:
            raise FieldError(Y_SETS, f'"{name}": choose Single, Replicates or Summary mean.')
        members = item.get("columns")
        if not isinstance(members, (list, tuple)) or any(not isinstance(column, str) for column in members):
            raise FieldError(Y_SETS, f'"{name}": choose its source columns.')
        members = list(members)
        if len(set(members)) != len(members):
            raise FieldError(Y_SETS, f'"{name}": a column is listed twice.')
        need = f"{'exactly one' if mode != REPLICATES else 'at least two'} column{'s' if mode == REPLICATES else ''}"
        if (len(members) != 1) if mode != REPLICATES else (len(members) < 2):
            raise FieldError(Y_SETS, f'"{name}" ({mode}) needs {need}.')
        for column in members:
            if column not in frame:
                raise FieldError(Y_SETS, f'Column "{column}" is not in the table.')
            if column in taken:
                raise FieldError(Y_SETS, f'"{column}" is already used as X or Row title.')
            if column in columns:
                raise FieldError(Y_SETS, f'"{column}" belongs to more than one Y set.')
            columns.add(column)
        sets.append((name, mode, members))
    return sets


def _mean_rows(block):
    """Row means of the finite cells and their counts; scaled only when the plain mean overflows."""
    present = np.isfinite(block)
    count = present.sum(axis=1)
    with np.errstate(all="ignore"):
        total = np.where(present, block, 0.0).sum(axis=1)
        mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
        broken = (count > 0) & ~np.isfinite(mean)
        if broken.any():
            scale = np.abs(np.where(present[broken], block[broken], 0.0)).max(axis=1)
            scale = np.where(scale == 0, 1.0, scale)
            scaled = np.where(present[broken], block[broken] / scale[:, None], 0.0).sum(axis=1)
            mean[broken] = scaled / count[broken] * scale
    return mean, count


def _transform(values, name, field):
    if name == "None":
        return values
    if name not in TRANSFORMS:
        raise FieldError(field, f"{field} must be one of {', '.join(TRANSFORMS)}.")
    if name == "Log10":
        if (values <= 0).any():
            raise FieldError(field, "Log10 needs strictly positive values after the swap.")
        with np.errstate(all="ignore"):
            result = np.log10(values)
    else:
        if (values == 0).any():
            raise FieldError(field, "Reciprocal cannot transform a zero value.")
        with np.errstate(all="ignore"):
            result = 1.0 / values
    if not np.isfinite(result).all():
        raise FieldError(field, f"{name} produces values outside the numeric range.")
    return result


def transpose_xy(frame, options):
    if not frame.columns.is_unique:
        raise FieldError(X, "The table needs unique column names.")
    x = options.get(X)
    if not isinstance(x, str) or x not in frame:
        raise FieldError(X, "Choose a column for X.")
    title = options.get(ROW_TITLE) or None
    if title is not None:
        if not isinstance(title, str) or title not in frame:
            raise FieldError(ROW_TITLE, "Choose an existing column for the row title, or none.")
        if title == x:
            raise FieldError(ROW_TITLE, "The row title column must differ from X.")
    order = options.get(ORDER, SOURCE_ORDER)
    if order not in ORDERS:
        raise FieldError(ORDER, "Choose the order of the rows within each set.")
    plot = options.get(PLOT, False)
    if not isinstance(plot, (bool, np.bool_)):
        raise FieldError(PLOT, "Plot must be on or off.")
    sets = _sets(frame, options, x, title)
    rows = len(frame)
    source_x = _column(frame, x, X).to_numpy(dtype=float)
    blocks = []
    for name, mode, members in sets:
        data = np.column_stack([_column(frame, column, Y_SETS).to_numpy(dtype=float) for column in members])
        if mode == REPLICATES:
            value, count = _mean_rows(data)
        else:
            value, count = data[:, 0], np.isfinite(data[:, 0]).astype(int)
        keep = np.flatnonzero(np.isfinite(source_x) & np.isfinite(value))
        blocks.append((name, keep, value[keep], count[keep]))
    total = sum(len(keep) for _, keep, _, _ in blocks)
    if not total:
        raise FieldError(Y_SETS, "No row has both an X value and a Y value for the chosen sets.")
    if total * (2 + (title is not None) + len(sets)) > MAX_CELLS:
        raise FieldError(Y_SETS, f"The result would exceed {MAX_CELLS:,} cells. Reduce the rows or the sets.")
    new_x, new_y, positions, series_of, counts = [], [], [], [], []
    for index, (name, keep, value, count) in enumerate(blocks):
        block_x = _transform(value, options.get(X_TRANSFORM, "None"), X_TRANSFORM)
        block_y = _transform(source_x[keep], options.get(Y_TRANSFORM, "None"), Y_TRANSFORM)
        if order == ASCENDING:
            ranking = np.argsort(block_x, kind="stable")
            block_x, block_y, keep, count = block_x[ranking], block_y[ranking], keep[ranking], count[ranking]
        new_x.append(block_x)
        new_y.append(block_y)
        positions.append(keep)
        counts.append(count)
        series_of.append(np.full(len(keep), index))
    new_x, new_y = np.concatenate(new_x), np.concatenate(new_y)
    positions, counts, series_of = np.concatenate(positions), np.concatenate(counts), np.concatenate(series_of)
    names = [name for name, *_ in sets]
    columns = {X: new_x}
    if title is not None:
        columns[ROW_TITLE] = frame[title].iloc[positions].to_numpy(dtype=object)
    for index, name in enumerate(names):
        wide = np.full(total, np.nan)
        wide[series_of == index] = new_y[series_of == index]
        columns[name] = wide
    output = pd.DataFrame(columns)
    output.attrs["table_format"] = "xy"
    output.attrs["worksheet_roles"] = {"x": [X], "y": [[name] for name in names]}
    if title is not None:
        output.attrs["row_title_column"] = ROW_TITLE
    provenance = pd.DataFrame({"Series": [names[i] for i in series_of], "Source row": positions + 1,
                               "Output row": np.arange(1, total + 1), "N present": counts.astype(int)})
    settings = {"X column": x, "Row title column": title or "None", "Y sets": len(sets),
                "Sets": "; ".join(f"{name} ({mode}: {', '.join(members)})" for name, mode, members in sets),
                "X transform": options.get(X_TRANSFORM, "None"), "Y transform": options.get(Y_TRANSFORM, "None"),
                "Order": order, "Plot": "On" if plot else "Off", "Input rows": rows, "Output rows": total,
                "Rows per set": "; ".join(f"{name}: {len(keep)}" for name, keep, _, _ in blocks)}
    figure = None
    if plot:
        from .xy_series import xy_series

        graph = xy_series(output, {"X": X, "Y columns": names, "Series style": dict.fromkeys(names, "Line and points")})
        figure = graph.figure
        axes = figure.axes[0]
        axes.set_title(TRANSPOSE_XY)
        axes.set_xlabel("X (source Y)")
        axes.set_ylabel(f"Y (source {x})")
    return Result({TABLE: output, SOURCE_SHEET: provenance, SETTINGS: _report(settings)}, figure)
