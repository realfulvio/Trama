"""Normalize worksheet columns onto a zero reference and a one reference.

For each finite value, ``normalized = M * (y - a) / (b - a)``. ``M`` is 1 for
fractions and 100 for percentages. ``a`` and ``b`` are fixed observed
references: their uncertainty is not propagated. The source frame, its attrs
and the options dict are left unchanged.
"""
from decimal import Decimal, InvalidOperation, localcontext
import math
import re

import numpy as np
import pandas as pd

from .category_graphs import COLORS
from .data import MAX_CELLS, decimal_comma
from .field_error import FieldError
from .processing import MULTIPLE, OPTIONAL, TEXT, _column
from .reporting import Result, _plot
from .worksheet_series import series_columns, series_labels


METHOD = "Normalize to references"
RAW = "Raw values"
SUMMARY = "Summary values"
INDEPENDENT = "Independent columns"
ROW_MEANS = "Normalize row means"
EACH = "Each replicate, common references"
MINIMUM = "Minimum"
FIRST_LOW = "First-last lower"
CONSTANT = "Constant"
SELECTED = "Selected rows mean"
MAXIMUM = "Maximum"
FIRST_HIGH = "First-last higher"
SUM = "Sum"
MEAN_RULE = "Mean"
FRACTIONS = "Fractions"
PERCENTAGES = "Percentages"
KEEP = "Keep"
BLANK = "Blank reference values"
ERR_NONE = "None"
SD = "SD"
SEM = "SEM"
DISTANCES = "Distances"
LIMITS = "Limits"

INPUTS = (RAW, SUMMARY)
REPLICATES = (INDEPENDENT, ROW_MEANS, EACH)
ZERO_RULES = (MINIMUM, FIRST_LOW, CONSTANT, SELECTED)
# Percentages is first so the generic dialog, which defaults to choices[0], matches the engine.
ONE_RULES = (MAXIMUM, FIRST_HIGH, SUM, MEAN_RULE, CONSTANT, SELECTED)
UNITS = (PERCENTAGES, FRACTIONS)
REFERENCE_OUTPUT = (KEEP, BLANK)
ERROR_FORMATS = (ERR_NONE, SD, SEM, DISTANCES, LIMITS)

NORMALIZED = "Normalized"
REFERENCES = "Normalization references"
SOURCE_ROWS = "Normalization source rows"
SETTINGS = "Normalization settings"
REFERENCE_COLUMNS = ("Series", "Zero reference", "One reference", "Scale factor", "Zero N", "One N",
                     "Zero source rows", "One source rows")
UNCERTAINTY_NOTE = ("Zero and one references are fixed observed values. "
                    "Their uncertainty is not propagated into the normalized results.")
SCALE_NOTE = "A scale factor is outside the numeric range and is left blank."

INPUT_FIELDS = ("Input", "Variables", "Mean", "X", "Row titles", "Replicates")
REFERENCE_FIELDS = ("Zero reference", "One reference", "Zero value", "One value", "Zero rows", "One rows",
                    "Allow reversed references")
OUTPUT_FIELDS = ("Units", "Reference values in output", "Error format", "Error lower", "Error upper", "N",
                 "Graph results")

OPTIONS = {
    "Input": INPUTS,
    "Variables": MULTIPLE,
    "Mean": None,
    "X": OPTIONAL,
    "Row titles": OPTIONAL,
    "Replicates": REPLICATES,
    "Zero reference": ZERO_RULES,
    "One reference": ONE_RULES,
    "Zero value": 0.0,
    "One value": 1.0,
    "Zero rows": TEXT,
    "One rows": TEXT,
    "Allow reversed references": False,
    "Units": UNITS,
    "Reference values in output": REFERENCE_OUTPUT,
    "Error format": ERROR_FORMATS,
    "Error lower": OPTIONAL,
    "Error upper": OPTIONAL,
    "N": OPTIONAL,
    "Graph results": True,
}

_MAX_SERIES = 24
_MAX_SELECTED_ROWS = 100_000
_ROW_ITEM = re.compile(r"\s*[1-9]\d*\s*(?:-\s*[1-9]\d*\s*)?\Z")
_GUIDE_ZERO = "tramastat-shape-reference-0"
_GUIDE_ONE = "tramastat-shape-reference-m"


def visibility(options=None):
    """Which dialog fields are active. Inactive fields are ignored by the engine too."""
    options = options or {}
    summary = options.get("Input", RAW) == SUMMARY
    zero = options.get("Zero reference", MINIMUM)
    one = options.get("One reference", MAXIMUM)
    error_format = options.get("Error format", ERR_NONE)
    return {
        "Input": True,
        "Variables": not summary,
        "Mean": summary,
        "X": True,
        "Row titles": True,
        "Replicates": not summary,
        "Zero reference": True,
        "One reference": True,
        "Zero value": zero == CONSTANT,
        "One value": one == CONSTANT,
        "Zero rows": zero == SELECTED,
        "One rows": one == SELECTED,
        "Allow reversed references": True,
        "Units": True,
        "Reference values in output": True,
        "Error format": summary,
        "Error lower": summary and error_format != ERR_NONE,
        "Error upper": summary and error_format in (DISTANCES, LIMITS),
        "N": summary,
        "Graph results": True,
    }


def normalize_to_references(frame, options):
    options = options or {}
    mode = _choice(options, "Input", INPUTS, RAW)
    summary = mode == SUMMARY
    units = _choice(options, "Units", UNITS, PERCENTAGES)
    span = 1 if units == FRACTIONS else 100
    zero_rule = _choice(options, "Zero reference", ZERO_RULES, MINIMUM)
    one_rule = _choice(options, "One reference", ONE_RULES, MAXIMUM)
    allow_reversed = _flag(options, "Allow reversed references", False)
    blank = _choice(options, "Reference values in output", REFERENCE_OUTPUT, KEEP) == BLANK
    graph = _flag(options, "Graph results", True)
    replicates = INDEPENDENT if summary else _choice(options, "Replicates", REPLICATES, INDEPENDENT)
    error_format = _choice(options, "Error format", ERROR_FORMATS, ERR_NONE) if summary else ERR_NONE
    show = visibility(options)
    zero_value = _constant(options, "Zero value", 0.0) if show["Zero value"] else None
    one_value = _constant(options, "One value", 1.0) if show["One value"] else None
    if len(frame.index) * len(frame.columns) > MAX_CELLS:
        raise FieldError("Mean" if summary else "Variables", "The table exceeds the size limit.")

    seen = {}
    if summary:
        mean_name = _required_name(options, "Mean")
        _claim(frame, mean_name, "Mean", seen)
        variables = [mean_name]
    else:
        mean_name = None
        variables = _variable_names(frame, options, seen)
    x_name = _optional_name(options, "X")
    titles_name = _optional_name(options, "Row titles")
    _claim(frame, x_name, "X", seen)
    _claim(frame, titles_name, "Row titles", seen)
    lower_name = upper_name = n_name = None
    if summary and error_format != ERR_NONE:
        lower_name = _required_name(options, "Error lower")
        _claim(frame, lower_name, "Error lower", seen)
        if error_format in (DISTANCES, LIMITS):
            upper_name = _required_name(options, "Error upper")
            _claim(frame, upper_name, "Error upper", seen)
    if summary and options.get("N"):
        n_name = _required_name(options, "N")
        _claim(frame, n_name, "N", seen)

    groups = [[name] for name in variables] if summary or replicates == INDEPENDENT else series_columns(
        frame, variables, recognize_replicates=True)
    if len(groups) > _MAX_SERIES:
        raise FieldError("Mean" if summary else "Variables", "Select at most 24 series.")
    labels = series_labels(groups)
    width = (x_name is not None) + (titles_name is not None)
    width += len(groups) if replicates == ROW_MEANS and not summary else sum(len(group) for group in groups)
    if lower_name:
        width += 1
    if upper_name:
        width += 1
    if n_name:
        width += 1
    if len(frame.index) * width > MAX_CELLS:
        raise FieldError("Mean" if summary else "Variables", "The table exceeds the size limit.")

    columns = {name: _decimals(frame, name, "Mean" if summary else "Variables") for name in dict.fromkeys(variables)}
    lower_cells = _loose(frame, lower_name, "Error lower") if lower_name else None
    upper_cells = _loose(frame, upper_name, "Error upper") if upper_name else None
    n_cells = _loose(frame, n_name, "N") if n_name else None
    n_rows = len(frame.index)
    used = set()
    ordered = {}
    roles_x = []
    roles_y = []
    references = []
    graph_lines = []
    scale_missing = False
    if x_name:
        placed = _place(used, x_name)
        ordered[placed] = _literal(frame[x_name])
        roles_x.append(placed)
    if titles_name:
        ordered[_place(used, titles_name)] = _literal(frame[titles_name])

    with localcontext() as context:
        context.prec = 80
        for group, label in zip(groups, labels, strict=True):
            members = [columns[name] for name in group]
            vector = members[0] if len(group) == 1 else _row_means(members, n_rows)
            empty_field = "Mean" if summary else "Variables"
            zero, zero_rows = _reference(vector, zero_rule, zero_value, options.get("Zero rows", ""),
                                         "Zero rows", empty_field)
            one, one_rows = _reference(vector, one_rule, one_value, options.get("One rows", ""),
                                       "One rows", empty_field)
            for field, anchor in (("Zero reference", zero), ("One reference", one)):
                if not math.isfinite(float(anchor)):
                    raise FieldError(field, f"{field} is outside the supported numeric range.")
            if zero == one:
                raise FieldError("One reference", "The zero and one references are equal.")
            if one < zero and not allow_reversed:
                raise FieldError("One reference",
                                 "The one reference is below the zero reference. "
                                 "Allow reversed references to keep this order.")
            mask = set(zero_rows + one_rows) if blank else set()
            if mask and (zero_rule in (SUM, MEAN_RULE) or one_rule in (SUM, MEAN_RULE)):
                raise FieldError("Reference values in output",
                                 "Blank reference values would remove every value that defines a sum or a mean.")
            value_field = "Mean" if summary else "Variables"
            if replicates == ROW_MEANS and not summary:
                placed = _place(used, label)
                values = [_apply(value, zero, one, span, mask, index, value_field) for index, value in enumerate(vector)]
                ordered[placed] = values
                series_title = placed
                plotted = [(placed, values)]
                roles_y.append([placed])
            else:
                series_title = label
                plotted = []
                role = []
                for name, source in zip(group, members, strict=True):
                    placed = _place(used, name)
                    values = [_apply(value, zero, one, span, mask, index, value_field)
                              for index, value in enumerate(source)]
                    ordered[placed] = values
                    plotted.append((placed, values))
                    role.append(placed)
                roles_y.append(role)
            factor = abs(Decimal(span) / (one - zero))
            if summary and error_format in (SD, SEM):
                _check_magnitude(lower_cells, lower_name, vector, "Error lower")
                ordered[lower_name] = _scaled_errors(lower_cells, vector, mask, factor, "Error lower")
                _place(used, lower_name)
            elif summary and error_format == DISTANCES:
                _check_magnitude(lower_cells, lower_name, vector, "Error lower")
                _check_magnitude(upper_cells, upper_name, vector, "Error upper")
                low_source, high_source = (lower_cells, upper_cells) if one > zero else (upper_cells, lower_cells)
                ordered[lower_name] = _scaled_errors(low_source, vector, mask, factor, "Error lower")
                ordered[upper_name] = _scaled_errors(high_source, vector, mask, factor, "Error upper")
                _place(used, lower_name)
                _place(used, upper_name)
            elif summary and error_format == LIMITS:
                _check_limits(lower_cells, lower_name, vector, "Error lower", upper=False)
                _check_limits(upper_cells, upper_name, vector, "Error upper", upper=True)
                low_source, high_source = (lower_cells, upper_cells) if one > zero else (upper_cells, lower_cells)
                ordered[lower_name] = _scaled_limits(low_source, vector, mask, zero, one, span, "Error lower")
                ordered[upper_name] = _scaled_limits(high_source, vector, mask, zero, one, span, "Error upper")
                _place(used, lower_name)
                _place(used, upper_name)
            if n_cells is not None:
                ordered[n_name] = _sample_sizes(n_cells, vector, mask)
                _place(used, n_name)
            scale = _scale(span, zero, one)
            scale_missing = scale_missing or scale is None
            references.append({
                "Series": series_title,
                "Zero reference": float(zero),
                "One reference": float(one),
                "Scale factor": scale,
                "Zero N": len(zero_rows),
                "One N": len(one_rows),
                "Zero source rows": ",".join(str(row) for row in zero_rows),
                "One source rows": ",".join(str(row) for row in one_rows),
            })
            yerr = _graph_errors(ordered, lower_name, upper_name, plotted[0][1], error_format) if summary else None
            for name, values in plotted:
                graph_lines.append((name, values, yerr if summary else None))

    normalized = pd.DataFrame(ordered, index=frame.index.copy())
    normalized.attrs["worksheet_roles"] = {"x": roles_x, "y": roles_y}
    figure = _graph(frame, graph_lines, x_name, span) if graph else None
    return Result({
        NORMALIZED: normalized,
        REFERENCES: _records(references, REFERENCE_COLUMNS),
        SOURCE_ROWS: _records([{
            "Source row": row,
            "Source index": _plain(value),
        } for row, value in enumerate(frame.index.tolist())], ("Source row", "Source index")),
        SETTINGS: _settings(options, mode, units, zero_rule, one_rule, allow_reversed, blank, graph, replicates,
                            error_format, variables, mean_name, x_name, titles_name, lower_name, upper_name, n_name,
                            zero_value, one_value, scale_missing),
    }, figure)


def _choice(options, field, allowed, default):
    value = options.get(field, default)
    if value not in allowed:
        raise FieldError(field, f"Choose a {field} option.")
    return value


def _flag(options, field, default):
    if field not in options:
        return default
    value = options[field]
    if not isinstance(value, bool):
        raise FieldError(field, f"{field} must be yes or no.")
    return value


def _constant(options, field, default):
    value = options[field] if field in options and options[field] is not None and options[field] != "" else default
    try:
        number = float(decimal_comma(value) if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, f"{field} must be a number.") from None
    if isinstance(value, bool) or not math.isfinite(number):
        raise FieldError(field, f"{field} must be finite.")
    return Decimal(str(number))


def _optional_name(options, field):
    if field not in options:
        return None
    value = options[field]
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise FieldError(field, f"Choose a column for {field}.")
    return value


def _required_name(options, field):
    value = _optional_name(options, field)
    if not value:
        raise FieldError(field, f"Choose a column for {field}.")
    return value


def _variable_names(frame, options, seen):
    value = options.get("Variables")
    if isinstance(value, str) or not isinstance(value, (list, tuple)) or not value:
        raise FieldError("Variables", "Choose a column for Variables.")
    names = []
    for name in value:
        if not isinstance(name, str) or not name:
            raise FieldError("Variables", "Choose a column for Variables.")
        _claim(frame, name, "Variables", seen)
        names.append(name)
    return names


def _claim(frame, name, field, seen):
    if not name:
        return
    if name not in frame:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    if name in seen:
        raise FieldError(field, f'"{name}" is already used as {seen[name]}.')
    seen[name] = field


def _decimals(frame, name, field):
    values = _column(frame, name, field).to_numpy(dtype=float, na_value=np.nan)
    return [None if math.isnan(value) else Decimal(str(float(value))) for value in values]


def _loose(frame, name, field):
    if name not in frame:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    return [_classify(value) for value in frame[name].tolist()]


def _classify(value):
    if value is None:
        return "missing", None
    if isinstance(value, (bool, np.bool_)):
        return "invalid", None
    try:
        if bool(pd.isna(value)):
            return "missing", None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, np.integer)):
        return "number", Decimal(int(value))
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return "invalid", None
        return "number", Decimal(str(float(value)))
    if isinstance(value, Decimal):
        return ("number", value) if value.is_finite() else ("invalid", None)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "missing", None
        try:
            number = Decimal(decimal_comma(text))
        except InvalidOperation:
            return "invalid", None
        return ("number", number) if number.is_finite() else ("invalid", None)
    return "invalid", None


def _rows(text, n_rows, field):
    if not isinstance(text, str) or not text.strip():
        raise FieldError(field, "Enter at least one row, numbered from 1.")
    chosen = set()
    for item in text.split(","):
        if not _ROW_ITEM.fullmatch(item):
            raise FieldError(field, "Use whole row numbers and increasing ranges, such as 1,3-5.")
        numbers = [int(part.strip()) for part in item.split("-")]
        low, high = numbers[0], numbers[-1]
        if high < low or high > n_rows:
            raise FieldError(field, "Row numbers must run from 1 through the last row of the table.")
        # Reject an enormous range before materializing it. Overlaps are counted after insertion.
        if high - low + 1 > _MAX_SELECTED_ROWS:
            raise FieldError(field, "Select at most 100000 rows.")
        chosen.update(range(low - 1, high))
        if len(chosen) > _MAX_SELECTED_ROWS:
            raise FieldError(field, "Select at most 100000 rows.")
    return sorted(chosen)


def _reference(values, rule, constant, selection, rows_field, empty_field):
    pairs = [(index, value) for index, value in enumerate(values) if value is not None]
    if rule == CONSTANT:
        return constant, []
    if rule == SELECTED:
        chosen = set(_rows(selection, len(values), rows_field))
        picked = [(index, value) for index, value in pairs if index in chosen]
        if not picked:
            raise FieldError(rows_field, "The selected rows have no values.")
        total = sum((value for _, value in picked), start=Decimal(0))
        return total / Decimal(len(picked)), [index for index, _ in picked]
    if not pairs:
        raise FieldError(empty_field, "Choose columns with at least one value.")
    if rule == MINIMUM:
        anchor = min(value for _, value in pairs)
        return anchor, [index for index, value in pairs if value == anchor]
    if rule == MAXIMUM:
        anchor = max(value for _, value in pairs)
        return anchor, [index for index, value in pairs if value == anchor]
    if rule in (FIRST_LOW, FIRST_HIGH):
        ends = [pairs[0]] if len(pairs) == 1 else [pairs[0], pairs[-1]]
        anchor = min(value for _, value in ends) if rule == FIRST_LOW else max(value for _, value in ends)
        return anchor, [index for index, value in ends if value == anchor]
    if rule == SUM:
        return sum((value for _, value in pairs), start=Decimal(0)), [index for index, _ in pairs]
    if rule == MEAN_RULE:
        total = sum((value for _, value in pairs), start=Decimal(0))
        return total / Decimal(len(pairs)), [index for index, _ in pairs]
    raise FieldError(rows_field, f"Choose a {rows_field} option.")


def _row_means(members, n_rows):
    means = []
    for index in range(n_rows):
        present = [column[index] for column in members if column[index] is not None]
        means.append(sum(present, start=Decimal(0)) / Decimal(len(present)) if present else None)
    return means


def _apply(value, zero, one, span, mask, index, field):
    if value is None or index in mask:
        return None
    number = float(Decimal(span) * (value - zero) / (one - zero))
    if not math.isfinite(number):
        raise FieldError(field, "A normalized value is outside the numeric range.")
    return number


def _scale(span, zero, one):
    number = float(Decimal(span) / (one - zero))
    return number if math.isfinite(number) else None


def _reject_text(kind, name, field):
    if kind == "invalid":
        raise FieldError(field, f'Column "{name}" contains text or infinite values.')


def _check_magnitude(cells, name, vector, field):
    for index, (kind, number) in enumerate(cells):
        if vector[index] is None or kind == "missing":
            continue
        _reject_text(kind, name, field)
        if number < 0:
            raise FieldError(field, "Error values must be zero or greater.")


def _check_limits(cells, name, vector, field, *, upper):
    for index, (kind, number) in enumerate(cells):
        if vector[index] is None or kind == "missing":
            continue
        _reject_text(kind, name, field)
        if not upper and number > vector[index]:
            raise FieldError(field, "The lower limit must be at or below the mean.")
        if upper and number < vector[index]:
            raise FieldError(field, "The upper limit must be at or above the mean.")


def _scaled_errors(cells, vector, mask, factor, field):
    scaled = []
    for index, (kind, number) in enumerate(cells):
        if index in mask or vector[index] is None or kind != "number":
            scaled.append(None)
            continue
        value = float(number * factor)
        if not math.isfinite(value):
            raise FieldError(field, "A normalized value is outside the numeric range.")
        scaled.append(value)
    return scaled


def _scaled_limits(cells, vector, mask, zero, one, span, field):
    scaled = []
    for index, (kind, number) in enumerate(cells):
        if index in mask or vector[index] is None or kind != "number":
            scaled.append(None)
            continue
        scaled.append(_apply(number, zero, one, span, set(), index, field))
    return scaled


def _sample_sizes(cells, vector, mask):
    sizes = []
    for index, (kind, number) in enumerate(cells):
        if vector[index] is None or kind == "missing":
            sizes.append(None)
            continue
        if kind != "number" or number != number.to_integral_value() or number < 1:
            raise FieldError("N", "N must be a whole number of at least 1.")
        sizes.append(None if index in mask else int(number))
    return sizes


def _literal(series):
    values = []
    for value in series.tolist():
        if isinstance(value, str):
            values.append(value)
            continue
        if value is None:
            values.append(None)
            continue
        try:
            missing = bool(pd.isna(value))
        except (TypeError, ValueError):
            missing = False
        values.append(None if missing else _plain(value))
    return values


def _plain(value):
    return value.item() if isinstance(value, np.generic) else value


def _place(used, name):
    candidate = name
    while candidate in used:
        candidate += " (series)"
    used.add(candidate)
    return candidate


def _records(rows, columns):
    return pd.DataFrame({column: pd.Series([row[column] for row in rows], dtype=object) for column in columns})


def _join(names):
    return list(names) if any("," in name for name in names) else ", ".join(names)


def _settings(options, mode, units, zero_rule, one_rule, allow_reversed, blank, graph, replicates, error_format,
              variables, mean_name, x_name, titles_name, lower_name, upper_name, n_name, zero_value, one_value,
              scale_missing):
    rows = [("Input", mode)]
    if mode == SUMMARY:
        rows.append(("Mean", mean_name))
    else:
        rows.append(("Variables", _join(variables)))
        rows.append(("Replicates", replicates))
    rows.extend((("X", x_name or ""), ("Row titles", titles_name or ""), ("Zero reference", zero_rule),
                 ("One reference", one_rule)))
    if zero_value is not None:
        rows.append(("Zero value", float(zero_value)))
    if one_value is not None:
        rows.append(("One value", float(one_value)))
    if zero_rule == SELECTED:
        rows.append(("Zero rows", options.get("Zero rows", "")))
    if one_rule == SELECTED:
        rows.append(("One rows", options.get("One rows", "")))
    rows.extend((("Units", units), ("Allow reversed references", allow_reversed),
                 ("Reference values in output", BLANK if blank else KEEP)))
    if mode == SUMMARY:
        rows.append(("Error format", error_format))
        rows.append(("Error lower", lower_name or ""))
        if error_format in (DISTANCES, LIMITS):
            rows.append(("Error upper", upper_name or ""))
        rows.append(("N", n_name or ""))
    rows.append(("Graph results", graph))
    rows.append(("Note", UNCERTAINTY_NOTE))
    if scale_missing:
        rows.append(("Scale factor", SCALE_NOTE))
    return _records([{"Setting": key, "Value": value} for key, value in rows], ("Setting", "Value"))


def _graph_errors(ordered, lower_name, upper_name, means, error_format):
    if error_format in (ERR_NONE, None) or not lower_name:
        return None
    if error_format in (SD, SEM):
        return _numbers(ordered[lower_name])
    if error_format == DISTANCES:
        return np.vstack([_numbers(ordered[lower_name]), _numbers(ordered[upper_name])])
    below, above = [], []
    for mean, low, high in zip(means, ordered[lower_name], ordered[upper_name], strict=True):
        if mean is None:
            below.append(np.nan)
            above.append(np.nan)
            continue
        below.append(0.0 if low is None else max(0.0, mean - low))
        above.append(0.0 if high is None else max(0.0, high - mean))
    return np.vstack([below, above])


def _numbers(values):
    return np.array([np.nan if value is None else value for value in values], dtype=float)


def _graph(frame, lines, x_name, span):
    numeric_x = _numeric_axis(frame[x_name]) if x_name is not None else None
    if numeric_x is None:
        x_values = np.arange(1, len(frame.index) + 1, dtype=float)
        xlabel = "Row"
    else:
        x_values = numeric_x
        xlabel = x_name
    figure, axes = _plot(METHOD, xlabel, "Normalized value")
    axes._tramastat_numeric_axes = ("x", "y")
    finite = []
    for index, (name, values, yerr) in enumerate(lines):
        y_values = _numbers(values)
        finite.extend(value for value in y_values if math.isfinite(value))
        color = COLORS[index % len(COLORS)]
        if yerr is None:
            axes.plot(x_values, y_values, color=color, marker="o", linewidth=1.8, label=name)
        else:
            axes.errorbar(x_values, y_values, yerr=yerr, color=color, marker="o", linewidth=1.8, capsize=3, label=name)
            # Explicit limits must include the errors, not only the means. Keep
            # missing-error rows missing and retain both sides of asymmetry.
            errors = np.broadcast_to(np.asarray(yerr, dtype=float), (2, len(y_values)))
            with np.errstate(over="ignore", invalid="ignore"):
                bounds = np.stack((y_values - errors[0], y_values + errors[1]))
            finite.extend(bounds[np.isfinite(bounds)].tolist())
    for level, gid in ((0.0, _GUIDE_ZERO), (float(span), _GUIDE_ONE)):
        guide = axes.axhline(level, color="#9aa0a6", linewidth=0.8, linestyle=(0, (1, 2)), zorder=0)
        guide.set_gid(gid)
        guide.set_label("_nolegend_")
    if lines:
        axes.legend()
    low = min([0.0, float(span), *finite]) if finite else min(0.0, float(span))
    high = max([0.0, float(span), *finite]) if finite else max(0.0, float(span))
    if low == high:
        low -= 1.0
        high += 1.0
    pad = (high - low) * 0.06
    axes.set_ylim(low - pad, high + pad)
    return figure


def _numeric_axis(series):
    if pd.api.types.is_bool_dtype(series) or not pd.api.types.is_numeric_dtype(series):
        return None
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
