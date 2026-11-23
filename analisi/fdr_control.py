"""False-discovery control for selected p columns and declared families.

Benjamini–Hochberg, Benjamini–Yekutieli and the two-stage Benjamini–Krieger–Yekutieli
procedure are step-up tests. The comparison is inclusive (``p <= alpha * rank / m``).
BH/BY adjusted values are independent of the requested level; two-stage BKY adjusted
values are level-specific. Discovery decisions always use the requested FDR. Equal p values share the adjusted value
and the decision. The rank is only the stable order statistic used by the step-up rule.

For two-stage BKY, ``m0`` is the stage-1 estimate ``m - R1``. It is not ``m`` minus the
final number of discoveries. When stage 1 rejects nothing or everything, the procedure
stops there and does not divide by ``m0``.

``operations.adjust_p`` is a different analysis and is left unchanged.
"""
import math
from collections.abc import Sequence

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from .field_error import FieldError
from .reporting import Result

METHOD = "Control false discoveries"
P_COLUMNS = "p columns"
FAMILY_COLUMNS = "Family columns"
SCOPE = "Family scope"
FDR_METHOD = "FDR method"
LEVEL = "Desired FDR (%)"
PLOT = "Show diagnostic plot"

SCOPE_EACH = "Each column separately"
SCOPE_POOL = "Pool selected columns"
SCOPES = (SCOPE_EACH, SCOPE_POOL)

BH = "Benjamini–Hochberg"
BY = "Benjamini–Yekutieli"
BKY = "Two-stage Benjamini–Krieger–Yekutieli"
FDR_METHODS = (BH, BY, BKY)
METHOD_CODES = {BH: "bh", BY: "by", BKY: "bky"}

RESULTS = "FDR results"
FAMILIES = "FDR families"
SETTINGS = "Settings"

STATUS_USED = "Used"
STATUS_MISSING_P = "Missing p"
STATUS_MISSING_FAMILY = "Missing family"
EMPTY_REASON = "No used p values"
POOLED = "Pooled"

MAX_P_COLUMNS = 24
MAX_FAMILY_COLUMNS = 4
MAX_CELLS = 200_000
MAX_FAMILIES = 200
MAX_PLOT_FAMILIES = 12

_FIELDS = {P_COLUMNS, FAMILY_COLUMNS, SCOPE, FDR_METHOD, LEVEL, PLOT}
_RESERVED = {"Source row", "Variable", "p", "Adjusted p", "Discovery", "Status", "Rank", "Threshold"}
_CODES = {"bh", "by", "bky"}

ERR_P_COUNT = "Select between 1 and 24 distinct p columns."
ERR_FAMILY_COUNT = "Select at most 4 distinct family columns."
ERR_OVERLAP = "A p column cannot also be a family column."
ERR_MISSING = "Column {column} is not in the table."
ERR_DUPLICATE = "Column {column} occurs more than once in the table."
ERR_RESERVED = "Family column {column} uses a reserved result name."
ERR_SCOPE = "Choose Each column separately or Pool selected columns."
ERR_METHOD = "Choose Benjamini–Hochberg, Benjamini–Yekutieli, or Two-stage Benjamini–Krieger–Yekutieli."
ERR_LEVEL = "Enter a finite number strictly between 0 and 100."
ERR_PLOT = "Choose whether to show the diagnostic plot."
ERR_P = "Column {column} contains a value that is not a finite p in [0, 1]."
ERR_CELLS = "Use at most 200000 p values."
ERR_FAMILIES = "Use at most 200 nonempty families."
ERR_PLOT_FAMILIES = "A diagnostic plot shows at most 12 families."

DEPENDENCE_NOTE = (
    "Benjamini–Hochberg and two-stage Benjamini–Krieger–Yekutieli control the FDR under their "
    "stated dependence conditions. Benjamini–Yekutieli is more conservative and does not require "
    "independence. Trama does not test whether the hypotheses are independent."
)
LEVEL_NOTE = (
    "BH and BY adjusted p values are independent of the requested FDR. "
    "Two-stage BKY adjusted p values depend on that level and must be recalculated for another FDR. "
    "Discovery decisions always use the requested level."
)
STEP_NOTE = (
    "After a stable sort, the procedure finds the largest rank i with p(i) <= alpha * i / m "
    "and rejects every rank through i. A rank-wise threshold is not an independent decision. "
    "Equal p values share the adjusted value and the decision."
)
BKY_NOTE = (
    "m0 is the stage-1 estimate m - R1. It is not m minus the final number of discoveries. "
    "When R1 is 0 or m, the procedure stops after stage 1 and does not divide by m0."
)


class _Cell:
    __slots__ = ("source_row", "variable", "family_key", "family_values", "p", "status",
                 "adjusted", "discovery", "rank", "threshold")

    def __init__(self, source_row, variable, family_key, family_values, p, status):
        self.source_row = source_row
        self.variable = variable
        self.family_key = family_key
        self.family_values = family_values
        self.p = p
        self.status = status
        self.adjusted = None
        self.discovery = None
        self.rank = None
        self.threshold = None


def adjust_family(values, method, q):
    """Adjust one nonempty family. ``method`` is bh, by or bky; ``q`` is a fraction in (0, 1)."""
    if method not in _CODES:
        raise ValueError("Unknown FDR method.")
    try:
        level = float(q)
    except (TypeError, ValueError):
        raise ValueError("q must be a fraction in (0, 1).") from None
    if isinstance(q, (bool, str, bytes)) or not math.isfinite(level) or not 0 < level < 1:
        raise ValueError("q must be a fraction in (0, 1).")
    try:
        original = list(values)
        observed = [float(value) for value in original]
    except (TypeError, ValueError):
        raise ValueError("Invalid p family.") from None
    if (not observed or any(isinstance(value, (bool, np.bool_)) for value in original)
            or any(not math.isfinite(value) or not 0 <= value <= 1 for value in observed)):
        raise ValueError("Invalid p family.")
    count = len(observed)
    scores = np.asarray(observed, dtype=float)
    # mergesort is stable, so tied p values keep their original family order.
    order = np.argsort(scores, kind="stable")
    ordered = scores[order]
    ranks = np.arange(1, count + 1, dtype=float)

    def step(alpha):
        passed = np.flatnonzero(ordered <= alpha * ranks / count)
        return int(passed[-1] + 1) if passed.size else 0

    raw = ordered * count / ranks
    bh = np.minimum.accumulate(raw[::-1])[::-1]
    if method == "bh":
        factor = 1.0
        stage_one = stage_zero = None
        alphas = [level]
        rejected_count = step(level)
    elif method == "by":
        harmonic = math.fsum(1.0 / rank for rank in range(1, count + 1))
        factor = harmonic
        stage_one = stage_zero = None
        alphas = [level / harmonic]
        rejected_count = step(alphas[0])
    else:
        first = level / (1.0 + level)
        stage_one = step(first)
        stage_zero = count - stage_one
        alphas = [first]
        if stage_one in (0, count):
            # R1 == m leaves m0 at 0. Stop instead of dividing, and do not zero the adjusted values.
            factor = 1.0 + level
            rejected_count = stage_one
        else:
            second = first * count / stage_zero
            alphas.append(second)
            rejected_count = step(second)
            factor = (1.0 + level) * stage_zero / count
    scaled = np.minimum(bh * factor, 1.0)
    adjusted = np.empty(count, dtype=float)
    adjusted[order] = scaled
    rejected = np.zeros(count, dtype=bool)
    if rejected_count:
        rejected[order[:rejected_count]] = True
    return {
        "adjusted": adjusted.tolist(),
        "rejected": [bool(value) for value in rejected.tolist()],
        "order": [int(index) for index in order.tolist()],
        "r1": stage_one,
        "m0": stage_zero,
        "stage_alphas": [float(alpha) for alpha in alphas],
    }


def _sequence(value, field, message):
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FieldError(field, message)
    return list(value)


def _locate(columns, name, field):
    matches = [index for index, column in enumerate(columns) if column == name]
    if not matches:
        raise FieldError(field, ERR_MISSING.format(column=name))
    if len(matches) != 1:
        raise FieldError(field, ERR_DUPLICATE.format(column=name))
    return matches[0]


def _missing(value):
    if value is None or value is pd.NA:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, (bool, np.bool_)) else False


def _as_p(value, column):
    if isinstance(value, (bool, np.bool_)):
        raise FieldError(P_COLUMNS, ERR_P.format(column=column))
    if isinstance(value, str):
        if value.strip() == "":
            return None
        raise FieldError(P_COLUMNS, ERR_P.format(column=column))
    if _missing(value):
        return None
    if isinstance(value, (int, np.integer, float, np.floating)):
        number = float(value)
        if math.isfinite(number) and 0 <= number <= 1:
            return number
    raise FieldError(P_COLUMNS, ERR_P.format(column=column))


def _token(value):
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, (bool, np.bool_)):
        return ("bool", bool(value))
    if isinstance(value, (int, np.integer)):
        return ("int", int(value))
    if isinstance(value, (float, np.floating)):
        return ("float", float(value))
    try:
        hash(value)
    except TypeError:
        return (type(value).__name__, repr(value))
    return (type(value).__name__, value)


def _family_label(values, names):
    if not names:
        return "All rows"
    return ", ".join(f"{name}={value!r}" if isinstance(value, str) else f"{name}={value}"
                     for name, value in zip(names, values, strict=True))


def discovery_level(options):
    """Read the percentage common to worksheet and pairwise FDR analyses."""
    level = options.get(LEVEL, 5.0)
    if isinstance(level, bool) or not isinstance(level, (int, np.integer, float, np.floating)):
        raise FieldError(LEVEL, ERR_LEVEL)
    level = float(level)
    if not math.isfinite(level) or not 0 < level < 100:
        raise FieldError(LEVEL, ERR_LEVEL)
    return level


def _request(options):
    if not isinstance(options, dict):
        raise FieldError(P_COLUMNS, ERR_P_COUNT)
    p_columns = _sequence(options.get(P_COLUMNS), P_COLUMNS, ERR_P_COUNT)
    if not 1 <= len(p_columns) <= MAX_P_COLUMNS or len(set(p_columns)) != len(p_columns):
        raise FieldError(P_COLUMNS, ERR_P_COUNT)
    family_columns = _sequence(options.get(FAMILY_COLUMNS) or (), FAMILY_COLUMNS, ERR_FAMILY_COUNT)
    if len(family_columns) > MAX_FAMILY_COLUMNS or len(set(family_columns)) != len(family_columns):
        raise FieldError(FAMILY_COLUMNS, ERR_FAMILY_COUNT)
    if set(p_columns) & set(family_columns):
        raise FieldError(FAMILY_COLUMNS, ERR_OVERLAP)
    reserved = next((name for name in family_columns if name in _RESERVED), None)
    if reserved is not None:
        raise FieldError(FAMILY_COLUMNS, ERR_RESERVED.format(column=reserved))
    scope = options.get(SCOPE, SCOPE_EACH)
    if scope not in SCOPES:
        raise FieldError(SCOPE, ERR_SCOPE)
    method_name = options.get(FDR_METHOD, BH)
    if method_name not in METHOD_CODES:
        raise FieldError(FDR_METHOD, ERR_METHOD)
    level = discovery_level(options)
    plot = options.get(PLOT, False)
    if not isinstance(plot, (bool, np.bool_)):
        raise FieldError(PLOT, ERR_PLOT)
    return {
        "p_columns": p_columns,
        "family_columns": family_columns,
        "scope": scope,
        "method_name": method_name,
        "method": METHOD_CODES[method_name],
        "level": level,
        "q": level / 100.0,
        "plot": bool(plot),
    }


def _column(frame, index):
    """One positional column as an array. A view is only read, never written back."""
    series = frame.iloc[:, index]
    try:
        return series.to_numpy(copy=False)
    except (TypeError, ValueError):
        return series.to_numpy(dtype=object)


def _prepare(frame, options):
    """Validate fields, domains and budgets. Does not adjust p values or build a figure."""
    request = _request(options)
    columns = list(frame.columns)
    p_index = [_locate(columns, name, P_COLUMNS) for name in request["p_columns"]]
    family_index = [_locate(columns, name, FAMILY_COLUMNS) for name in request["family_columns"]]
    p_values = [_column(frame, index) for index in p_index]
    family_values_cols = [_column(frame, index) for index in family_index]
    # Every non-missing p is judged before a missing family removes the row from the test.
    # Row order, then the selected p-column order, so the first invalid cell is stable.
    groups = []
    group_values = {}
    seen = {}
    cells = []
    opened = set()
    used_count = 0
    names = request["p_columns"]
    pooled = request["scope"] == SCOPE_POOL
    for row in range(len(frame)):
        family_values = tuple(column[row] for column in family_values_cols)
        if any(_missing(value) for value in family_values):
            family_key = None
        else:
            family_key = tuple(_token(value) for value in family_values)
            if family_key not in seen:
                seen[family_key] = len(groups)
                groups.append(family_key)
                group_values[family_key] = family_values
        for name, column in zip(names, p_values, strict=True):
            number = _as_p(column[row], name)
            if family_key is None:
                status = STATUS_MISSING_FAMILY
            elif number is None:
                status = STATUS_MISSING_P
            else:
                status = STATUS_USED
                used_count += 1
                if used_count > MAX_CELLS:
                    raise FieldError(P_COLUMNS, ERR_CELLS)
                identity = family_key if pooled else (family_key, name)
                opened.add(identity)
            cells.append(_Cell(row + 1, name, family_key, family_values, number, status))
    buckets = {}
    missing = {name: [] for name in names}
    for cell in cells:
        if cell.family_key is None:
            missing[cell.variable].append(cell)
        else:
            buckets.setdefault((cell.family_key, cell.variable), []).append(cell)
    ordered = []
    for key in groups:
        for name in names:
            ordered.extend(buckets.get((key, name), ()))
    for name in names:
        ordered.extend(missing[name])
    nonempty = len(opened)
    if nonempty > MAX_FAMILIES:
        raise FieldError(FAMILY_COLUMNS, ERR_FAMILIES)
    if request["plot"] and nonempty > MAX_PLOT_FAMILIES:
        raise FieldError(PLOT, ERR_PLOT_FAMILIES)
    request.update(cells=ordered, groups=groups, group_values=group_values, buckets=buckets,
                   nonempty=nonempty, used=used_count)
    return request


def validate_request(frame, options):
    """Field, domain and budget check safe to run on the dialog thread."""
    _prepare(frame, options)


def _apply(cells, outcome):
    count = len(cells)
    rank_of = [0] * count
    for position, index in enumerate(outcome["order"], start=1):
        rank_of[index] = position
    alpha = outcome["stage_alphas"][-1]
    for index, cell in enumerate(cells):
        rank = rank_of[index]
        cell.adjusted = outcome["adjusted"][index]
        cell.discovery = outcome["rejected"][index]
        cell.rank = rank
        cell.threshold = alpha * rank / count
    return alpha


def _members(request, key, variable):
    if request["scope"] == SCOPE_POOL:
        return [cell for name in request["p_columns"] for cell in request["buckets"].get((key, name), ())]
    return list(request["buckets"].get((key, variable), ()))


def _calculate(request):
    summaries = []
    panels = []
    variables = [None] if request["scope"] == SCOPE_POOL else request["p_columns"]
    for key in request["groups"]:
        label = _family_label(request["group_values"][key], request["family_columns"])
        for variable in variables:
            members = _members(request, key, variable)
            used = [cell for cell in members if cell.status == STATUS_USED]
            family = label if request["scope"] == SCOPE_POOL else f"{label} · {variable}"
            row = {
                "Family": family, "Variable": POOLED if variable is None else variable,
                "Method": request["method_name"], "q": request["q"], "m": len(used),
                "Discoveries": 0, "R1": pd.NA, "m0": pd.NA, "Stage 1": pd.NA, "Stage 2": pd.NA,
                "Reason": "",
            }
            if not used:
                row["Reason"] = EMPTY_REASON
                summaries.append(row)
                continue
            outcome = adjust_family([cell.p for cell in used], request["method"], request["q"])
            alpha = _apply(used, outcome)
            row["Discoveries"] = sum(cell.discovery for cell in used)
            if request["method"] == "bky":
                row["R1"] = outcome["r1"]
                row["m0"] = outcome["m0"]
            row["Stage 1"] = outcome["stage_alphas"][0]
            if len(outcome["stage_alphas"]) > 1:
                row["Stage 2"] = outcome["stage_alphas"][1]
            summaries.append(row)
            order = outcome["order"]
            panels.append({
                "label": family,
                "p": [used[index].p for index in order],
                "discovery": [used[index].discovery for index in order],
                "threshold": [alpha * rank / len(used) for rank in range(1, len(used) + 1)],
            })
    return summaries, panels


def _blank(value):
    return pd.NA if value is None else value


def _results_table(request):
    rows = request["cells"]
    data = {
        "Source row": [cell.source_row for cell in rows],
        "Variable": [cell.variable for cell in rows],
    }
    for position, name in enumerate(request["family_columns"]):
        data[name] = [cell.family_values[position] for cell in rows]
    data["p"] = [_blank(cell.p) for cell in rows]
    data["Adjusted p"] = [_blank(cell.adjusted) for cell in rows]
    data["Discovery"] = [_blank(cell.discovery) for cell in rows]
    data["Status"] = [cell.status for cell in rows]
    data["Rank"] = [_blank(cell.rank) for cell in rows]
    data["Threshold"] = [_blank(cell.threshold) for cell in rows]
    return pd.DataFrame(data)


def _settings(request, summaries):
    missing_p = sum(cell.status == STATUS_MISSING_P for cell in request["cells"])
    missing_family = sum(cell.status == STATUS_MISSING_FAMILY for cell in request["cells"])
    empty = sum(row["Reason"] == EMPTY_REASON for row in summaries)
    if request["used"] == 0:
        figure = "No used p values, so there is no diagnostic plot."
    elif request["plot"]:
        figure = "One panel per nonempty family. The Y scale is linear and p = 0 is kept."
    else:
        figure = "Diagnostic plot not requested."
    rows = [
        ("FDR method", request["method_name"]),
        ("Desired FDR (%)", request["level"]),
        ("q", request["q"]),
        ("Family scope", request["scope"]),
        ("p columns", ", ".join(request["p_columns"])),
        ("Family columns", ", ".join(request["family_columns"]) if request["family_columns"] else "(none)"),
        ("Show diagnostic plot", request["plot"]),
        ("Comparison", "inclusive (<=)"),
        ("Used p values", request["used"]),
        ("Ignored missing p", missing_p),
        ("Ignored missing family", missing_family),
        ("Nonempty families", request["nonempty"]),
        ("Empty families", empty),
        ("Cell limit", MAX_CELLS),
        ("Nonempty family limit", MAX_FAMILIES),
        ("Plotted family limit", MAX_PLOT_FAMILIES),
        ("Figure", figure),
        ("Dependence", DEPENDENCE_NOTE),
        ("Requested level", LEVEL_NOTE),
        ("Adjusted p depends on desired FDR", request["method"] == "bky"),
        ("Step-up", STEP_NOTE),
    ]
    if request["method"] == "bky":
        rows.append(("BKY m0", BKY_NOTE))
    return pd.DataFrame(rows, columns=["Setting", "Value"])


def _figure(request, panels):
    if not request["plot"] or not panels:
        return None
    from .i18n import tr, ui

    count = len(panels)
    columns = 1 if count == 1 else 2 if count <= 4 else 3
    rows = math.ceil(count / columns)
    figure = Figure(figsize=(6.2 * columns, 3.8 * rows), dpi=100, layout="constrained")
    axes = np.atleast_1d(figure.subplots(rows, columns, squeeze=False)).ravel()
    method = ui(request["method_name"])
    level = f"{request['level']:g}"
    threshold_label = tr("fdr.legend.threshold", method=method, level=level)
    discovery_label = tr("fdr.legend.discovery")
    other_label = tr("fdr.legend.not")
    for index, (axis, panel) in enumerate(zip(axes, panels, strict=False)):
        p = np.asarray(panel["p"], dtype=float)
        threshold = np.asarray(panel["threshold"], dtype=float)
        ranks = np.arange(1, len(p) + 1)
        discovered = np.asarray(panel["discovery"], dtype=bool)
        line, = axis.plot(ranks, threshold, linestyle="--", color="#0f6b4c",
                          marker="s" if len(p) == 1 else "none", label=threshold_label)
        line.set_gid(f"fdr-threshold-{index}")
        if discovered.any():
            found = axis.scatter(ranks[discovered], p[discovered], marker="o", s=36, c="#1f4e79",
                                 zorder=3, label=discovery_label)
            found.set_gid(f"fdr-discovery-{index}")
        if (~discovered).any():
            rest = axis.scatter(ranks[~discovered], p[~discovered], marker="x", s=36, c="#9a3412",
                                zorder=3, label=other_label)
            rest.set_gid(f"fdr-other-{index}")
        top = max(float(p.max()) if len(p) else 0.0, float(threshold.max()) if len(threshold) else 0.0, 0.0)
        pad = top * 0.08 if top else 0.05
        axis.set_xlim(0.5, len(p) + 0.5)
        axis.set_ylim(-pad * 0.2, top + pad)
        axis.set_yscale("linear")
        axis.set_title(panel["label"], fontsize=10)
        axis.set_xlabel(tr("fdr.axis.rank"))
        axis.set_ylabel(tr("fdr.axis.p"))
        axis.spines[["right", "top"]].set_visible(False)
    for axis in axes[count:]:
        axis.set_visible(False)
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], linestyle="--", color="#0f6b4c")]
    labels = [threshold_label]
    decisions = [np.asarray(panel["discovery"], dtype=bool) for panel in panels]
    if any(choice.any() for choice in decisions):
        handles.append(Line2D([], [], linestyle="none", marker="o", color="#1f4e79", markersize=6))
        labels.append(discovery_label)
    if any((~choice).any() for choice in decisions):
        handles.append(Line2D([], [], linestyle="none", marker="x", color="#9a3412", markersize=6))
        labels.append(other_label)
    figure.legend(handles, labels, loc="outside lower center", ncol=len(labels), fontsize=8)
    figure.suptitle(tr("fdr.figure.title", method=method, level=level))
    return figure


def analysis(frame, options):
    """Build the FDR sheets and, when requested, the diagnostic figure."""
    request = _prepare(frame, options)
    summaries, panels = _calculate(request)
    tables = {
        RESULTS: _results_table(request),
        FAMILIES: pd.DataFrame(summaries, columns=[
            "Family", "Variable", "Method", "q", "m", "Discoveries",
            "R1", "m0", "Stage 1", "Stage 2", "Reason"]),
        SETTINGS: _settings(request, summaries),
    }
    return Result(tables, _figure(request, panels))


def format_fdr_error(error):
    """Prefix a catalogued field error with the translated caption. None for other errors."""
    field = getattr(error, "field", None)
    if field not in _FIELDS:
        return None
    from .i18n import translate_message, ui

    text = translate_message(str(error), "fdr.error.")
    label = ui(field)
    if label and label not in text:
        return f"{label}: {text}"
    return text
