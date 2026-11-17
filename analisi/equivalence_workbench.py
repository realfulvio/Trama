"""Equivalence test (TOST): data extraction, the four designs, result sheets and the figure.

Designs and the difference tested (always the first quantity minus the second):

* One-sample: mean(Response) − Reference, df = n − 1.
* Paired: mean(First − Second) over the rows where both cells are present, df = n_pairs − 1.
* Student: mean(First) − mean(Second) with the pooled variance, df = n1 + n2 − 2.
* Welch: the same difference with separate variances and Welch–Satterthwaite df.

The statistics themselves (two one-sided tests, interval, decision) are in ``equivalence``. This module
removes missing cells (each column on its own for the independent designs, a row with a missing member for
Paired), never mutates the worksheet, and keeps the original row label of every observation. Values are
scaled and centered before the moments are taken, so very large or very small units neither overflow
nor lose representable variability. Whatever
cannot be inferred is reported as "Inference unavailable" with its reason; no p value is invented.
"""
from numbers import Real

import numpy as np
import pandas as pd

from .category_graphs import COLORS
from .equivalence import UNAVAILABLE, check_zone, tost_from_summary
from .field_error import FieldError
from .reporting import Result, _plot, _report

EQUIVALENCE = "Equivalence test (TOST)"
DESIGN, RESPONSE, REFERENCE, FIRST, SECOND = "Design", "Response", "Reference", "First", "Second"
LOWER, UPPER, ALPHA = "Lower margin", "Upper margin", "Alpha"
ONE_SAMPLE, PAIRED, STUDENT, WELCH = DESIGNS = ("One-sample", "Paired", "Student", "Welch")

# The first entry of a choice is its default. The zone starts invalid (0, 0) on purpose: the margins depend
# on the scientific question, so Trama never proposes them and the analysis refuses to run until they are declared.
OPTIONS = {DESIGN: DESIGNS, RESPONSE: None, REFERENCE: 0.0, FIRST: None, SECOND: None, LOWER: 0.0, UPPER: 0.0,
           ALPHA: 0.05}
DATA_FIELDS = (DESIGN, RESPONSE, REFERENCE, FIRST, SECOND)

SUMMARY_SHEET, TESTS_SHEET, DATA_SHEET, SETTINGS_SHEET = (
    "Equivalence summary", "Equivalence tests", "Data used", "Settings")
SUMMARY_COLUMNS = ["Design", "First label", "Second label", "N first", "N second", "Difference", "SE", "df",
                   "Lower margin", "Upper margin", "Alpha", "CI level (%)", "CI lower", "CI upper", "t lower",
                   "p lower", "t upper", "p upper", "p TOST", "Conclusion", "Status / Reason"]
GID = "tost:"

# Interface captions and choices; recipes keep the English field names and values.
TAB_KEYS = {"Data": "tost.tab.data", "Equivalence zone": "tost.tab.zone"}
LABEL_KEYS = {DESIGN: "tost.field.design", RESPONSE: "tost.field.response", REFERENCE: "tost.field.reference",
              FIRST: "tost.field.first", SECOND: "tost.field.second", LOWER: "tost.field.lower",
              UPPER: "tost.field.upper", ALPHA: "tost.field.alpha"}
CHOICE_KEYS = {ONE_SAMPLE: "tost.choice.one_sample", PAIRED: "tost.choice.paired", STUDENT: "tost.choice.student",
               WELCH: "tost.choice.welch"}
ERROR_PREFIX = "tost.error."


def visibility(design):
    """Fields that apply to the design; the others are inactive, never validated and never saved."""
    one = design == ONE_SAMPLE
    return {RESPONSE: one, REFERENCE: one, FIRST: not one, SECOND: not one}


# ----- options -------------------------------------------------------------------------------------------------------

def _real(options, name, what="a finite number"):
    value = options.get(name)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(float(value)):
        raise FieldError(name, f"{name} must be {what}.")
    return float(value)


def _settings(options):
    design = options.get(DESIGN)
    if not isinstance(design, str) or design not in DESIGNS:
        raise FieldError(DESIGN, "Design: choose One-sample, Paired, Student or Welch.")
    reference = _real(options, REFERENCE) if design == ONE_SAMPLE else None
    lower, upper = _real(options, LOWER), _real(options, UPPER)
    alpha = _real(options, ALPHA)
    try:
        check_zone(lower, upper, alpha)
    except ValueError as error:
        field = LOWER if "Lower" in str(error) else UPPER if "Upper" in str(error) else ALPHA
        raise FieldError(field, str(error)) from None
    return design, reference, lower, upper, alpha


# ----- data ----------------------------------------------------------------------------------------------------------

def _column(frame, name, role):
    """Return (present, values): which cells hold something, and their float values (nan when unusable)."""
    if not isinstance(name, str) or not name:
        raise FieldError(role, f"Choose a column for {role}.")
    if name not in frame:
        raise FieldError(role, f'Choose an existing column for {role}: "{name}" is not in the worksheet.')
    raw = frame[name]
    if isinstance(raw, pd.DataFrame):
        raise FieldError(role, "Worksheet column names must be unique.")
    cells = raw.to_numpy(dtype=object)
    present = np.array([not (value is None or value is pd.NA or value is pd.NaT
                             or (isinstance(value, float) and np.isnan(value))
                             or (isinstance(value, str) and not value.strip())) for value in cells], dtype=bool)
    values = np.full(len(cells), np.nan)
    for i in np.flatnonzero(present):
        value = cells[i]
        if isinstance(value, (bool, np.bool_)):
            continue
        try:
            values[i] = float(value.replace(",", ".")) if isinstance(value, str) else float(value)
        except (TypeError, ValueError, OverflowError):
            pass
    return present, values


def _used(frame, role, name, values, rows):
    """Float values of the used rows; the first unusable cell names its column and source row."""
    chosen = values[rows]
    bad = ~np.isfinite(chosen)
    if bad.any():
        label = frame.index[rows[int(np.flatnonzero(bad)[0])]]
        count = int(bad.sum())
        if count > 1:
            raise FieldError(role, f'Column "{name}" must hold finite numbers in the rows used. '
                                   f"Source row {label} is not a finite number ({count} cells are unusable).")
        raise FieldError(role, f'Column "{name}" must hold finite numbers in the rows used. '
                               f"Source row {label} is not a finite number.")
    return chosen


def _prepare(frame, design, options):
    """Source rows and values of the observations used, with the labels the tables show."""
    if design == ONE_SAMPLE:
        name = options.get(RESPONSE)
        present, values = _column(frame, name, RESPONSE)
        rows = np.flatnonzero(present)
        a = _used(frame, RESPONSE, name, values, rows)
        if len(a) < 2:
            raise FieldError(RESPONSE, f'Column "{name}" needs at least two finite values; {len(a)} found.')
        return {"first": name, "second": None, "rows_a": rows, "a": a, "rows_b": rows[:0], "b": a[:0]}
    first, second = options.get(FIRST), options.get(SECOND)
    present_a, values_a = _column(frame, first, FIRST)
    if isinstance(second, str) and second and second == first:
        raise FieldError(SECOND, "Choose different columns for First and Second.")
    present_b, values_b = _column(frame, second, SECOND)
    if design == PAIRED:
        rows = np.flatnonzero(present_a & present_b)
        a = _used(frame, FIRST, first, values_a, rows)
        b = _used(frame, SECOND, second, values_b, rows)
        if len(rows) < 2:
            raise FieldError(FIRST, f"A paired test needs at least two complete pairs; {len(rows)} found.")
        return {"first": first, "second": second, "rows_a": rows, "a": a, "rows_b": rows, "b": b}
    rows_a, rows_b = np.flatnonzero(present_a), np.flatnonzero(present_b)
    a = _used(frame, FIRST, first, values_a, rows_a)
    b = _used(frame, SECOND, second, values_b, rows_b)
    for role, name, values in ((FIRST, first, a), (SECOND, second, b)):
        if len(values) < 2:
            raise FieldError(role, f'Column "{name}" needs at least two finite values; {len(values)} found.')
    return {"first": first, "second": second, "rows_a": rows_a, "a": a, "rows_b": rows_b, "b": b}


# ----- estimates -----------------------------------------------------------------------------------------------------

def _exponent(*arrays):
    """Binary exponent that brings the largest magnitude into [0.5, 1)."""
    top = max((float(np.max(np.abs(a))) for a in arrays if len(a)), default=0.0)
    return int(np.frexp(top)[1]) if top > 0 else 0


def _unscale(value, exponent):
    with np.errstate(over="ignore"):
        return float(np.ldexp(value, exponent))


def _spread(scaled):
    """Sample SD after centering; an arbitrary offset must not erase variation."""
    return float(np.std(scaled - scaled[0], ddof=1))


def _sample_se(values):
    exponent = _exponent(values)
    return _unscale(_spread(np.ldexp(values, -exponent)) / np.sqrt(len(values)), exponent)


def _estimate(design, data, reference):
    """Return (difference, se, df, reason); nan for the parts that cannot be computed."""
    a, b = data["a"], data["b"]
    n, m = len(a), len(b)
    exponent = _exponent(a, b)
    a_s, b_s = np.ldexp(a, -exponent), np.ldexp(b, -exponent)
    if design == ONE_SAMPLE:
        diff_exponent = _exponent(a, np.array([reference]))
        scaled = np.ldexp(a, -diff_exponent)
        offset = scaled[0] - float(np.ldexp(reference, -diff_exponent))
        diff = _unscale(offset + float(np.mean(scaled - scaled[0])), diff_exponent)
        se, df = _sample_se(a), n - 1.0
    elif design == PAIRED:
        with np.errstate(over="ignore"):
            differences = a - b
        if np.isfinite(differences).all():
            difference_exponent = _exponent(differences)
            scaled = np.ldexp(differences, -difference_exponent)
            diff = _unscale(scaled[0] + float(np.mean(scaled - scaled[0])), difference_exponent)
            se = _sample_se(differences)
        else:
            scaled = a_s - b_s
            diff = _unscale(float(np.mean(scaled)), exponent)
            se = _unscale(_spread(scaled) / np.sqrt(n), exponent)
        df = n - 1.0
    else:
        center = a_s[0]
        diff = _unscale(float(np.mean(a_s - center)) - float(np.mean(b_s - center)), exponent)
        sa, sb = _sample_se(a), _sample_se(b)
        if design == STUDENT:
            df = n + m - 2.0
            with np.errstate(over="ignore"):
                se = float(np.hypot(sa * np.sqrt(n * (n - 1) / df * (1 / n + 1 / m)),
                                    sb * np.sqrt(m * (m - 1) / df * (1 / n + 1 / m))))
        else:
            se = float(np.hypot(sa, sb))
            scale = max(sa, sb)
            if np.isfinite(scale) and scale > 0:
                va, vb = (sa / scale) ** 2, (sb / scale) ** 2
                df = (va + vb) ** 2 / (va ** 2 / (n - 1) + vb ** 2 / (m - 1))
            else:
                df = np.nan
    reasons = []
    if not np.isfinite(diff):
        reasons.append("The difference is outside the floating-point range.")
        diff = np.nan
    if not np.isfinite(se):
        reasons.append("The standard error is outside the floating-point range.")
        se = np.nan
    elif se == 0:
        reasons.append("The standard error is zero, so t, p and the interval "
                       "are undefined.")
    elif not np.isfinite(df) or df <= 0:
        reasons.append("The degrees of freedom are not valid.")
        df = np.nan
    return diff, se, float(df), " ".join(reasons)


# ----- analysis ------------------------------------------------------------------------------------------------------

def equivalence_test(frame, options):
    design, reference, lower, upper, alpha = _settings(options)
    data = _prepare(frame, design, options)
    difference, se, df, reason = _estimate(design, data, reference)
    n, m = len(data["a"]), (None if design == ONE_SAMPLE else len(data["b"]))
    second_label = f"Reference ({reference:g})" if design == ONE_SAMPLE else data["second"]
    row = {"Design": design, "First label": data["first"], "Second label": second_label, "N first": n, "N second": m,
           "Difference": difference, "SE": se, "df": df, "Lower margin": lower, "Upper margin": upper, "Alpha": alpha,
           "CI level (%)": 100.0 * (1.0 - 2.0 * alpha)}
    result = dict.fromkeys(("CI lower", "CI upper", "t lower", "p lower", "t upper", "p upper", "p TOST"), np.nan)
    if not reason:
        try:
            tost = tost_from_summary(difference, se, df, lower, upper, alpha)
        except ValueError as error:
            reason = str(error)
        else:
            result = {"CI lower": tost["ci_lower"], "CI upper": tost["ci_upper"], "t lower": tost["t_lower"],
                      "p lower": tost["p_lower"], "t upper": tost["t_upper"], "p upper": tost["p_upper"],
                      "p TOST": tost["p_tost"]}
            row["Conclusion"] = tost["conclusion"]
    row.update(result)
    if reason:
        row["Conclusion"] = UNAVAILABLE
    row["Status / Reason"] = reason or "OK"
    summary = pd.DataFrame([row], columns=SUMMARY_COLUMNS)
    for name in ("N first", "N second"):
        # Counts stay integers; a missing second sample is a blank cell, never an invented zero.
        summary[name] = pd.Series([row[name]], dtype=object)
    orientation = "Sample − Reference" if design == ONE_SAMPLE else "First − Second"
    tables = {SUMMARY_SHEET: summary, TESTS_SHEET: _tests_table(row, orientation),
              DATA_SHEET: _data_table(frame, design, data)}
    settings = {"Design": design, "Difference": orientation,
                "First": data["first"] if design != ONE_SAMPLE else "Not used",
                "Second": data["second"] if design != ONE_SAMPLE else "Not used",
                "Response": data["first"] if design == ONE_SAMPLE else "Not used",
                "Reference": reference if design == ONE_SAMPLE else "Not used",
                "Lower margin": lower, "Upper margin": upper, "Alpha": alpha,
                "CI level (%)": row["CI level (%)"],
                "Decision": "Equivalent only if both one-sided p values are below Alpha and the "
                            f"{row['CI level (%)']:g}% interval lies strictly inside the zone.",
                "Margins": "Declared by the researcher before the data; Trama does not choose or validate them.",
                "Not included": "Non-inferiority, ratio of lognormal means, summary mean/SD/N, pairing by Subject, "
                                "repeated measures, bootstrap, Bayesian methods and multiple-comparison corrections."}
    tables[SETTINGS_SHEET] = _report(settings)
    return Result(tables, _figure(design, orientation, data, row))


def _tests_table(row, orientation):
    available = row["Conclusion"] != UNAVAILABLE
    lower, upper, alpha = row["Lower margin"], row["Upper margin"], row["Alpha"]

    def rejected(p):
        return ("Yes" if p < alpha else "No") if available else "Not available"
    return pd.DataFrame([
        {"Test": "Lower", "Null hypothesis": f"{orientation} ≤ {lower:g}", "Alternative": f"{orientation} > {lower:g}",
         "Margin": lower, "t": row["t lower"], "df": row["df"], "p": row["p lower"], "Alpha": alpha,
         "Null rejected": rejected(row["p lower"])},
        {"Test": "Upper", "Null hypothesis": f"{orientation} ≥ {upper:g}", "Alternative": f"{orientation} < {upper:g}",
         "Margin": upper, "t": row["t upper"], "df": row["df"], "p": row["p upper"], "Alpha": alpha,
         "Null rejected": rejected(row["p upper"])}])


def _data_table(frame, design, data):
    if design == PAIRED:
        return pd.DataFrame({"Source row": frame.index[data["rows_a"]], "First": data["a"], "Second": data["b"],
                             "Difference": _unscaled_difference(data)})
    records = [{"Source row": source, "Sample": name, "Value": value}
               for name, rows, values in ((data["first"], data["rows_a"], data["a"]),
                                          (data["second"], data["rows_b"], data["b"]))
               for source, value in zip(frame.index[rows], values, strict=True)]
    return pd.DataFrame(records, columns=["Source row", "Sample", "Value"])


def _unscaled_difference(data):
    with np.errstate(over="ignore"):
        return data["a"] - data["b"]


# ----- figure --------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _figure(design, orientation, data, row):
    lower, upper = row["Lower margin"], row["Upper margin"]
    estimate, low, high = row["Difference"], row["CI lower"], row["CI upper"]
    raw_lower, raw_upper, raw_estimate, raw_low, raw_high = lower, upper, estimate, low, high
    finite = [x for x in (lower, upper, estimate, low, high) if np.isfinite(x)]
    largest = max(abs(x) for x in finite)
    exponent = _exponent(np.array(finite)) if largest > 1e100 or largest < 1e-100 else 0
    if exponent:
        lower, upper, estimate, low, high = (float(np.ldexp(x, -exponent)) for x in (lower, upper, estimate, low, high))
    # The title repeats the table's conclusion; the figure never decides anything itself.
    first, second = row["First label"], row["Second label"]
    names = f"{first} − {second}"
    figure, axes = _plot(f"{EQUIVALENCE} · {design} · {row['Conclusion']}",
                         f"Difference, {orientation}" + ("" if names == orientation else f" ({names})"))
    if exponent:
        axes.set_xlabel(axes.get_xlabel() + f" · displayed values × 2^{exponent}")
    _plain(axes.title, axes.xaxis.label)
    axes.set_yticks([])
    axes.spines["left"].set_visible(False)
    axes.set_ylim(-1, 1)
    zone = axes.axvspan(lower, upper, color="#2f7d6b", alpha=.12, zorder=0, linewidth=0,
                        label=f"Equivalence zone ({raw_lower:g} to {raw_upper:g})")
    zone.set_gid(f"{GID}zone")
    for value, raw_value, name in ((lower, raw_lower, "Lower margin"), (upper, raw_upper, "Upper margin")):
        line = axes.axvline(value, color="#1f2933", linestyle="--", linewidth=1.8, zorder=2,
                            label=f"{name} = {raw_value:g}")
        line.set_gid(f"{GID}{name.split()[0].lower()}")
        _plain(axes.text(value, .97, f"{name}\n{raw_value:g}", transform=axes.get_xaxis_transform(), ha="center",
                         va="top", fontsize=8.5, color="#1f2933", bbox={"facecolor": "white", "edgecolor": "none",
                                                                       "alpha": .85}))
    zero = axes.axvline(0, color="#6b7785", linestyle=":", linewidth=1.5, zorder=1, label="No difference (0)")
    zero.set_gid(f"{GID}zero")
    points = [lower, upper, 0.0]
    if np.isfinite(estimate) and np.isfinite(low) and np.isfinite(high):
        container = axes.errorbar([estimate], [0], xerr=[[estimate - low], [high - estimate]], fmt="D",
                                  color=COLORS[0], capsize=8, markersize=8, linewidth=2.6, zorder=4,
                                  label=f"{raw_estimate:.4g} ({row['CI level (%)']:g}% CI {raw_low:.4g} to {raw_high:.4g})")
        container.lines[0].set_gid(f"{GID}estimate")
        points += [estimate, low, high]
    else:
        notes = row["Status / Reason"]
        if np.isfinite(estimate):
            axes.scatter([estimate], [0], marker="D", s=70, color=COLORS[0], zorder=4,
                         label=f"{raw_estimate:.4g}").set_gid(f"{GID}estimate")
            points.append(estimate)
        _plain(axes.text(.5, .5, f"{UNAVAILABLE}: {notes}", transform=axes.transAxes, ha="center", va="center",
                         fontsize=9, color="#8a3b12", wrap=True, zorder=5,
                         bbox={"facecolor": "white", "edgecolor": "none", "alpha": .92}))
    span = max(points) - min(points)
    pad = .12 * span
    axes.set_xlim(min(points) - pad, max(points) + pad)
    legend = axes.legend(frameon=True, facecolor="white", edgecolor="none", framealpha=.92, loc="lower center",
                         fontsize=8.5, ncol=2)
    _plain(legend.get_title(), *legend.get_texts())
    return figure
