"""Diagnostic, agreement and exploratory statistics."""
import numpy as np
import pandas as pd
from scipy import stats

from .data import decimal_comma
from .processing import FieldError
from .stats import complete


def roc(frame, controls, patients, direction, level=95.0):
    """Two-column ROC summary and curve points; see ``roc.roc_analysis`` for the threshold table."""
    from .roc import roc_analysis

    report, curve, _ = roc_analysis(frame, controls, patients, direction, level)
    return report, curve


LOG_RATIO = "Log ratio (geometric)"
AGREEMENT_METHODS = ("Difference", "Ratio", "Percent difference", LOG_RATIO)
COVERAGE, CONFIDENCE = "Agreement coverage (%)", "Confidence level (%)"
LIMIT_INTERVALS, CONFIDENCE_BANDS = "Confidence intervals for agreement limits", "Show confidence bands"
DEFAULT_PERCENT = 95.0


def _percent(value, field):
    try:
        number = float(decimal_comma(value) if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, f"{field} must be a number.") from None
    if not np.isfinite(number) or not 0 < number < 100:
        raise FieldError(field, f"{field} must be greater than 0 and less than 100.")
    return number


def _flag(value, field):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise FieldError(field, f"{field} must be on or off.")


def _mean_sd(values):
    """Sample mean and SD; rescaled by the largest magnitude only when the direct sums overflow."""
    with np.errstate(all="ignore"):
        mean, sd = values.mean(), values.std(ddof=1)
    if not np.isfinite([mean, sd]).all():
        scale = np.abs(values).max()
        scaled = values / scale
        mean, sd = scaled.mean() * scale, scaled.std(ddof=1) * scale
    return float(mean), float(sd)


def _positive_logs(frame, data, first, second):
    values = data[[first, second]]
    bad = values <= 0
    if bad.to_numpy().any():
        # Report the sheet position of the first offending complete pair, not the label of the filtered frame.
        numeric = frame[[first, second]].apply(pd.to_numeric, errors="coerce")
        rows = np.flatnonzero(numeric.notna().all(axis=1).to_numpy())
        row, column = next((r, c) for r, c in zip(*np.nonzero(bad.to_numpy())))
        name = (first, second)[column]
        raise FieldError(("First", "Second")[column], f'Log ratio needs positive values: column "{name}" has {values.iloc[row, column]:g} '
                               f"in row {rows[row] + 1}.")
    return np.log(values[first].to_numpy()), np.log(values[second].to_numpy())


def agreement(frame, first, second, mode="Difference", coverage=DEFAULT_PERCENT, confidence=DEFAULT_PERCENT,
              limit_intervals=False):
    """Bland–Altman summary: ``report``, ``points`` and the ``display`` geometry used by the plot.

    Limits are m ± z·s with z = Φ⁻¹((1 + coverage/100)/2). The bias interval is m ± t·s/√n and, when
    requested, each limit gets the approximate interval limit ± t·s·√(1/n + z²/(2(n−1))) with
    t = t(n−1, (1 + confidence/100)/2) (Bland and Altman 1999). Coverage and confidence are independent.
    """
    if mode not in AGREEMENT_METHODS:
        raise ValueError("Unknown Bland–Altman mode.")
    for name, label in ((first, "First"), (second, "Second")):
        if name not in frame:
            raise FieldError(label, f"Choose a column for {label}.")
    if first == second:
        raise FieldError("Second", "Choose two distinct columns for First and Second.")
    coverage, confidence = _percent(coverage, COVERAGE), _percent(confidence, CONFIDENCE)
    limit_intervals = _flag(limit_intervals, LIMIT_INTERVALS)
    data = complete(frame, [first, second])
    n = len(data)
    if n < 3:
        raise ValueError("Bland–Altman needs at least three complete pairs.")
    a, b = data[first], data[second]
    logs = mode == LOG_RATIO
    if logs:
        log_a, log_b = _positive_logs(frame, data, first, second)
        with np.errstate(all="ignore"):
            average = pd.Series(np.exp((log_a + log_b) / 2), index=data.index)
        working = pd.Series(log_a - log_b, index=data.index)
        with np.errstate(all="ignore"):
            ratios = np.exp(working.to_numpy())
        differences = pd.Series(_finite_array(ratios, "A First / Second ratio"), index=data.index)
    else:
        average = a / 2 + b / 2
        working = differences = a - b
        if mode == "Percent difference":
            if (average == 0).any():
                raise ValueError("Percent difference requires nonzero paired averages.")
            working = differences = 100 * differences / average
        elif mode == "Ratio":
            if (b == 0).any():
                raise ValueError("Ratio requires a nonzero second measurement in every pair.")
            working = differences = a / b
    bias, sd = _mean_sd(working.to_numpy())
    z = stats.norm.isf((100 - coverage) / 200)
    t = stats.t.isf((100 - confidence) / 200, n - 1)
    half_bias = t * sd / np.sqrt(n)
    lower, upper = bias - z * sd, bias + z * sd

    def scale(value):
        with np.errstate(all="ignore"):
            shown = float(np.exp(value) if logs else value)
        if not np.isfinite(shown) or (logs and shown <= 0):
            domain = "finite positive" if logs else "finite"
            raise ValueError(f"An agreement estimate is not representable as a {domain} number.")
        return shown

    legacy = coverage == confidence == DEFAULT_PERCENT
    ci = f"Bias CI {str(confidence).removesuffix('.0')}%"
    display = {"bias": scale(bias), "lower": scale(lower), "upper": scale(upper),
               "log": logs, "neutral": 1.0 if logs else None}
    spread = ({"SD of log ratio": sd, "Geometric SD (exp of SD of log ratio)": scale(sd)}
              if logs else {"SD": sd})
    report = {"N": n, "Bias": display["bias"], **spread, f"{ci} low": scale(bias - half_bias),
              f"{ci} high": scale(bias + half_bias), "Lower agreement limit": display["lower"],
              "Upper agreement limit": display["upper"]}
    if not legacy or limit_intervals or logs:
        report[COVERAGE], report[CONFIDENCE] = coverage, confidence
    if limit_intervals:
        half_limit = t * sd * np.sqrt(1 / n + z * z / (2 * (n - 1)))
        for key, label, limit in (("lower_band", "Lower limit", lower), ("upper_band", "Upper limit", upper)):
            low, high = scale(limit - half_limit), scale(limit + half_limit)
            display[key] = low, high
            report.update({f"{label} CI low": low, f"{label} CI high": high})
    points = pd.DataFrame({"Mean": average, mode: differences})
    if logs:
        points["Log ratio"] = working
    return {"report": report, "points": points, "display": display}


def _finite_array(values, what):
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f"{what} is not representable as a finite positive number.")
    return values


def bland_altman(frame, first, second, mode="Difference", coverage=DEFAULT_PERCENT, confidence=DEFAULT_PERCENT,
                 limit_intervals=False):
    """Public API kept compatible: ``(report, points)``; the legacy call needs no new options."""
    found = agreement(frame, first, second, mode, coverage, confidence, limit_intervals)
    return found["report"], found["points"]


def area_under_curve(frame, x, y, baseline=0.0):
    if not np.isfinite(baseline):
        raise ValueError("Baseline must be finite.")
    data = complete(frame, [x, y]).sort_values(x)
    xx, yy = data[x].to_numpy(), data[y].to_numpy() - baseline
    steps = np.diff(xx)
    if len(data) < 2 or (steps <= 0).any():
        raise ValueError("Area under curve needs at least two distinct X values and no duplicate X.")
    left, right = yy[:-1], yy[1:]
    cross = np.sign(left) * np.sign(right) < 0
    positive = steps * (np.maximum(left, 0) + np.maximum(right, 0)) / 2
    negative = steps * (np.maximum(-left, 0) + np.maximum(-right, 0)) / 2
    split = (np.abs(left[cross]) + np.abs(right[cross]))
    positive[cross] *= np.maximum(left[cross], right[cross]) / split
    negative[cross] *= -np.minimum(left[cross], right[cross]) / split
    return {"Baseline": baseline, "Area above baseline": positive.sum(), "Area below baseline": negative.sum(),
            "Net area": positive.sum() - negative.sum(), "X min": xx[0], "X max": xx[-1], "N": len(data)}, data


def deming(frame, x, y, error_ratio=1.0):
    data = complete(frame, [x, y])
    if len(data) < 3 or not np.isfinite(error_ratio) or error_ratio <= 0:
        raise ValueError("Deming regression requires at least three pairs and a positive error variance ratio.")
    xx, yy = data[x].to_numpy(), data[y].to_numpy()
    dx, dy = xx - xx.mean(), yy - yy.mean()
    sxx, syy, sxy = dx @ dx, dy @ dy, dx @ dy
    if not sxx or not syy or abs(sxy) <= np.finfo(float).eps * np.sqrt(sxx * syy):
        raise ValueError("Deming regression needs varying variables with nonzero covariance.")
    diff = syy - error_ratio * sxx
    root = np.hypot(diff, 2 * np.sqrt(error_ratio) * sxy)
    slope = (diff + root) / (2 * sxy) if diff >= 0 else 2 * error_ratio * sxy / (root - diff)
    return {"N": len(data), "Slope": slope, "Intercept": yy.mean() - slope * xx.mean(),
            "Y / X measurement error variance": error_ratio}, data


def pca(frame, columns, standardize=True):
    data = complete(frame, columns)
    if len(columns) < 2 or len(columns) > 256 or len(data) < 3:
        raise ValueError("PCA needs 2 to 256 variables and at least three complete rows.")
    values = data.to_numpy()
    centered = values - values.mean(axis=0)
    scales = centered.std(axis=0, ddof=1)
    if (scales <= 0).any():
        raise ValueError("Remove constant variables before PCA.")
    if standardize:
        centered /= scales
    u, singular, vt = np.linalg.svd(centered, full_matrices=False)
    # Canonicalize the sign, which is otherwise arbitrary for an eigenvector.
    signs = np.sign(vt[np.arange(len(vt)), np.argmax(np.abs(vt), axis=1)])
    vt *= signs[:, None]
    scores = u * (signs * singular)
    eigenvalues = singular**2 / (len(values) - 1)
    variance = eigenvalues / eigenvalues.sum() * 100
    names = [f"PC{i}" for i in range(1, len(eigenvalues) + 1)]
    return (pd.DataFrame({"Eigenvalue": eigenvalues, "Variance (%)": variance,
                          "Cumulative (%)": variance.cumsum()}, index=names),
            pd.DataFrame(vt.T, index=columns, columns=names),
            pd.DataFrame(scores, index=data.index, columns=names))


def interpolate_linear(frame, x, y, query):
    from .stats import linear

    fit = linear(frame, x, y)
    if fit["Slope"] == 0:
        raise ValueError("The fitted calibration line is horizontal.")
    samples = complete(frame, [query])[query]
    if samples.empty:
        raise ValueError("Enter one or more unknown response values.")
    calibrated = complete(frame, [x, y])[x]
    estimates = (samples - fit["Intercept"]) / fit["Slope"]
    return fit, pd.DataFrame({"Response": samples, "Interpolated X": estimates,
                              "Outside calibration": ~estimates.between(calibrated.min(), calibrated.max())})


def curve_operation(frame, x, y, method, fraction=.5):
    from scipy.integrate import cumulative_trapezoid
    from statsmodels.nonparametric.smoothers_lowess import lowess

    data = complete(frame, [x, y]).sort_values(x)
    xx, yy = data[x].to_numpy(), data[y].to_numpy()
    if len(data) < 3 or (np.diff(xx) <= 0).any():
        raise ValueError("This analysis requires at least three distinct X values with no duplicates.")
    if method == "Differentiate":
        answer = np.gradient(yy, xx, edge_order=2)
    elif method == "Cumulative integral":
        answer = cumulative_trapezoid(yy, xx, initial=0)
    elif method == "LOWESS":
        if not 0 < fraction <= 1 or int(len(xx) * fraction) < 3:
            raise ValueError("Choose a LOWESS fraction that includes at least three observations.")
        if len(xx) > 10000:
            raise ValueError("LOWESS supports up to 10000 complete pairs.")
        answer = lowess(yy, xx, frac=fraction, is_sorted=True, return_sorted=False)
    else:
        raise ValueError("Unknown curve operation.")
    if not np.isfinite(answer).all():
        raise ValueError("Could not calculate the curve at all X values.")
    return pd.DataFrame({"X": xx, "Original Y": yy, method: answer}, index=data.index)
