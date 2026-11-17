"""Remove baseline and column math for replicate subcolumns.

The legacy path in processing.remove_baseline treats every subcolumn as an
independent column. The three replicate modes here read the dataset groups
from the worksheet roles (or, when a table has none, from consistent
"Name [n]" titles) and apply the baseline without flattening the replicates:

* Each replicate vs baseline mean: one baseline per row, the mean of the finite
  baseline replicates, applied to every signal replicate.
* Mean vs baseline mean: the row mean of the signal replicates combined with
  the row mean of the baseline replicates, one output per dataset.
* Matched subcolumns: signal replicate i combined with baseline replicate i.

TramaStat choices: the linear baseline is fitted by OLS to the row means of the
baseline replicates, so a row with several finite replicates counts once and
every X row has equal weight; Matched subcolumns with the linear baseline is
rejected. Missing and excluded cells are never treated as zero.
"""
import re

import numpy as np
import pandas as pd

from .data import _worksheet_roles
from .processing import BASELINES, FieldError, OPERATIONS, _apply, _column, _distinct, _finite, _whole
from .reporting import Result, _report
from .stats import linear

INDEPENDENT = "Independent columns"
EACH = "Each replicate vs baseline mean"
MEANS = "Mean vs baseline mean"
MATCHED = "Matched subcolumns"
REPLICATE_HANDLING = (INDEPENDENT, EACH, MEANS, MATCHED)
SUBCOLUMNS = "Baseline subcolumns"

_REPLICATE = re.compile(r"(.+) \[([1-9]\d*)\]")
_SUMMARY = re.compile(r".+ \[(?:Mean|SD|SEM|N|Center|Plus|Minus|Lower|Upper|CV%?|Value|Error)\](?: \(\d+\))?")


def replicate_handling(options):
    """The saved choice; recipes from 0.48.0 and earlier have none and stay on the legacy path."""
    return options.get("Replicate handling") or INDEPENDENT


def _table_groups(frame):
    """Every dataset of the table as a list of subcolumn names, in table order."""
    roles = _worksheet_roles(frame)
    if roles and roles.get("y"):
        groups = [[name for name in group if name in frame] for group in roles["y"]]
        return [group for group in groups if group], True
    groups = {}
    for name in frame.columns:
        match = _REPLICATE.fullmatch(str(name))
        if match:
            groups.setdefault(match.group(1), []).append((int(match.group(2)), name))
    ordered = []
    for members in groups.values():
        indices = [index for index, _ in members]
        if indices != list(range(1, len(members) + 1)):
            continue  # Not a consistent "Name [1]", "Name [2]"… run: ambiguous, so not a group.
        ordered.append([name for _, name in members])
    return ordered, False


def _groups(frame, selected, field):
    """Arrange selected column names into complete dataset groups, in table order."""
    for name in selected:
        if name not in frame:
            raise FieldError(field, f'Column "{name}" is not in the table.')
        if _SUMMARY.fullmatch(str(name)):
            raise FieldError(field, f'"{name}" is a summary subcolumn (Mean, SD, SEM, N or limits). Replicate '
                                    "handling needs raw replicates: choose Independent columns instead.")
    table, declared = _table_groups(frame)
    owner = {name: index for index, group in enumerate(table) for name in group}
    chosen = {}
    for name in selected:
        if name not in owner:
            source = "the table's datasets" if declared else 'a consistent "Name [1]", "Name [2]"… group'
            raise FieldError(field, f'"{name}" does not belong to {source}. Select whole replicate groups or '
                                    "choose Independent columns.")
        chosen.setdefault(owner[name], set()).add(name)
    groups = []
    for index in sorted(chosen):
        group = table[index]
        missing = [name for name in group if name not in chosen[index]]
        if missing:
            raise FieldError(field, f"The group {', '.join(group)} is incomplete: also select "
                                    f"{', '.join(missing)}, or choose Independent columns.")
        groups.append(group)
    position = list(frame.columns).index
    return sorted(groups, key=lambda group: position(group[0]))


def _group_name(group):
    stems = {match.group(1) for name in group if (match := _REPLICATE.fullmatch(str(name)))}
    if len(stems) == 1 and all(_REPLICATE.fullmatch(str(name)) for name in group):
        return stems.pop()
    return str(group[0]) if len(group) == 1 else f"{group[0]} group"


def _unique(name, taken):
    proposed, i = name, 2
    while proposed in taken:
        proposed = f"{name} ({i})"
        i += 1
    taken.add(proposed)
    return proposed


def _mean(values):
    """Mean of the finite values, robust to overflow of a sum of large finite values."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        return np.nan
    with np.errstate(all="ignore"):
        value = values.mean()
        if not np.isfinite(value):
            scale = np.abs(values).max()
            value = (values / scale).mean() * scale
    return float(value)


def _row_mean(data, group):
    block = np.column_stack([data[name].to_numpy(dtype=float) for name in group])
    return pd.Series([_mean(row) for row in block], index=data[group[0]].index)


def _pairs(groups, mode):
    if len(groups) < 2 or len(groups) % 2:
        raise FieldError("Data columns", "Alternate pairing needs an even number of complete datasets. Pairs "
                                         "follow the table order.")
    odd, even = groups[0::2], groups[1::2]
    return list(zip(*((odd, even) if mode == BASELINES[1] else (even, odd)), strict=True))


def _check_matched(signal, base, field):
    if len(signal) != len(base):
        raise FieldError(field, f"Matched subcolumns needs the same number of replicates: {', '.join(signal)} "
                                f"has {len(signal)} and {', '.join(base)} has {len(base)}.")


def replicate_baseline(frame, o):
    handling = replicate_handling(o)
    if handling not in REPLICATE_HANDLING[1:]:
        raise FieldError("Replicate handling", "Choose how replicate subcolumns are handled.")
    mode, operation = o.get("Baseline"), o.get("Operation")
    if mode not in BASELINES:
        raise FieldError("Baseline", "Choose a baseline.")
    if operation not in OPERATIONS:
        raise FieldError("Operation", "Choose an operation.")
    selected = list(o.get("Data columns") or [])
    if not selected or len(set(selected)) != len(selected):
        raise FieldError("Data columns", "Select one or more distinct data columns.")
    x, titles = o.get("X"), o.get("Row titles")
    uses_column = mode in (BASELINES[0], BASELINES[5])
    if mode == BASELINES[5] and handling == MATCHED:
        raise FieldError("Replicate handling", "Matched subcolumns is not available with a linear baseline: the "
                                               "line is fitted to the row means of the baseline replicates. Choose "
                                               "Each replicate vs baseline mean or Mean vs baseline mean.")
    _distinct(frame, {"X": x, "Row titles": titles})
    base_group = []
    if uses_column:
        chosen = list(o.get(SUBCOLUMNS) or [])
        if not chosen:
            raise FieldError(SUBCOLUMNS, "Select the subcolumns of one baseline dataset.")
        base_groups = _groups(frame, chosen, SUBCOLUMNS)
        if len(base_groups) != 1:
            raise FieldError(SUBCOLUMNS, "Select the subcolumns of a single baseline dataset.")
        base_group = base_groups[0]
        for name in base_group:
            for field, role in (("X", x), ("Row titles", titles)):
                if role == name:
                    raise FieldError(SUBCOLUMNS, f'"{name}" is already used as {field}.')
            if name in selected:
                raise FieldError(SUBCOLUMNS, f'"{name}" is also selected in Data columns.')
    for name in selected:
        for field, role in (("X", x), ("Row titles", titles)):
            if role == name:
                raise FieldError("Data columns", f'"{name}" is already used as {field}.')
    groups = _groups(frame, selected, "Data columns")
    data = {name: _column(frame, name, "Data columns") for group in groups for name in group}
    data.update({name: _column(frame, name, SUBCOLUMNS) for name in base_group})
    rows = len(frame)
    summary = {"Baseline": mode, "Operation": operation, "Replicate handling": handling}
    keep = np.ones(rows, dtype=bool)
    extra = {}
    # Each target is (signal group, baselines): one Series per signal subcolumn, or one for the group mean.
    targets = []
    if uses_column:
        if all(data[name].isna().all() for name in base_group):
            raise FieldError(SUBCOLUMNS, f"The baseline subcolumns {', '.join(base_group)} have no values.")
        summary["Baseline subcolumns"] = ", ".join(base_group)
        if handling == MATCHED:
            for group in groups:
                _check_matched(group, base_group, SUBCOLUMNS)
            targets = [(group, [data[name] for name in base_group]) for group in groups]
        else:
            baseline = _row_mean(data, base_group)
            if mode == BASELINES[5]:
                if not x:
                    raise FieldError("X", "Choose an X column for the linear baseline.")
                xs = _column(frame, x, "X")
                pairs = pd.DataFrame({"x": xs, "baseline": baseline}).dropna()
                if len(pairs) < 3 or pairs["x"].nunique() < 2:
                    raise FieldError(SUBCOLUMNS, "A linear baseline needs at least three rows with X and a baseline "
                                                 "mean, with two or more distinct X values.")
                with np.errstate(all="ignore"):
                    fit = linear(pairs, "x", "baseline")
                    predicted = fit["Intercept"] + fit["Slope"] * xs
                _finite((fit["Intercept"], fit["Slope"]), SUBCOLUMNS, "Fitting the baseline", present=True)
                _finite(predicted, SUBCOLUMNS, "Predicting the baseline", present=xs.notna())
                summary.update({"Rows used for the fit": fit["N"], "Intercept": fit["Intercept"],
                                "Slope": fit["Slope"]})
                x_label = f"{x} (X)" if x in {"Observed baseline mean", "Predicted baseline"} else x
                extra["Linear baseline"] = pd.DataFrame({x_label: frame[x], "Observed baseline mean": baseline,
                                                         "Predicted baseline": predicted})
                baseline = predicted
            else:
                summary["Rows without a baseline value"] = int(baseline.isna().sum())
            targets = [(group, [baseline]) for group in groups]
    elif mode in BASELINES[1:3]:
        for base, signal in _pairs(groups, mode):
            if all(data[name].isna().all() for name in base):
                raise FieldError("Data columns", f"The baseline subcolumns {', '.join(base)} have no values.")
            if handling == MATCHED:
                _check_matched(signal, base, "Data columns")
                targets.append((signal, [data[name] for name in base]))
            else:
                targets.append((signal, [_row_mean(data, base)]))
            summary[f"Baseline for {_group_name(signal)}"] = ", ".join(base)
    else:
        k = _whole(o.get("Rows for baseline (K)"), "Rows for baseline (K)", 1, rows)
        first = mode == BASELINES[3]
        window = slice(0, k) if first else slice(rows - k, rows)
        where = "first" if first else "last"
        for group in groups:
            parts = [[name] for name in group] if handling == MATCHED else [group]
            values = []
            for part in parts:
                reference = np.concatenate([data[name].iloc[window].to_numpy(dtype=float) for name in part])
                value = _mean(reference)
                if np.isnan(value):
                    raise FieldError("Rows for baseline (K)",
                                     f"{', '.join(part)} has no values in the {where} {k} row(s).")
                _finite(value, "Rows for baseline (K)", "Averaging the baseline", present=True)
                summary[f"Baseline of {', '.join(part)}"] = value
                values.append(pd.Series(value, index=frame.index))
            targets.append((group, values))
        if o.get("Drop baseline rows", False):
            keep[window] = False
            summary["Rows removed"] = k
    output = {}
    if titles:
        output[titles] = frame[titles]
    if x:
        output[x] = frame[x]
    taken = set(output)
    y_groups = []
    zero = 0
    for group, baselines in targets:
        if handling == MEANS:
            name = _unique(_group_name(group), taken)
            output[name], count = _apply(operation, _row_mean(data, group), baselines[0])
            zero += count
            y_groups.append([name])
            continue
        names = []
        for i, column in enumerate(group):
            baseline = baselines[i] if handling == MATCHED else baselines[0]
            name = _unique(column, taken)
            output[name], count = _apply(operation, data[column], baseline)
            zero += count
            names.append(name)
        y_groups.append(names)
    if handling == MATCHED and uses_column:
        summary["Pairs"] = "; ".join(f"{signal} with {base}" for group, _ in targets
                                     for signal, base in zip(group, base_group, strict=True))
    if zero:
        summary["Zero denominators left blank"] = zero
    result = pd.DataFrame(output, index=frame.index).iloc[keep].reset_index(drop=True)
    result.attrs["worksheet_roles"] = {"x": [x] if x else [], "y": y_groups}
    replicated = any(len(group) > 1 for group in y_groups)
    result.attrs["table_format"] = (("XY with replicates" if replicated else "xy") if x
                                    else "grouped" if replicated else "column")
    return Result({"Processed data": result, **extra, "Notes": _report(summary)})
