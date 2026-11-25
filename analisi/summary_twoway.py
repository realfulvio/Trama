"""Two-way ANOVA from cell summaries: mean, SD or SEM, and N.

The design is one row per factorial cell. Sample size is a weight, never a count of
manufactured replicates. The hypothesis sums of squares are Type III contrasts of the
cell means; the denominator is the pooled within-cell sum of squares.
"""
import re
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd
from scipy import stats
from scipy.linalg import solve_triangular

from .anova_diagnostics import ASSUMPTIONS, DIAGNOSTICS, GRAPH, GRAPH_NONE
from .field_error import FieldError
from .i18n import translate_message
from .reporting import Result

METHOD = "Two-way ANOVA from summaries"
INPUT = "Input"
SUBCOLUMNS = "Summary subcolumns"
ROWS = "Groups in rows"
ROW_LABELS = "Row labels"
VARIABLES = "Variables"
ROW_FACTOR = "Row factor variable"
COLUMN_FACTOR = "Column factor variable"
MEAN = "Mean"
DISPERSION = "Dispersion"
SAMPLE_SIZE = "Sample size"
DISPERSION_TYPE = "Dispersion type"
SD, SEM = "SD", "SEM"
ROW_NAME = "Row factor name"
COLUMN_NAME = "Column factor name"
ANOVA_SHEET = "ANOVA (type III)"
SUMMARY_SHEET = "Summaries used"
SETTINGS_SHEET = "Settings"
RESIDUAL = "Residual"
TOTAL = "Corrected total"
SOURCE_ROW = "Source row"
ERROR_PREFIX = "summary.twoway.error."
_MAX_LEVELS = 64
_MAX_CELLS = 1024
_SUBCOLUMN = re.compile(r"(.+) \[(Mean|SD|SEM|N)\]( \(\d+\))?\Z")
_ROLES = ("Mean", "SD", "SEM", "N")
_RESERVED = {RESIDUAL, TOTAL, MEAN, SD, SEM, "N", SOURCE_ROW}

# English sentences. interface_catalog registers the Italian text under ERROR_PREFIX.
ERRORS = {
    "input": "Choose summary subcolumns or groups in rows.",
    "dispersion": "Choose SD or SEM.",
    "infer": "Choose SD or SEM. The selected summaries do not show one dispersion.",
    "unique": "Worksheet column names must be unique.",
    "row": "Choose the column with the row factor levels.",
    "variables": "Select the Mean, SD or SEM, and N subcolumns for each column group.",
    "subcolumn": "Select only named Mean, SD, SEM or N subcolumns.",
    "role": "Each column group must have unique summary roles.",
    "triple": "Each column group needs Mean, the chosen dispersion and N.",
    "column": "Choose an existing column for {field}.",
    "distinct": "The two factors and the summary columns must be distinct.",
    "name": "Enter a factor name of up to 160 characters.",
    "reserved": 'Choose a factor name other than "{name}".',
    "colon": "A factor name cannot contain a colon.",
    "same": "Choose different names for the two factors.",
    "finite": "Summary values must be finite numbers.",
    "nonnegative": "Dispersion must be nonnegative.",
    "conversion": "The SD conversion is outside the supported numeric range.",
    "size": "Each sample size must be an integer from 2 to 2^53.",
    "partial": "Cell {row_level} × {column_level} is incomplete or excluded ({role}).",
    "partial_row": "Row {source_row} is incomplete or excluded ({role}).",
    "blank": "Each included row needs a nonempty level name.",
    "duplicate": "The combination {row_level} × {column_level} appears more than once.",
    "missing": "The combination {row_level} × {column_level} is missing.",
    "levels": "{factor} needs at least two levels.",
    "variance": "The pooled residual variance is zero.",
    "repeated": "Repeated measures cannot be estimated from cell summaries.",
    "diagnostics": "Residual diagnostics need the observations. Cell summaries do not keep them.",
    "type3": "This analysis reports Type III sums of squares only.",
    "interaction": "The model is the full crossing with interaction.",
    "comparisons": "Comparisons that need the observations are not available from cell summaries.",
    "numeric": "The sums of squares could not be computed reliably for this grid.",
    "total": "The total sample size must not exceed 2^53.",
    "grid": "Provide a complete grid with at least two levels of each factor.",
    "large": "This grid has too many cells for the summary ANOVA.",
}
EQUAL_WEIGHT = (
    "Equal-weight marginal means are estimates of sum-to-zero contrasts: each cell mean has the "
    "same weight, whatever its sample size. This table is not the estimated marginal means sheet."
)
UNEQUAL_N = (
    "Sample sizes differ across cells. The Type III sums of squares do not add up to the corrected total."
)
BALANCED_N = (
    "Sample sizes are equal. On this grid the Type III sums of squares and the residual sum of "
    "squares add up to the corrected total."
)
INDEPENDENCE = (
    "Observations are assumed independent, with one common variance. Cell summaries cannot "
    "reconstruct repeated measures, residuals, normality or the data distribution."
)
OPTIONS = {
    INPUT: (SUBCOLUMNS, ROWS),
    ROW_LABELS: None,
    VARIABLES: "Multiple (optional)",
    ROW_FACTOR: None,
    COLUMN_FACTOR: None,
    MEAN: None,
    DISPERSION: None,
    SAMPLE_SIZE: None,
    DISPERSION_TYPE: (SD, SEM),
    ROW_NAME: "Text",
    COLUMN_NAME: "Text",
}
LABEL_KEYS = {
    METHOD: "interface." + METHOD,
    INPUT: "interface." + INPUT,
    SUBCOLUMNS: "interface." + SUBCOLUMNS,
    ROWS: "interface." + ROWS,
    ROW_LABELS: "interface." + ROW_LABELS,
    VARIABLES: "interface." + VARIABLES,
    ROW_FACTOR: "interface." + ROW_FACTOR,
    COLUMN_FACTOR: "interface." + COLUMN_FACTOR,
    MEAN: "interface." + MEAN,
    DISPERSION: "interface." + DISPERSION,
    SAMPLE_SIZE: "interface." + SAMPLE_SIZE,
    DISPERSION_TYPE: "interface." + DISPERSION_TYPE,
    ROW_NAME: "interface." + ROW_NAME,
    COLUMN_NAME: "interface." + COLUMN_NAME,
}


def visibility(mode):
    """Which dialog fields belong to the selected arrangement."""
    subcolumns = mode == SUBCOLUMNS
    rows = mode == ROWS
    return {
        ROW_LABELS: subcolumns,
        VARIABLES: subcolumns,
        ROW_FACTOR: rows,
        COLUMN_FACTOR: rows,
        MEAN: rows,
        DISPERSION: rows,
        SAMPLE_SIZE: rows,
        DISPERSION_TYPE: True,
        ROW_NAME: True,
        COLUMN_NAME: True,
    }


def looks_like_subcolumns(frame):
    """True when a column already uses the grouped Mean/SD/SEM/N header."""
    return any(isinstance(name, str) and _SUBCOLUMN.fullmatch(name) for name in frame.columns)


def format_error(error):
    """The engine sentence in the active language. Unknown text is left unchanged."""
    return translate_message(str(error), ERROR_PREFIX)


def _fail(field, key, **values):
    raise FieldError(field, ERRORS[key].format(**values))


def _missing(value):
    return (value is None or value is pd.NA or value is pd.NaT
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, (float, np.floating)) and np.isnan(value)))


def _number(value, field):
    try:
        if isinstance(value, (bool, np.bool_)):
            raise ValueError
        number = float(value)
        if not np.isfinite(number):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        _fail(field, "finite")
    return number


def _size(value, field):
    try:
        if isinstance(value, (bool, np.bool_)):
            raise ValueError
        number = Decimal(str(value).strip())
        if not number.is_finite() or number != number.to_integral_value() or not 2 <= number <= 2**53:
            raise ValueError
    except (ValueError, InvalidOperation, ArithmeticError):
        _fail(field, "size")
    return int(number)


def _label(value, field):
    if isinstance(value, str):
        if not value.strip():
            _fail(field, "blank")
        return value
    if _missing(value) or isinstance(value, (bool, np.bool_)):
        _fail(field, "blank")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(float(value)):
            _fail(field, "blank")
        return str(int(value)) if float(value) == int(value) else str(float(value))
    text = str(value)
    if not text.strip():
        _fail(field, "blank")
    return text


def _reject_unsupported(options):
    if options.get("Subject") not in (None, "") or options.get("Repeated measures") not in (None, False, ""):
        _fail("Subject" if options.get("Subject") not in (None, "") else "Repeated measures", "repeated")
    if options.get("Linear trend") not in (None, False, ""):
        _fail("Linear trend", "comparisons")
    if options.get(DIAGNOSTICS) not in (None, False) or options.get(ASSUMPTIONS) not in (None, False):
        _fail(DIAGNOSTICS, "diagnostics")
    if options.get(GRAPH, GRAPH_NONE) not in (None, "", GRAPH_NONE):
        _fail(GRAPH, "diagnostics")
    if "Sums of squares" in options and options.get("Sums of squares") not in (None, "", "Type III"):
        _fail("Sums of squares", "type3")
    if "Include interaction" in options and options.get("Include interaction") is False:
        _fail("Include interaction", "interaction")
    if options.get("Post-hoc", None) not in (None, "", "None"):
        _fail("Post-hoc", "comparisons")


def _factor_name(options, field, default):
    name = options.get(field, "")
    if name is None:
        name = ""
    if not isinstance(name, str) or len(name) > 160:
        _fail(field, "name")
    name = name.strip() or default
    if ":" in name:
        _fail(field, "colon")
    if name in _RESERVED:
        _fail(field, "reserved", name=name)
    return name


def _dispersion_type(options, available):
    """Explicit SD or SEM, or the single dispersion role present on every selected group."""
    requested = options.get(DISPERSION_TYPE, None)
    if requested is None or requested == "":
        if available == {SD} or available == {SEM}:
            return next(iter(available))
        _fail(DISPERSION_TYPE, "infer")
    if requested not in (SD, SEM):
        _fail(DISPERSION_TYPE, "dispersion")
    return requested


def _column(frame, options, field):
    name = options.get(field)
    if not isinstance(name, str) or name not in frame.columns:
        _fail(field, "column", field=field)
    return name


def _groups(frame, selected):
    groups = {}
    order = []
    for column in selected:
        if not isinstance(column, str) or column not in frame.columns:
            _fail(VARIABLES, "variables")
        match = _SUBCOLUMN.fullmatch(column)
        if not match:
            _fail(VARIABLES, "subcolumn")
        name = match.group(1) + (match.group(3) or "")
        role = match.group(2)
        group = groups.setdefault(name, {})
        if role in group:
            _fail(VARIABLES, "role")
        if name not in order:
            order.append(name)
        group[role] = column
    return [(name, groups[name]) for name in order]


def _selected_subcolumns(frame, options, row_labels):
    selected = options.get(VARIABLES)
    if selected is None or selected == []:
        selected = [name for name in frame.columns if name != row_labels and isinstance(name, str)
                    and _SUBCOLUMN.fullmatch(name)]
    if isinstance(selected, str) or not isinstance(selected, (list, tuple)) or not selected:
        _fail(VARIABLES, "variables")
    if len(set(selected)) != len(selected):
        _fail(VARIABLES, "variables")
    return list(selected)


def _cells_from_subcolumns(frame, options):
    row_labels = options.get(ROW_LABELS)
    if not isinstance(row_labels, str) or row_labels not in frame.columns:
        _fail(ROW_LABELS, "row")
    grouped = _groups(frame, _selected_subcolumns(frame, options, row_labels))
    if len(grouped) < 2:
        _fail(VARIABLES, "grid")
    available = set()
    for _, roles in grouped:
        available.update(role for role in roles if role in (SD, SEM))
    kind = _dispersion_type(options, available)
    for _, roles in grouped:
        if not {"Mean", kind, "N"} <= roles.keys():
            _fail(VARIABLES, "triple")
    records = []
    for row in range(len(frame)):
        level = _label(frame.iloc[row][row_labels], ROW_LABELS)
        for column_level, roles in grouped:
            values = {role: frame.iloc[row][roles[role]] for role in ("Mean", kind, "N")}
            missing = [role for role, value in values.items() if _missing(value)]
            if missing:
                _fail(VARIABLES, "partial", row_level=level, column_level=column_level,
                      role=", ".join(missing))
            records.append(_record(row + 1, level, column_level, values["Mean"], values[kind], values["N"],
                                   kind, VARIABLES, VARIABLES))
    return records, kind


def _cells_from_rows(frame, options):
    fields = (ROW_FACTOR, COLUMN_FACTOR, MEAN, DISPERSION, SAMPLE_SIZE)
    columns = [_column(frame, options, field) for field in fields]
    if len(set(columns)) != len(columns):
        _fail(MEAN, "distinct")
    kind = _dispersion_type(options, _infer_long(columns[3]))
    records = []
    for row in range(len(frame)):
        raw = [frame.iloc[row][column] for column in columns]
        if all(_missing(value) for value in raw):
            continue
        missing = [field for field, value in zip(fields, raw) if _missing(value)]
        if missing:
            role = {"Mean": "Mean", DISPERSION: kind, SAMPLE_SIZE: "N"}.get(missing[0], missing[0])
            _fail(missing[0], "partial_row", source_row=row + 1, role=role)
        records.append(_record(row + 1, _label(raw[0], ROW_FACTOR), _label(raw[1], COLUMN_FACTOR),
                               raw[2], raw[3], raw[4], kind, DISPERSION, SAMPLE_SIZE))
    return records, kind


def _infer_long(column):
    text = column.strip()
    if text in {SEM, "sem"} or text.endswith("[SEM]"):
        return {SEM}
    if text in {SD, "sd"} or text.endswith("[SD]"):
        return {SD}
    return set()


def _record(source_row, row_level, column_level, mean, dispersion, size, kind, dispersion_field, size_field):
    mean = _number(mean, MEAN if dispersion_field != VARIABLES else VARIABLES)
    dispersion = _number(dispersion, dispersion_field)
    size = _size(size, size_field if size_field != VARIABLES else VARIABLES)
    if dispersion < 0:
        _fail(dispersion_field, "nonnegative")
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        deviation = dispersion * np.sqrt(size) if kind == SEM else dispersion
        error = deviation / np.sqrt(size)
    if not np.isfinite(deviation) or not np.isfinite(error) or (dispersion > 0 and deviation == 0):
        _fail(dispersion_field, "conversion")
    return {
        "source_row": source_row,
        "row_level": row_level,
        "column_level": column_level,
        "Mean": mean,
        "SD": float(deviation),
        "SEM": float(error),
        "N": size,
    }


def _complete(records, row_field, column_field, row_name, column_name, size_field):
    seen = {}
    row_levels, column_levels = [], []
    for record in records:
        key = (record["row_level"], record["column_level"])
        if key in seen:
            _fail(row_field, "duplicate", row_level=key[0], column_level=key[1])
        seen[key] = record
        if record["row_level"] not in row_levels:
            row_levels.append(record["row_level"])
        if record["column_level"] not in column_levels:
            column_levels.append(record["column_level"])
    if len(row_levels) < 2:
        _fail(row_field, "levels", factor=row_name)
    if len(column_levels) < 2:
        _fail(column_field, "levels", factor=column_name)
    if (len(row_levels) > _MAX_LEVELS or len(column_levels) > _MAX_LEVELS
            or len(row_levels) * len(column_levels) > _MAX_CELLS):
        _fail(row_field, "large")
    ordered = []
    for row_level in row_levels:
        for column_level in column_levels:
            record = seen.get((row_level, column_level))
            if record is None:
                _fail(row_field, "missing", row_level=row_level, column_level=column_level)
            ordered.append(record)
    if sum(record["N"] for record in ordered) > 2**53:
        _fail(size_field, "total")
    return ordered, row_levels, column_levels


def check_options(frame, options):
    """Validate the recipe and return the cell summaries in first-seen level order.

    The result is ``(cells, row factor name, column factor name, dispersion type)``.
    ``cells`` has one row per factorial cell. Nothing here allocates storage proportional to N.
    """
    if not frame.columns.is_unique:
        _fail(VARIABLES, "unique")
    _reject_unsupported(options)
    mode = options.get(INPUT, SUBCOLUMNS)
    if mode == SUBCOLUMNS:
        records, kind = _cells_from_subcolumns(frame, options)
        row_field, column_field, size_field = ROW_LABELS, VARIABLES, VARIABLES
        row_default, column_default = "Row factor", "Column factor"
    elif mode == ROWS:
        records, kind = _cells_from_rows(frame, options)
        row_field, column_field, size_field = ROW_FACTOR, COLUMN_FACTOR, SAMPLE_SIZE
        row_default = options.get(ROW_FACTOR) if isinstance(options.get(ROW_FACTOR), str) else "Row factor"
        column_default = (options.get(COLUMN_FACTOR) if isinstance(options.get(COLUMN_FACTOR), str)
                          else "Column factor")
    else:
        _fail(INPUT, "input")
    row_name = _factor_name(options, ROW_NAME, row_default)
    column_name = _factor_name(options, COLUMN_NAME, column_default)
    if row_name == column_name:
        _fail(COLUMN_NAME, "same")
    ordered, row_levels, column_levels = _complete(
        records, row_field, column_field, row_name, column_name, size_field)
    cells = pd.DataFrame(ordered)
    cells.attrs["row_levels"] = row_levels
    cells.attrs["column_levels"] = column_levels
    return cells, row_name, column_name, kind


def _contrasts(labels, levels):
    """Sum-to-zero columns. The last level is the reference; the column space does not depend on that choice."""
    index = {level: position for position, level in enumerate(levels)}
    codes = np.fromiter((index[label] for label in labels), dtype=np.int64, count=len(labels))
    one = np.zeros((len(labels), len(levels)), dtype=np.float64)
    one[np.arange(len(labels)), codes] = 1.0
    return one[:, :-1] - one[:, -1:]


def _weighted_rss(design, response, weights):
    scale = np.sqrt(weights)
    weighted = np.ascontiguousarray(design * scale[:, None], dtype=np.float64)
    target = np.ascontiguousarray(response * scale, dtype=np.float64)
    q, r = np.linalg.qr(weighted, mode="reduced")
    diagonal = np.abs(np.diag(r))
    limit = np.finfo(np.float64).eps * max(weighted.shape) * (diagonal.max() if diagonal.size else 1.0)
    if not diagonal.size or diagonal.min() <= limit:
        _fail(DISPERSION, "numeric")
    beta = solve_triangular(r, q.T @ target, check_finite=False)
    residual = target - weighted @ beta
    total = float(residual @ residual)
    if not np.isfinite(total):
        _fail(DISPERSION, "numeric")
    return total


def _type_iii(cells):
    """Type III sums of squares for A, B and A×B, plus the within-cell residual and the corrected total."""
    means = cells["Mean"].to_numpy(dtype=np.float64)
    sizes = cells["N"].to_numpy(dtype=np.float64)
    deviations = cells["SD"].to_numpy(dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        residual = float(np.sum((sizes - 1.0) * deviations**2))
    degrees = int(np.sum(sizes - 1.0))
    if not np.isfinite(residual) or residual <= 0 or degrees < 1:
        _fail(DISPERSION, "variance" if residual == 0 else "numeric")
    centered = means - np.median(means)
    row = _contrasts(cells["row_level"], cells.attrs["row_levels"])
    column = _contrasts(cells["column_level"], cells.attrs["column_levels"])
    interaction = (row[:, :, None] * column[:, None, :]).reshape(len(cells), -1)
    blocks = (row, column, interaction)
    intercept = np.ones((len(cells), 1), dtype=np.float64)
    full = np.column_stack([intercept, *blocks])
    full_rss = _weighted_rss(full, centered, sizes)
    tolerance = 1e-8 * (float(np.sum(sizes * centered**2)) + 1.0) + 1e-8
    if full_rss > tolerance:
        _fail(DISPERSION, "numeric")
    sums = []
    for index, block in enumerate(blocks):
        reduced = np.column_stack([intercept, *[other for other_index, other in enumerate(blocks)
                                                if other_index != index]])
        sums.append(_weighted_rss(reduced, centered, sizes) - full_rss)
    if not np.isfinite(sums).all() or min(sums) < -tolerance:
        _fail(DISPERSION, "numeric")
    sums = [max(0.0, value) for value in sums]
    grand = float(np.average(means, weights=sizes))
    with np.errstate(over="ignore", invalid="ignore"):
        between = float(np.sum(sizes * (means - grand)**2))
    total = residual + between
    if not np.isfinite(total):
        _fail(DISPERSION, "numeric")
    return sums, residual, degrees, total, int(sizes.sum()) - 1


def summary_twoway(frame, options):
    """Type III two-way ANOVA from the sufficient statistics of a complete factorial grid."""
    cells, row_name, column_name, kind = check_options(frame, options)
    sums, residual, residual_df, total, total_df = _type_iii(cells)
    degrees = (
        len(cells.attrs["row_levels"]) - 1,
        len(cells.attrs["column_levels"]) - 1,
        (len(cells.attrs["row_levels"]) - 1) * (len(cells.attrs["column_levels"]) - 1),
    )
    denominator = residual / residual_df
    names = (row_name, column_name, f"{row_name}:{column_name}")
    rows = []
    for name, ss, df in zip(names, sums, degrees, strict=True):
        mean_square = ss / df
        statistic = mean_square / denominator
        if not np.isfinite(statistic):
            _fail(DISPERSION, "numeric")
        rows.append({"Term": name, "SS": ss, "df": df, "MS": mean_square, "F": statistic,
                     "p": float(stats.f.sf(statistic, df, residual_df))})
    rows.append({"Term": RESIDUAL, "SS": residual, "df": residual_df, "MS": denominator})
    rows.append({"Term": TOTAL, "SS": total, "df": total_df})
    anova = pd.DataFrame(rows).set_index("Term")
    summaries = cells.rename(columns={"row_level": row_name, "column_level": column_name,
                                      "source_row": SOURCE_ROW})
    summaries = summaries[[row_name, column_name, "Mean", "SD", "SEM", "N", SOURCE_ROW]]
    equal = len(set(cells["N"].tolist())) == 1
    settings = pd.DataFrame({
        "Setting": ["Model", "Sums of squares", "Input", "Dispersion type", "Row factor", "Column factor",
                    "Cells", "Total N", "Residual df", "Equal-weight means", "Balance", "Independence"],
        "Value": ["Two-way ANOVA, fixed crossed factors, with interaction", "Type III",
                  options.get(INPUT, SUBCOLUMNS), kind, row_name, column_name, len(cells),
                  int(cells["N"].sum()), residual_df, EQUAL_WEIGHT, BALANCED_N if equal else UNEQUAL_N,
                  INDEPENDENCE],
    })
    return Result({ANOVA_SHEET: anova, SUMMARY_SHEET: summaries, SETTINGS_SHEET: settings})
