"""ROC curve, diagnostic thresholds with binomial intervals, and DeLong AUC inference.

Every table is derived from the same cumulative counts. Scores are oriented so that a
higher oriented score always points to a patient, and the diagnostic rule is expressed
on the original scale as ``score >= threshold`` (Higher) or ``score <= threshold`` (Lower).
"""
import numpy as np
import pandas as pd
from scipy import stats

from .processing import FieldError, INTERVALS, WILSON_BROWN, _column, _intervals, _number

HIGHER, LOWER, AUTOMATIC = "Higher in patients", "Lower in patients", "Automatic"
DIRECTIONS = (AUTOMATIC, HIGHER, LOWER)
ROC_INTERVALS = (INTERVALS[1], INTERVALS[2], WILSON_BROWN)
SHOW_AS = ("Fractions", "Percentages")
DEFAULT_LEVEL = 95.0
INF_TEXT = {1: "+∞", -1: "−∞"}


def validate_level(value):
    level = _number(DEFAULT_LEVEL if value is None else value, "Confidence level (%)")
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)", "Confidence level (%) must be greater than 0 and less than 100.")
    return level


def _mean_gap_positive(positive, negative):
    """True when the patient mean is below the control mean, without overflowing."""
    with np.errstate(all="ignore"):
        means = positive.mean(), negative.mean()
    if not np.isfinite(means).all():
        scale = max(np.abs(positive).max(), np.abs(negative).max())
        means = (positive / scale).mean(), (negative / scale).mean()
    return means[0] < means[1]


def _midpoint(low, high):
    """Overflow-safe average of two finite floats with low < high."""
    if (low < 0) != (high < 0) and low != 0 and high != 0:
        return low / 2 + high / 2
    return low + (high - low) / 2


def binomial_interval(method, successes, totals, level):
    """Pointwise interval for each successes/totals pair; limits are exact at 0 and n."""
    if method not in ROC_INTERVALS:
        raise FieldError("Confidence interval", "Choose a confidence interval method.")
    k, n = np.asarray(successes, dtype=float), np.asarray(totals, dtype=float)
    lower, upper = _intervals(method, k, n, level)
    return np.where(k == 0, 0., lower), np.where(k == n, 1., upper)


def threshold_text(value):
    return INF_TEXT[int(np.sign(value))] if np.isinf(value) else repr(float(value)).removesuffix(".0")


def _rule(sign, value):
    return f"score {'>=' if sign > 0 else '<='} {threshold_text(value)}"


def _auc(negative, positive, level):
    """Mann–Whitney AUC with the DeLong placements and observed variance."""
    m, n = len(positive), len(negative)
    # Placement values: phi = 1, 1/2 or 0 for a patient above, tied with or below a control.
    per_case = (negative.searchsorted(positive, "left") + negative.searchsorted(positive, "right")) / (2 * n)
    per_control = 1 - (positive.searchsorted(negative, "left") + positive.searchsorted(negative, "right")) / (2 * m)
    auc = float(per_case.mean())
    constant = np.ptp(per_case) == 0 and np.ptp(per_control) == 0
    variance = 0.0 if constant else float(per_case.var(ddof=1) / m + per_control.var(ddof=1) / n)
    se = float(np.sqrt(variance))
    half_width = stats.norm.isf((100 - level) / 200) * se
    p = float(2 * stats.norm.sf(abs(auc - .5) / se)) if se > 0 else np.nan
    return auc, variance, se, max(0., auc - half_width), min(1., auc + half_width), p


def roc_analysis(frame, controls, patients, direction=AUTOMATIC, level=DEFAULT_LEVEL,
                 interval=ROC_INTERVALS[0], show_as=SHOW_AS[0]):
    """Return (summary, curve points, diagnostic thresholds) for a two-column ROC."""
    if controls == patients:
        raise FieldError("Patient", "Choose distinct control and patient columns.")
    level = validate_level(level)
    if interval not in ROC_INTERVALS:
        raise FieldError("Confidence interval", "Choose a confidence interval method.")
    if show_as not in SHOW_AS:
        raise FieldError("Show as", "Choose fractions or percentages.")
    if direction not in DIRECTIONS:
        raise FieldError("Direction", "Choose the positive score direction.")
    negative = _column(frame, controls, "Control").dropna().to_numpy()
    positive = _column(frame, patients, "Patient").dropna().to_numpy()
    if min(len(negative), len(positive)) < 2:
        raise ValueError("ROC needs at least two observations per group.")
    if direction == AUTOMATIC:
        direction = LOWER if _mean_gap_positive(positive, negative) else HIGHER
    sign = 1 if direction == HIGHER else -1
    # Adding 0.0 turns -0.0 into 0.0 so both zeros form one block of tied scores.
    negative, positive = np.sort(sign * negative + 0.0), np.sort(sign * positive + 0.0)
    m, n = len(positive), len(negative)

    values = np.unique(np.r_[negative, positive])                  # ascending distinct oriented scores
    at_or_above_p = m - positive.searchsorted(values)              # patients with score >= block value
    at_or_above_n = n - negative.searchsorted(values)
    tp = np.r_[0, at_or_above_p[::-1]]                             # row i: positives are the top i blocks
    fp = np.r_[0, at_or_above_n[::-1]]
    curve = pd.DataFrame({"Threshold": np.r_[np.inf, values[::-1]] * sign + 0.0,
                          "False positive rate": fp / n, "True positive rate": tp / m})

    auc, variance, se, low, high, p = _auc(negative, positive, level)

    # Threshold rows: +/- infinity at the ends, the midpoint of adjacent distinct scores in between.
    oriented = np.empty(len(tp))
    kinds = np.full(len(tp), "Midpoint", dtype=object)
    oriented[0], oriented[-1] = np.inf, -np.inf
    kinds[0] = kinds[-1] = "Endpoint"
    for row in range(1, len(tp) - 1):
        upper, lower = values[len(values) - row], values[len(values) - row - 1]   # block just left/just joined
        middle = _midpoint(lower, upper)
        if lower < middle < upper:
            oriented[row] = middle
        else:                                                      # rounding collapsed the gap
            oriented[row], kinds[row] = upper, "Observed boundary"
    threshold = oriented * sign + 0.0
    tn, fn = n - fp, m - tp

    # Integer numerators of Youden's J keep exact ties exact: J = numerator / (m * n).
    numerator = tp.astype(np.int64) * n + tn.astype(np.int64) * m - m * n
    interior = kinds != "Endpoint"
    best = numerator[interior].max() if interior.any() else 0
    candidate = interior & (numerator == best) if best > 0 else np.zeros(len(tp), dtype=bool)

    sens_low, sens_high = binomial_interval(interval, tp, np.full(len(tp), m), level)
    spec_low, spec_high = binomial_interval(interval, tn, np.full(len(tp), n), level)
    percent = show_as == SHOW_AS[1]
    scale, unit = (100., " (%)") if percent else (1., "")
    label = f"{level:g}%"
    table = pd.DataFrame({
        "Threshold": threshold,
        "Threshold type": kinds,
        "Rule": [_rule(sign, value) for value in threshold],
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        f"Sensitivity{unit}": scale * tp / m,
        f"Sensitivity CI {label} low{unit}": scale * sens_low,
        f"Sensitivity CI {label} high{unit}": scale * sens_high,
        f"Specificity{unit}": scale * tn / n,
        f"Specificity CI {label} low{unit}": scale * spec_low,
        f"Specificity CI {label} high{unit}": scale * spec_high,
        "Youden J": numerator / (m * n),
        "Youden candidate": np.where(candidate, "Yes", ""),
    })

    shown = f"{level:g}"
    report = {"AUC": auc, "SE (DeLong)": se, "Variance (DeLong)": variance,
              f"CI {shown}% low": low, f"CI {shown}% high": high,
              "p (normal approximation)": p, "Control N": n, "Patient N": m, "Direction": direction,
              "AUC method": "Normal approximation with observed DeLong standard error; null hypothesis AUC = 0.5",
              "Confidence level (%)": level, "Binomial interval": interval,
              "Interval coverage": "Pointwise per threshold; thresholds chosen on the sample are not corrected "
                                   "for selection optimism",
              "Youden candidates": (", ".join(threshold_text(value) for value in threshold[candidate])
                                    if candidate.any() else "None (no interior threshold has J > 0)")}
    if se == 0:
        report["p note"] = "Zero DeLong variance: the standard error is zero and p is not defined."
    if candidate.any():
        report["Candidate note"] = ("Interior thresholds with maximum J > 0, descriptive only. Selecting the "
                                    "maximum on the sample is exploratory and needs validation on independent data.")
    report["Endpoint note"] = "Rows with type Endpoint are curve sentinels (±∞), not observed thresholds."
    return report, curve, table


# ---------------------------------------------------------------------------
# Paired comparison of two correlated ROC curves (DeLong, DeLong and Clarke-Pearson 1988)
# ---------------------------------------------------------------------------
PAIRED_DIRECTIONS = (HIGHER, LOWER)


def _placements(negative, positive):
    """Placement values aligned with the subjects; sorted copies serve only the searches."""
    sorted_negative, sorted_positive = np.sort(negative), np.sort(positive)
    m, n = len(positive), len(negative)
    per_case = sorted_negative.searchsorted(positive, "left") + sorted_negative.searchsorted(positive, "right")
    per_control = (2 * m - sorted_positive.searchsorted(negative, "left")
                   - sorted_positive.searchsorted(negative, "right"))
    return per_case, per_control

def _pairs(frame, first, second, fields):
    """Complete cases within one block; returns aligned arrays and the incomplete-pair count."""
    a, b = _column(frame, first, fields[0]), _column(frame, second, fields[1])
    shared = a.notna() & b.notna()
    incomplete = int((a.notna() ^ b.notna()).sum())
    return a[shared].to_numpy(), b[shared].to_numpy(), incomplete


def _curve(negative, positive):
    values = np.unique(np.r_[negative, positive])
    tp = np.r_[0, (len(positive) - np.sort(positive).searchsorted(values))[::-1]]
    fp = np.r_[0, (len(negative) - np.sort(negative).searchsorted(values))[::-1]]
    return values[::-1], fp / len(negative), tp / len(positive)


def compare_paired_roc(frame, control_a, control_b, patient_a, patient_b, direction_a=HIGHER,
                       direction_b=HIGHER, level=DEFAULT_LEVEL):
    """Return (summary, curve points of marker A, curve points of marker B)."""
    names = (control_a, control_b, patient_a, patient_b)
    if len(set(names)) != 4:
        raise FieldError("Control A", "Choose four distinct columns: Control A, Control B, Patient A and Patient B.")
    for field, direction in (("Direction A", direction_a), ("Direction B", direction_b)):
        if direction not in PAIRED_DIRECTIONS:
            raise FieldError(field, "Choose Higher in patients or Lower in patients for each marker.")
    level = validate_level(level)
    frame = frame.reset_index(drop=True)
    ca, cb, lost_controls = _pairs(frame, control_a, control_b, ("Control A", "Control B"))
    pa, pb, lost_patients = _pairs(frame, patient_a, patient_b, ("Patient A", "Patient B"))
    n, m = len(ca), len(pa)
    if min(n, m) < 2:
        raise ValueError("Paired ROC comparison needs at least two valid pairs per class.")
    sign_a, sign_b = (1 if d == HIGHER else -1 for d in (direction_a, direction_b))
    ca, pa, cb, pb = sign_a * ca + 0.0, sign_a * pa + 0.0, sign_b * cb + 0.0, sign_b * pb + 0.0
    case_counts_a, control_counts_a = _placements(ca, pa)
    case_counts_b, control_counts_b = _placements(cb, pb)
    case_a, case_b = case_counts_a / (2 * n), case_counts_b / (2 * n)
    control_place_a, control_place_b = control_counts_a / (2 * m), control_counts_b / (2 * m)

    def variance(positives, controls):
        if np.ptp(positives) == 0 and np.ptp(controls) == 0:
            return 0.0
        return float(positives.var(ddof=1) / m + controls.var(ddof=1) / n)

    auc_a, auc_b = float(case_a.mean()), float(case_b.mean())
    case_difference = case_counts_a - case_counts_b
    control_difference = control_counts_a - control_counts_b
    delta = float(case_difference.mean() / (2 * n))
    covariance = float(np.cov(case_a, case_b, ddof=1)[0, 1] / m + np.cov(control_place_a, control_place_b, ddof=1)[0, 1] / n)
    # The difference variance comes straight from the placement differences, which is stable
    # and equals Var(A) + Var(B) - 2 Cov(A, B).
    var_delta = variance(case_difference / (2 * n), control_difference / (2 * m))
    se = float(np.sqrt(var_delta))
    half = stats.norm.isf((100 - level) / 200) * se
    z = delta / se if se > 0 else np.nan
    p = float(2 * stats.norm.sf(abs(z))) if se > 0 else np.nan
    shown = f"{level:g}"
    report = {"AUC A": auc_a, "AUC B": auc_b, "Difference (A − B)": delta,
              "Variance A": variance(case_a, control_place_a), "Variance B": variance(case_b, control_place_b),
              "Covariance (A, B)": covariance, "Variance of difference": var_delta, "SE (difference)": se,
              f"CI {shown}% low (difference)": max(-1., delta - half),
              f"CI {shown}% high (difference)": min(1., delta + half),
              "Z": z, "p (normal approximation)": p,
              "Control pairs used": n, "Patient pairs used": m,
              "Incomplete control pairs discarded": lost_controls,
              "Incomplete patient pairs discarded": lost_patients,
              "Direction A": direction_a, "Direction B": direction_b, "Confidence level (%)": level,
              "Method": "Paired DeLong test: normal approximation with the observed covariance of the placement "
                        "values; null hypothesis AUC A = AUC B"}
    if se == 0:
        report["Note"] = "Zero variance of the difference: the standard error is zero, Z and p are not defined."
    curves = []
    for sign, negative, positive in ((sign_a, ca, pa), (sign_b, cb, pb)):
        thresholds, fpr, tpr = _curve(negative, positive)
        curves.append(pd.DataFrame({"Threshold": np.r_[np.inf, thresholds] * sign + 0.0,
                                    "False positive rate": fpr, "True positive rate": tpr}))
    return report, curves[0], curves[1]
