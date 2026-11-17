"""One-way ANOVA from sufficient statistics, never synthetic observations.

Ordinary ANOVA is unchanged. Welch and the original Brown–Forsythe F* use the
same summaries, scaled before any square or weight so extreme units stay finite.
"""
import re
from decimal import Decimal, InvalidOperation
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .processing import FieldError
from .reporting import Result, _plot
from .unequal_anova import JOINT, brown_forsythe

METHOD = "One-way ANOVA from summaries"
ROWS, SUBCOLUMNS = "Groups in rows", "Summary subcolumns"
ORDINARY, WELCH = "Ordinary", "Welch"
BROWN = "Brown\u2013Forsythe"
GAMES, TAMHANE = "Games\u2013Howell", "Tamhane T2"
ORDINARY_POSTHOC = ("None", "Tukey", "Holm", "Bonferroni")
UNEQUAL_POSTHOC = ("None", GAMES, TAMHANE, "Holm", "Bonferroni")
NOTE = ("These summaries are treated as independent groups. They cannot reconstruct "
        "paired dependence, normality, residuals or the data distribution.")
OPTIONS = {"Input": (ROWS, SUBCOLUMNS), "Group": "Optional", "Mean": None,
           "Dispersion": None, "Sample size": None, "Variables": "Multiple",
           "Summary row": 1, "Dispersion type": ("SD", "SEM", "CV (%)"),
           "Method": (ORDINARY, WELCH, JOINT),
           "Post-hoc": ORDINARY_POSTHOC, "Confidence level (%)": 95.}
_SUBCOLUMN = re.compile(r"(.+) \[(Mean|SD|SEM|N|CV|CV%)\]( \(\d+\))?")
_RANGE = "The ANOVA statistic is outside the supported numeric range."
_SCALE = "The group means and SDs cannot be scaled into the range Welch ANOVA can represent."


def visibility(mode):
    return {**dict.fromkeys(("Group", "Mean", "Dispersion", "Sample size"), mode == ROWS),
            **dict.fromkeys(("Variables", "Summary row"), mode == SUBCOLUMNS)}


def _missing(value):
    return value is None or value is pd.NA or value is pd.NaT or (isinstance(value, str) and not value.strip()) or (
        isinstance(value, (float, np.floating)) and np.isnan(value))


def _number(value, field):
    try:
        if isinstance(value, (bool, np.bool_)): raise ValueError()
        number = float(value)
        if not np.isfinite(number): raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, "Summary values must be finite numbers.") from None


def _size(value, field):
    try:
        if isinstance(value, (bool, np.bool_)): raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or not 2 <= number <= 2**53 or number != number.to_integral_value():
            raise ValueError()
        return int(number)
    except (ValueError, InvalidOperation):
        raise FieldError(field, "Each sample size must be an integer from 2 to 2^53.") from None


def check_options(frame, options):
    """Validate columns and sufficient statistics without expensive distribution calculations."""
    mode = options.get("Input", ROWS)
    if mode not in (ROWS, SUBCOLUMNS):
        raise FieldError("Input", "Choose groups in rows or summary subcolumns.")
    dispersion = options.get("Dispersion type", "SD")
    if dispersion not in OPTIONS["Dispersion type"]:
        raise FieldError("Dispersion type", "Choose SD, SEM or CV (%).")
    method = options.get("Method", ORDINARY)
    if method not in OPTIONS["Method"]:
        raise FieldError("Method", "Choose Ordinary, Welch, or Welch and Brown–Forsythe.")
    posthoc = options.get("Post-hoc", "None")
    allowed = ORDINARY_POSTHOC if method == ORDINARY else UNEQUAL_POSTHOC
    if posthoc not in allowed:
        if method == ORDINARY and posthoc in (GAMES, TAMHANE):
            raise FieldError("Post-hoc", "Games–Howell or Tamhane T2 requires the Welch or Welch and Brown–Forsythe method.")
        if method != ORDINARY and posthoc == "Tukey":
            raise FieldError("Post-hoc", "Tukey assumes equal variances. Choose None, Games–Howell, Tamhane T2, Holm or Bonferroni.")
        if method == ORDINARY:
            raise FieldError("Post-hoc", "Choose None, Tukey, Holm or Bonferroni.")
        raise FieldError("Post-hoc", "Choose None, Games–Howell, Tamhane T2, Holm or Bonferroni.")
    level = _number(options.get("Confidence level (%)", 95.), "Confidence level (%)")
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)", "Confidence level (%) must be between 0 and 100.")
    if not 0 < level/100 < 1 or .5+level/200 == .5:
        raise FieldError("Confidence level (%)", "The confidence level is too close to a numerical boundary.")
    if not frame.columns.is_unique:
        raise FieldError("Mean" if mode == ROWS else "Variables", "Worksheet column names must be unique.")
    records = []
    if mode == ROWS:
        roles = ("Mean", "Dispersion", "Sample size")
        columns = [options.get(role) for role in roles]
        for role, column in zip(roles, columns):
            if not isinstance(column, str) or column not in frame:
                raise FieldError(role, "Choose an existing summary column.")
        label_column = options.get("Group")
        if label_column and (not isinstance(label_column,str) or label_column not in frame):
            raise FieldError("Group", "Choose an existing summary column.")
        if len(set(columns)) != 3 or label_column in columns:
            raise FieldError("Mean", "Summary roles must use distinct columns.")
        for row in range(len(frame)):
            cells = [frame.iloc[row][column] for column in columns]
            if all(_missing(value) for value in cells): continue
            label = frame.iloc[row][label_column] if label_column else f"Group {row+1}"
            if _missing(label): label = f"Group {row+1}"
            records.append((row+1, str(label), *cells))
    else:
        selected = options.get("Variables")
        if (not isinstance(selected, (list, tuple)) or not selected
                or any(not isinstance(column, str) or column not in frame for column in selected)
                or len(set(selected)) != len(selected)):
            raise FieldError("Variables", "Select the Mean, dispersion and N subcolumns for each group.")
        row = _number(options.get("Summary row", 1), "Summary row")
        if row != int(row) or not 1 <= row <= len(frame):
            raise FieldError("Summary row", "Choose an existing worksheet row (starting at 1).")
        groups = {}
        for column in selected:
            match = _SUBCOLUMN.fullmatch(column)
            if not match:
                raise FieldError("Variables", "Select only named Mean, SD, SEM, CV or N subcolumns.")
            name, role, suffix = match.groups()
            name += suffix or ""
            role = "CV" if role == "CV%" else role
            group = groups.setdefault(name, {})
            if role in group: raise FieldError("Variables", "Each group must have unique summary roles.")
            group[role] = column
        error_role = "CV" if dispersion == "CV (%)" else dispersion
        for name, columns in groups.items():
            if not {"Mean", error_role, "N"} <= columns.keys():
                raise FieldError("Variables", "Each selected group needs Mean, the chosen dispersion and N.")
            cells = [frame.iloc[int(row)-1][columns[role]] for role in ("Mean", error_role, "N")]
            records.append((int(row), name, *cells))
    used, omitted = [], []
    for row, label, mean, error, size in records:
        if any(_missing(value) for value in (mean, error, size)):
            omitted.append({"Source row": row, "Group": label, "Reason": "Incomplete mean, dispersion or N."})
            continue
        mean_field, error_field, size_field = ("Mean", "Dispersion", "Sample size") if mode == ROWS else ("Variables",)*3
        mean, error, size = _number(mean,mean_field), _number(error,error_field), _size(size,size_field)
        if error < 0: raise FieldError(error_field, "Dispersion must be nonnegative.")
        if dispersion == "CV (%)" and mean == 0:
            raise FieldError(error_field, "CV (%) cannot define dispersion for a zero mean.")
        with np.errstate(over="ignore", under="ignore"):
            sd = (error * np.sqrt(size) if dispersion == "SEM" else
                  (abs(mean) * (error/100) if dispersion == "CV (%)" else error))
        if not np.isfinite(sd) or (error > 0 and sd == 0):
            raise FieldError(error_field, "The SD conversion is outside the supported numeric range.")
        used.append({"Source row": row, "Group": label, "Mean": mean, "SD": sd, "N": int(size)})
    if not 2 <= len(used) <= 30:
        raise FieldError("Variables" if mode == SUBCOLUMNS else "Mean", "Provide between 2 and 30 complete groups.")
    if sum(row["N"] for row in used) > 2**53:
        raise FieldError("Sample size" if mode == ROWS else "Variables", "The total sample size must not exceed 2^53.")
    error_field = "Dispersion" if mode == ROWS else "Variables"
    if method != ORDINARY:
        if any(not row["SD"] > 0 for row in used):
            raise FieldError(error_field, "Every group used by Welch ANOVA needs a positive SD.")
    elif not any(row["SD"] > 0 for row in used):
        raise FieldError(error_field, "ANOVA requires positive pooled residual variance.")
    return pd.DataFrame(used), pd.DataFrame(omitted, columns=("Source row", "Group", "Reason")), level, posthoc


def _restore(value, scale, power=1):
    """Unavailable is distinct from zero when display units exceed floating-point range."""
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        result = np.float64(value)
        for _ in range(power): result *= scale
    return float(result) if np.isfinite(result) and (value == 0 or result != 0) else np.nan


def _field(options):
    return "Dispersion" if options.get("Input", ROWS) == ROWS else "Variables"


def _require(values, field, message=_RANGE):
    array = np.asarray(values, dtype=float)
    if array.shape and not np.isfinite(array).all():
        raise FieldError(field, message)
    if not array.shape and not np.isfinite(array):
        raise FieldError(field, message)
    return array


def _scaled(means, sds, field):
    """Center, then scale by the larger of the centered means and the SDs."""
    origin = .5 * means.min() + .5 * means.max()
    shifted = means - origin
    scale = max(float(np.max(np.abs(shifted))), float(np.max(sds)))
    if not scale > 0 or not np.isfinite(scale):
        raise FieldError(field, _SCALE)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        normalized, errors = shifted / scale, sds / scale
    if not np.isfinite(normalized).all() or not np.isfinite(errors).all() or not (errors > 0).all():
        raise FieldError(field, _SCALE)
    return normalized, np.square(errors), float(scale)


def _welch(means, variances, sizes, field):
    """Welch F with the correction term retained even when the sample sizes match."""
    count = len(sizes)
    weights = _require(sizes / variances, field, _SCALE)
    if not (weights > 0).all():
        raise FieldError(field, _SCALE)
    # Individual precisions can be finite while their sum overflows. Normalize
    # before summing so the weighted mean and Welch correction stay meaningful.
    relative = weights / weights.max()
    ratios = relative / relative.sum()
    center = np.sum(ratios * means)
    correction = np.sum(np.square(1 - ratios) / (sizes - 1))
    _require(correction, field, _SCALE)
    if not correction > 0:
        raise FieldError(field, _SCALE)
    numerator = np.sum(weights * np.square(means - center)) / (count - 1)
    denominator = 1 + 2 * (count - 2) * correction / (count * count - 1)
    statistic = _require(numerator / denominator, field).item()
    df2 = _require((count * count - 1) / (3 * correction), field).item()
    if not df2 > 0:
        raise FieldError(field, _RANGE)
    probability = _require(stats.f.sf(statistic, count - 1, df2), field).item()
    return statistic, count - 1, df2, probability


def _brown(means, variances, sizes, field):
    statistic, df1, df2, probability = brown_forsythe(sizes, means, variances)
    _require([statistic, df2, probability], field)
    if not df2 > 0:
        raise FieldError(field, _RANGE)
    return float(statistic), int(df1), float(df2), float(probability)


def _pair_statistics(means, variances, sizes, field):
    count = len(sizes)
    first, second = np.array(list(combinations(range(count), 2))).T
    variance = variances / sizes
    left, right = variance[first], variance[second]
    pooled = left + right
    se = _require(np.sqrt(pooled), field, _SCALE)
    if not (se > 0).all():
        raise FieldError(field, _SCALE)
    # Welch-Satterthwaite is homogeneous: avoid squaring tiny variances into zero.
    pair_scale = np.maximum(left, right)
    left_relative, right_relative = left / pair_scale, right / pair_scale
    df = _require(np.square(left_relative + right_relative) /
                  (np.square(left_relative) / (sizes[first] - 1) +
                   np.square(right_relative) / (sizes[second] - 1)), field)
    if not (df > 0).all():
        raise FieldError(field, _RANGE)
    differences = means[first] - means[second]
    raw = _require(2 * stats.t.sf(np.abs(differences / se), df), field)
    return first, second, differences, se, df, raw


def _games_howell(differences, se, df, count, level, field):
    statistic = np.sqrt(2) * np.abs(differences) / se
    try:
        with np.errstate(all="ignore"):
            adjusted = stats.studentized_range.sf(statistic, count, df)
            half = stats.studentized_range.ppf(level / 100, count, df) * se / np.sqrt(2)
    except (ValueError, FloatingPointError) as error:
        raise FieldError(field, _RANGE) from error
    return _require(adjusted, field), _require(half, field)


def _tamhane(raw, se, df, count, level, field):
    family = count * (count - 1) / 2
    adjusted = np.ones_like(raw, dtype=float)
    safe = raw < 1
    if safe.any():
        adjusted[safe] = -np.expm1(family * np.log1p(-raw[safe]))
    alpha = -np.expm1(np.log(level / 100) / family)
    try:
        with np.errstate(all="ignore"):
            half = stats.t.isf(alpha / 2, df) * se
    except (ValueError, FloatingPointError) as error:
        raise FieldError(field, _RANGE) from error
    return _require(adjusted, field), _require(half, field)


def _intervals(differences, half, scale):
    restored = [_restore(value, scale) for value in differences]
    width = [_restore(value, scale) for value in half]
    lower, upper = [], []
    for center, side in zip(restored, width):
        if not np.isfinite(center) or not np.isfinite(side):
            lower.append(np.nan)
            upper.append(np.nan)
            continue
        with np.errstate(over="ignore", invalid="ignore"):
            low, high = center - side, center + side
        lower.append(float(low) if np.isfinite(low) else np.nan)
        upper.append(float(high) if np.isfinite(high) else np.nan)
    return restored, lower, upper


def _unequal(used, omitted, level, posthoc, options):
    field = _field(options)
    means, sds, sizes = (used[name].to_numpy(dtype=float) for name in ("Mean", "SD", "N"))
    count, total = len(used), int(sum(map(int, used.N)))
    normalized, variances, scale = _scaled(means, sds, field)
    welch = _welch(normalized, variances, sizes, field)
    rows = [{"Term": WELCH, "F": welch[0], "F df1": welch[1], "F df2": welch[2], "p": welch[3]}]
    if options.get("Method", ORDINARY) == JOINT:
        brown = _brown(normalized, variances, sizes, field)
        rows.append({"Term": BROWN, "F": brown[0], "F df1": brown[1], "F df2": brown[2], "p": brown[3]})
    anova = pd.DataFrame(rows, columns=("Term", "F", "F df1", "F df2", "p"))
    used = used.copy()
    # SE and the pointwise half-width are scaled, then restored. A positive width that
    # cannot be shown in the original units stays blank instead of becoming zero.
    standard_error = np.sqrt(variances / sizes)
    critical = stats.t.ppf(.5 + level / 200, sizes - 1)
    half_widths = np.array([_restore(value, scale) for value in critical * standard_error], dtype=float)
    displayed_se = np.array([_restore(value, scale) for value in standard_error], dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        used["Mean SE"] = displayed_se
        used["Mean CI lower"] = means - half_widths
        used["Mean CI upper"] = means + half_widths
    used.replace([np.inf, -np.inf], np.nan, inplace=True)
    tables = {"ANOVA": anova, "Summaries used": used, "Omitted groups": omitted}
    if posthoc != "None":
        first, second, differences, se, df, raw = _pair_statistics(normalized, variances, sizes, field)
        if posthoc == GAMES:
            adjusted, half = _games_howell(differences, se, df, count, level, field)
        elif posthoc == TAMHANE:
            adjusted, half = _tamhane(raw, se, df, count, level, field)
        else:
            adjusted = multipletests(raw, method="holm" if posthoc == "Holm" else "bonferroni")[1]
            half = None
        _require(adjusted, field)
        pairs = pd.DataFrame({
            "First": used.Group.iloc[first].to_numpy(), "Second": used.Group.iloc[second].to_numpy(),
            "First source row": used["Source row"].iloc[first].to_numpy(),
            "Second source row": used["Source row"].iloc[second].to_numpy(),
            "Difference": [_restore(value, scale) for value in differences],
            "SE": [_restore(value, scale) for value in se], "df": df, "p": raw, "Adjusted p": adjusted,
            "Method": GAMES if posthoc == GAMES else TAMHANE if posthoc == TAMHANE else posthoc})
        if half is not None:
            restored, lower, upper = _intervals(differences, half, scale)
            pairs["Difference"] = restored
            pairs["CI lower"] = lower
            pairs["CI upper"] = upper
            pairs["Confidence level (%)"] = level
        pairs["Significant"] = np.asarray(adjusted) < 1 - level / 100
        tables["Multiple comparisons"] = pairs
    figure, axes = _plot("Group means from summaries", "Group", "Mean")
    axes.errorbar(np.arange(count), means, yerr=half_widths, fmt="o", capsize=4,
                  label=f"Mean and {level:g}% pointwise CI")
    axes.set_xticks(np.arange(count), used.Group.tolist(), rotation=35 if count > 6 else 0)
    axes.legend(fontsize=8)
    descriptive = ["Mean SE", "Mean CI lower", "Mean CI upper"]
    unavailable = not np.isfinite(used[descriptive]).all().all()
    if "Multiple comparisons" in tables:
        columns = [name for name in ("Difference", "SE", "CI lower", "CI upper") if name in tables["Multiple comparisons"]]
        unavailable |= not np.isfinite(tables["Multiple comparisons"][columns]).all().all()
    method = options.get("Method", ORDINARY)
    tables["Settings"] = pd.DataFrame({
        "Setting": ["Model", "Input", "Dispersion type", "Confidence level (%)", "Comparison family",
                    "Groups used", "Groups omitted", "Total N", "Independence", "Summary limits", "Display limits"],
        "Value": ["Welch one-way ANOVA" if method == WELCH else "Welch and Brown–Forsythe one-way ANOVA",
                  options.get("Input", ROWS), options.get("Dispersion type", "SD"), level,
                  "None" if posthoc == "None" else f"All pairs, {posthoc}",
                  count, len(omitted), total,
                  "Groups are assumed independent. Summary data cannot reconstruct paired dependence.",
                  "Summary data cannot reconstruct normality, residuals or the data distribution.",
                  "Some quantities are not representable in the original units and are blank; scaled inference is retained."
                  if unavailable else "None"]})
    return Result(tables, figure)


def summary_anova(frame, options):
    used, omitted, level, posthoc = check_options(frame, options)
    if options.get("Method", ORDINARY) != ORDINARY:
        return _unequal(used, omitted, level, posthoc, options)
    means, sds, sizes = (used[name].to_numpy(dtype=float) for name in ("Mean", "SD", "N"))
    count, total = len(used), sum(map(int, used.N))
    origin = .5*means.min() + .5*means.max()
    shifted = means-origin
    scale = max(abs(shifted).max(), sds.max())
    normalized, errors = shifted/scale, sds/scale
    grand = np.average(normalized, weights=sizes)
    within = np.sum((sizes-1)*errors**2)
    between = np.sum(sizes*(normalized-grand)**2)
    df1, df2 = count-1, total-count
    residual = within/df2
    error_field = "Dispersion" if options.get("Input",ROWS) == ROWS else "Variables"
    if not residual > 0:
        raise FieldError(error_field, "ANOVA requires positive pooled residual variance.")
    with np.errstate(over="ignore", invalid="ignore"):
        statistic = (between/df1)/residual
    if not np.isfinite(statistic):
        raise FieldError(error_field, "The ANOVA statistic is outside the supported numeric range.")
    table = pd.DataFrame([
        {"Term":"Between groups", "SS":_restore(between,scale,2), "df":df1,
         "MS":_restore(between/df1,scale,2), "F":statistic, "F df1":df1,"F df2":df2,
         "p":stats.f.sf(statistic,df1,df2)},
        {"Term":"Residual", "SS":_restore(within,scale,2), "df":df2, "MS":_restore(residual,scale,2)}])
    table["Note"] = ["SS or MS cannot be represented in the original units; inference uses scaled values."
                     if not np.isfinite([row.SS,row.MS]).all() else "" for row in table.itertuples()]
    tables = {"ANOVA":table, "Summaries used":used, "Omitted groups":omitted}
    if posthoc != "None":
        first, second = np.array(list(combinations(range(count),2))).T
        differences = normalized[first]-normalized[second]
        se = np.sqrt(residual*(1/sizes[first]+1/sizes[second]))
        t = abs(differences/se)
        raw = 2*stats.t.sf(t,df2)
        adjusted = (stats.studentized_range.sf(np.sqrt(2)*t,count,df2) if posthoc == "Tukey" else
                    multipletests(raw,method="holm" if posthoc == "Holm" else "bonferroni")[1])
        pairs = pd.DataFrame({"First":used.Group.iloc[first].to_numpy(), "Second":used.Group.iloc[second].to_numpy(),
                              "First source row":used["Source row"].iloc[first].to_numpy(),
                              "Second source row":used["Source row"].iloc[second].to_numpy(),
                              "Difference":[_restore(x,scale) for x in differences],
                              "SE":[_restore(x,scale) for x in se],"df":df2,"p":raw,"Adjusted p":adjusted,
                              "Method":"Tukey–Kramer" if posthoc == "Tukey" else posthoc})
        if posthoc == "Tukey":
            half = stats.studentized_range.ppf(level/100,count,df2)*se/np.sqrt(2)
            pairs["CI lower"] = [_restore(x,scale) for x in differences-half]
            pairs["CI upper"] = [_restore(x,scale) for x in differences+half]
            pairs["Confidence level (%)"] = level
        pairs["Significant"] = adjusted < 1-level/100
        tables["Multiple comparisons"] = pairs
    critical = stats.t.isf((1-level/100)/2,df2)
    pooled_se = np.sqrt(residual/sizes)
    half_widths = np.array([_restore(critical*x,scale) for x in pooled_se])
    with np.errstate(over="ignore", invalid="ignore"):
        used["Pooled mean CI lower"] = means-half_widths
        used["Pooled mean CI upper"] = means+half_widths
    used.replace([np.inf,-np.inf],np.nan,inplace=True)
    figure, axes = _plot("Group means from summaries", "Group", "Mean")
    axes.errorbar(np.arange(count),means,yerr=half_widths,fmt="o",capsize=4,
                  label=f"Mean and {level:g}% pointwise CI (pooled variance)")
    axes.set_xticks(np.arange(count),used.Group.tolist(),rotation=35 if count>6 else 0)
    axes.legend(fontsize=8)
    unavailable = (not np.isfinite(table[["SS","MS"]]).all().all()
                   or not np.isfinite(used[["Pooled mean CI lower","Pooled mean CI upper"]]).all().all())
    if "Multiple comparisons" in tables:
        columns = [name for name in ("Difference","SE","CI lower","CI upper") if name in tables["Multiple comparisons"]]
        unavailable |= not np.isfinite(tables["Multiple comparisons"][columns]).all().all()
    tables["Settings"] = pd.DataFrame({"Setting":["Model","Input","Dispersion type","Confidence level (%)",
        "Groups used","Groups omitted","Total N","Display limits","Interpretation"],"Value":["Ordinary one-way ANOVA",
        options.get("Input",ROWS),options.get("Dispersion type","SD"),level,count,len(omitted),total,
        "Some quantities are not representable in the original units and are blank; scaled inference is retained." if unavailable else "None",
        "Independent groups and common variance assumed. Summary data cannot assess normality or paired dependence."]})
    return Result(tables,figure)
