"""Adapters for repeated-measure and multi-series curve input tables."""
import math
import re

import numpy as np
import pandas as pd

from .curve_models import MODELS
from .stats import FIT_WEIGHTINGS, complete


def _selected(frame, names, message):
    if not names or any(not name or name not in frame for name in names) or len(set(names)) != len(names):
        raise ValueError(message)


def _unused(base, names):
    name = base
    while name in names:
        name += " (within)"
    return name


def _series_name(label, merge_replicates):
    match = re.fullmatch(r"(.*?)\s+\[([1-9]\d*)\]", label) if merge_replicates else None
    return match[1] if match else label


def _allows_single_curve(options):
    model = MODELS.get(options.get("Model"))
    return model is not None and bool(model.required_fixed)


def encode_series_label(label):
    if isinstance(label, np.generic):
        label = label.item()
    if type(label) in (str, int, bool) or (type(label) is float and math.isfinite(label)):
        return label
    raise ValueError("A series label must be text or a finite number.")


def decode_series_constraints(records):
    if not isinstance(records, list):
        raise ValueError("Series constraints must be a list of series records.")
    constraints = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"series", "parameters"}:
            raise ValueError("Invalid series constraint record.")
        label = encode_series_label(record["series"])
        if label in constraints:
            raise ValueError(f"Duplicate series constraint record for {label!r}.")
        if not isinstance(record["parameters"], dict):
            raise ValueError(f"Invalid parameters for series {label!r}.")
        constraints[label] = record["parameters"]
    return constraints


def curve_series_labels(frame, options):
    """List series with at least one nonblank XY observation in the selection."""
    x = options.get("X")
    if x not in frame:
        return []
    keep_x = frame[x].notna()
    if options.get("Input format") == "Wide XY":
        columns = options.get("Y columns") or ()
        merge = options.get("Merge numbered replicates", True)
        return list(dict.fromkeys(_series_name(column, merge) for column in columns
                                  if column != x and column in frame and (keep_x & frame[column].notna()).any()))
    y, series = options.get("Y"), options.get("Series")
    if y in frame and y != x and not series and _allows_single_curve(options):
        return ["All"] if (keep_x & frame[y].notna()).any() else []
    if y not in frame or series not in frame or len({x, y, series}) != 3:
        return []
    values = frame.loc[keep_x & frame[y].notna(), series].dropna().unique()
    labels = []
    for value in values:
        try:
            labels.append(encode_series_label(value))
        except ValueError:
            # Some labels can identify a fit series without being JSON scalars.
            continue
    return labels


def _numeric(series, label):
    numeric = pd.to_numeric(series, errors="coerce")
    if np.iscomplexobj(numeric.to_numpy()):
        raise ValueError(f'Column "{label}" contains complex values.')
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    if (series.notna().to_numpy() & ~np.isfinite(values)).any():
        raise ValueError(f'Column "{label}" contains non-numeric or infinite values.')
    return values


def _curve_means(data, sigma):
    clean = complete(data.reset_index(drop=True), ["X", "Response"], ["Series"])
    grouping = ["Series", "X"]
    if not sigma:
        return clean.groupby(grouping, sort=False, observed=True, as_index=False)["Response"].mean()
    scales = _numeric(data[sigma].iloc[clean.index], sigma)
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise ValueError("Weighted regression requires a positive SD for each retained observation.")
    # For independent observations with fixed SDs, Var(mean) = sum(SD²) / n².
    # Scale first so squaring finite relative weights does not overflow.
    reference = scales.max() if len(scales) else 1
    clean["Relative variance"] = (scales / reference)**2
    means = clean.groupby(grouping, sort=False, observed=True, as_index=False).agg(
        Response=("Response", "mean"), Variance=("Relative variance", "sum"), N=("Response", "size"))
    means[sigma] = np.sqrt(means.pop("Variance")) / means.pop("N") * reference
    return means


def curve_input(frame, options):
    """Return an XY/series table and axis labels for one joint objective."""
    x = options.get("X")
    input_format = options.get("Input format", "Long table")
    weighted = options.get("Weighting") == FIT_WEIGHTINGS[1]
    allow_one = _allows_single_curve(options)
    sd_name = options.get("SD column") if weighted else None
    if weighted and (not sd_name or sd_name not in frame):
        raise ValueError("Select a column containing positive standard deviations.")
    if input_format == "Wide XY":
        columns = options.get("Y columns") or []
        _selected(frame, [x, *columns, *([sd_name] if sd_name else [])],
                  "Select distinct X, Y and optional SD columns.")
        if len(columns) < (1 if allow_one else 2):
            raise ValueError("Select at least one Y column." if allow_one else "Select at least two Y columns.")
        if len(frame) * len(columns) > 500_000:
            raise ValueError("The selected wide curves contain too many observations.")
        # Use NumPy arrays so concatenation never realigns duplicate index labels.
        x_values = frame[x].to_numpy()
        sd_values = frame[sd_name].to_numpy() if sd_name else None
        blocks = []
        for label in columns:
            block = pd.DataFrame({"X": x_values, "Response": frame[label].to_numpy(),
                                  "Series": _series_name(label, options.get("Merge numbered replicates", True))},
                                 index=frame.index)
            if sd_values is not None:
                block["SD"] = sd_values
            blocks.append(block)
        data = pd.concat(blocks)
        ylabel = "Response"
    elif input_format == "Long table":
        y, series = options.get("Y"), options.get("Series")
        use_group = bool(series) or not allow_one
        columns = [x, y, *([series] if use_group else []), *([sd_name] if sd_name else [])]
        _selected(frame, columns, "Select distinct X, Y, series and optional SD columns.")
        names = ["X", "Response", *(["Series"] if use_group else []), *(["SD"] if sd_name else [])]
        data = frame[columns].set_axis(names, axis=1).copy()
        if not use_group:
            data["Series"] = "All"
        ylabel = y
    else:
        raise ValueError("Select long or wide XY input.")
    scale = options.get("X values", "As entered")
    xlabel = x
    if scale == "Log10 concentrations":
        raw = _numeric(data["X"], x)
        with np.errstate(over="ignore", under="ignore"):
            dose = np.power(10., raw)
        if (np.isfinite(raw) & ((dose <= 0) | ~np.isfinite(dose))).any():
            raise ValueError("Converted concentrations are outside the numeric range.")
        data["X"] = dose
        xlabel = "Concentration"
    elif scale != "As entered":
        raise ValueError("Select how the X values are stored.")
    if data["Series"].nunique(dropna=True) < (1 if allow_one else 2):
        raise ValueError("Joint fitting needs at least two distinct series.")
    sigma = "SD" if sd_name else None
    replicate_mode = options.get("Replicates", "Individual observations")
    if replicate_mode == "Means at each X":
        data = _curve_means(data, sigma)
    elif replicate_mode != "Individual observations":
        raise ValueError("Select how to handle replicates.")
    return data, xlabel, ylabel, sigma


def _grouped_input(frame, options):
    columns = options.get("Measurement columns") or []
    row_labels = options.get("Row labels")
    _selected(frame, [*columns, *([row_labels] if row_labels else [])],
              "Select distinct measurement and optional row label columns.")
    if len(columns) < 2 or len(frame) < 2 or len(frame) * len(columns) > 500_000:
        raise ValueError("Grouped input needs at least two rows and two measurement columns, within the size limit.")
    row_factor = row_labels or "Row"
    column_factor = _unused("Column series", [row_factor])
    subject = _unused("Subject", [row_factor, column_factor])
    response = _unused("Response", [row_factor, column_factor, subject])
    levels = frame[row_labels].to_numpy() if row_labels else np.arange(1, len(frame) + 1)
    if pd.isna(levels).any() or len(pd.unique(levels)) != len(frame):
        raise ValueError("Grouped table row labels must be present and unique.")
    repeated = options.get("Repeat across", "Columns only")
    if repeated not in {"Rows only", "Columns only", "Rows and columns"}:
        raise ValueError("Choose which grouped factors use repeated measurements.")
    within = [role for role, dimension in ((row_factor, "Rows"), (column_factor, "Columns"))
              if repeated == "Rows and columns" or repeated == f"{dimension} only"]
    between = [role for role in (row_factor, column_factor) if role not in within]
    blocks, seen, series = [], set(), set()
    for column in columns:
        match = re.fullmatch(r"(.*?)\s+\[([1-9]\d*)\]", column)
        label, replicate = (match[1], int(match[2])) if match else (column, 1)
        if (label, replicate) in seen:
            raise ValueError("Two selected columns name the same series and replicate.")
        seen.add((label, replicate))
        series.add(label)
        if repeated == "Rows and columns":
            identifiers = [replicate] * len(levels)
        elif repeated == "Rows only":
            identifiers = [(label, replicate)] * len(levels)
        else:
            identifiers = [(level, replicate) for level in levels]
        blocks.append(pd.DataFrame({row_factor: levels, column_factor: label,
                                    subject: identifiers, response: frame[column].to_numpy()}))
    if len(series) < 2:
        raise ValueError("Grouped input needs at least two distinct column series.")
    return pd.concat(blocks, ignore_index=True), response, within, between, subject


def mixed_input(frame, options):
    """Return response and factor roles for the repeated-measures engine."""
    between = options.get("Between factors") or []
    subject = options.get("Subject")
    input_format = options.get("Input format", "Long table")
    if input_format == "Grouped replicate table":
        return _grouped_input(frame, options)
    if input_format == "Wide repeated measures":
        values = options.get("Measurement columns") or []
        if len(values) < 2:
            raise ValueError("Select at least two measurement columns.")
        _selected(frame, [*values, *between, *([subject] if subject else [])],
                  "Select distinct measurement, between-factor and subject columns.")
        if len(values) * len(frame) > 500_000:
            raise ValueError("The selected wide table contains too many observations.")
        keep = [*between, *([subject] if subject else [])]
        data = frame[keep + values].copy()
        if not subject:
            subject = _unused("Subject", data.columns)
            data[subject] = np.arange(1, len(data) + 1)
        condition = _unused("Condition", data.columns)
        response = _unused("Response", data.columns)
        data = data.melt(id_vars=[subject, *between], value_vars=values,
                         var_name=condition, value_name=response, ignore_index=False)
        within = [condition]
    elif input_format == "Long table":
        within = options.get("Within factors") or []
        response = options.get("Y")
        roles = [response, subject, *within, *between]
        _selected(frame, roles, "Choose distinct response, subject, within-factor and between-factor columns.")
        data = frame[roles].copy()
    else:
        raise ValueError("Select long or wide repeated-measures input.")
    if not within or len(within) + len(between) > 3:
        raise ValueError("Select one to three factors, with at least one within-subject factor.")
    subject_mode = options.get("Subject IDs", "Unique across groups")
    if subject_mode == "Restart within between groups" and between:
        original = [*between, subject]
        key = _unused("Subject within groups", data.columns)
        data[key] = [row if all(pd.notna(value) for value in row) else None
                     for row in data[original].itertuples(index=False, name=None)]
        subject = key
    elif subject_mode not in {"Unique across groups", "Restart within between groups"}:
        raise ValueError("Select how the subject IDs are assigned.")
    return data, response, within, between, subject
