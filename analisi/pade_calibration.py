"""Rational Padé (1,1) calibration on a normalized X domain.

With z = (X − X min) / (X max − X min) in [0, 1], the model fits

    Y = (A0 + A1 · z) / (1 + B1 · z)

by unweighted ordinary least squares in Y, constraining the denominator
1 + B1 · z to stay at least 1e-6 over the closed observed interval [0, 1].
Since the denominator is affine and equals 1 at z = 0, the constraint is
equivalent to 1 + B1 >= 1e-6.

Estimation uses variable projection over the single nonlinear parameter B1
(searched globally in u = ln(1 + B1), including the linearized initializer
and B1 = 0, then refined by bounded scalar minimization) followed by bounded
trust-region least squares with an analytic Jacobian. Only improvements that
remain finite and satisfy the denominator bound are accepted.

Because 1 + B1 · z > 0 on [0, 1], the derivative (A1 − A0 · B1) / (1 + B1 · z)²
never changes sign. Inversion on [0, 1] is therefore unique whenever the curve
span |f(1) − f(0)| exceeds the scale-relative flatness tolerance
max(1e-8 · scale, 1e-12).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import least_squares, minimize_scalar

from .field_error import FieldError
from .stats import complete

MODEL = "Padé (1,1)"
PARAMETERS = ("A0", "A1", "B1")
DENOMINATOR_MIN = 1e-6
# Smallest float64 b1 such that 1.0 + b1 >= DENOMINATOR_MIN strictly in IEEE-754 arithmetic.
B1_MIN = float(np.nextafter(-1.0 + DENOMINATOR_MIN, 0.0)) if (1.0 + (-1.0 + DENOMINATOR_MIN)) < DENOMINATOR_MIN else float(-1.0 + DENOMINATOR_MIN)
MIN_OBSERVATIONS = 4
MIN_DISTINCT_X = 3
CURVE_POINTS = 300

# Scale-relative tolerance used for curve identifiability and endpoint rounding acceptance.
FLAT_REL_TOL = 1e-8
FLAT_ABS_TOL = 1e-12
# Condition guard for orthogonal two-column projection at extreme B1.
ORTHO_TOL = 1e-12
# Upper cap for u = ln(1 + B1) during adaptive positive-B1 expansion (~4.85e8).
MAX_LOG_DENOM = 20.0

IN_RANGE = "In range"
OUT_OF_RANGE = "Out of range"
NOT_IDENTIFIABLE = "Not identifiable"
OUTSIDE_CALIBRATION = "Outside calibration"


@dataclass(frozen=True)
class PadeFit:
    a0: float
    a1: float
    b1: float
    x_min: float
    x_max: float
    x_scale: float
    n: int
    distinct_x: int
    df: int
    residual_ss: float
    residual_sd: float
    r_squared: float
    min_denominator: float
    y_at_min: float
    y_at_max: float
    identifiable: bool
    parameters: pd.DataFrame
    diagnostics: dict[str, object]
    curve: np.ndarray

    @property
    def coefficients(self):
        return (self.a0, self.a1, self.b1)


def tolerance(scale):
    """Scale-relative tolerance for flatness and endpoint rounding."""
    return max(FLAT_REL_TOL * float(scale), FLAT_ABS_TOL)


def evaluate_z(coefficients, z):
    """Evaluate (A0 + A1·z) / (1 + B1·z) for scalar or array z in [0, 1]."""
    a0, a1, b1 = coefficients
    z_arr = np.asarray(z, dtype=float)
    denom = 1.0 + b1 * z_arr
    if not np.isfinite(denom).all() or np.any(denom < DENOMINATOR_MIN):
        raise ValueError("Padé (1,1) denominator approaches zero inside the calibration domain.")
    values = (a0 + a1 * z_arr) / denom
    if not np.isfinite(values).all():
        raise ValueError("Could not evaluate a finite Padé (1,1) calibration curve.")
    return float(values) if np.ndim(z) == 0 else values


def validate_standards(frame, x, y, *, standards=None):
    """Validate calibration standards for Padé (1,1) and return normalized arrays.

    Returns ``(xx, yy, z, x_min, x_max, span, distinct_x)``.
    Raises ``FieldError`` on ``"X"`` or ``"Y"`` when requirements are not met.
    """
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    if standards is None:
        try:
            standards = complete(frame, [x, y])
        except ValueError as error:
            message = str(error)
            field = "Y" if f'"{y}"' in message and f'"{x}"' not in message else "X"
            raise FieldError(field, message) from error
    if standards.empty:
        raise FieldError("X", "The calibration standards do not define an X interval.")
    xx = standards[x].to_numpy(dtype=float)
    yy = standards[y].to_numpy(dtype=float)
    if not np.isfinite(xx).all():
        raise FieldError("X", "The calibration standards contain non-finite X values.")
    if not np.isfinite(yy).all():
        raise FieldError("Y", "The calibration standards contain non-finite Y values.")
    x_min = float(xx.min())
    x_max = float(xx.max())
    span = float(x_max - x_min)
    if not np.isfinite(span) or span <= 0.0:
        raise FieldError("X", "The calibration standards do not define an X interval.")
    distinct_x = int(len(np.unique(xx)))
    if len(xx) < MIN_OBSERVATIONS or distinct_x < MIN_DISTINCT_X:
        raise FieldError("X", "Padé (1,1) requires at least four observations and three distinct X values.")
    z = np.clip((xx - x_min) / span, 0.0, 1.0)
    if not np.isfinite(z).all() or len(np.unique(z)) < MIN_DISTINCT_X:
        raise FieldError("X", "Padé (1,1) requires at least four observations and three distinct X values.")
    y_ptp = float(np.ptp(yy))
    if not np.isfinite(y_ptp):
        raise FieldError("Y", "Response values exceed the numerical range.")
    if y_ptp <= 0.0:
        raise FieldError("Y", "Response values have zero variation.")
    return xx, yy, z, x_min, x_max, span, distinct_x


def _b1_from_u(u):
    b1 = float(np.expm1(u))
    return B1_MIN if b1 < B1_MIN else b1


def _solve_linear_for_b1(z, ys, b1):
    """Exact unweighted OLS for (A0, A1) at fixed B1 via re-orthogonalized Gram-Schmidt."""
    if not np.isfinite(b1) or (1.0 + b1) < DENOMINATOR_MIN:
        return np.inf, None
    denom = 1.0 + b1 * z
    if not np.isfinite(denom).all() or np.any(denom < DENOMINATOR_MIN):
        return np.inf, None
    inv_d = 1.0 / denom
    p = inv_d
    q = z * inv_d
    p_norm = float(np.linalg.norm(p))
    q_norm = float(np.linalg.norm(q))
    if not (np.isfinite(p_norm) and np.isfinite(q_norm) and p_norm > 0.0 and q_norm > 0.0):
        return np.inf, None
    p_hat = p / p_norm
    proj1 = float(np.dot(p_hat, q))
    r = q - proj1 * p_hat
    proj2 = float(np.dot(p_hat, r))
    r = r - proj2 * p_hat
    proj = proj1 + proj2
    r_norm = float(np.linalg.norm(r))
    if not np.isfinite(r_norm) or r_norm <= ORTHO_TOL * q_norm:
        return np.inf, None
    r_hat = r / r_norm
    a1 = float(np.dot(r_hat, ys)) / r_norm
    a0 = (float(np.dot(p_hat, ys)) - proj * a1) / p_norm
    if not (np.isfinite(a0) and np.isfinite(a1)):
        return np.inf, None
    resid = ys - (a0 + a1 * z) * inv_d
    ss = float(np.dot(resid, resid))
    if not np.isfinite(ss):
        return np.inf, None
    return ss, (a0, a1, float(b1))


def _linearized_b1_guess(z, ys):
    """Initial B1 from the linearized equation y ≈ A0 + A1·z − B1·(z·y)."""
    design = np.column_stack((np.ones_like(z), z, -z * ys))
    try:
        coeffs, *_ = np.linalg.lstsq(design, ys, rcond=None)
    except np.linalg.LinAlgError:
        return None
    b1 = float(coeffs[2])
    if np.isfinite(b1) and (1.0 + b1) >= DENOMINATOR_MIN:
        return b1
    return None


def _polish_least_squares(z, ys, start, best_ss):
    """Refine (A0, A1, B1) with bounded TRF and analytic Jacobian; accept only strict improvements."""
    def residuals(params):
        a0, a1, b1 = params
        return (a0 + a1 * z) / (1.0 + b1 * z) - ys

    def jacobian(params):
        a0, a1, b1 = params
        inv_d = 1.0 / (1.0 + b1 * z)
        yhat = (a0 + a1 * z) * inv_d
        return np.column_stack((inv_d, z * inv_d, -z * yhat * inv_d))

    try:
        result = least_squares(
            residuals,
            np.asarray(start, dtype=float),
            jac=jacobian,
            bounds=([-np.inf, -np.inf, B1_MIN], [np.inf, np.inf, np.inf]),
            method="trf",
            ftol=1e-14,
            xtol=1e-14,
            gtol=1e-14,
            max_nfev=120,
        )
    except Exception:
        return best_ss, start
    cand = tuple(float(v) for v in result.x)
    if not np.isfinite(cand).all() or (1.0 + cand[2]) < DENOMINATOR_MIN:
        return best_ss, start
    # Re-evaluate residual SS directly and compare with VarPro solution at the same B1.
    denom = 1.0 + cand[2] * z
    if not np.isfinite(denom).all() or np.any(denom < DENOMINATOR_MIN):
        return best_ss, start
    resid = ys - (cand[0] + cand[1] * z) / denom
    ss_trf = float(np.dot(resid, resid))
    chosen_ss, chosen = best_ss, start
    if np.isfinite(ss_trf) and ss_trf < chosen_ss:
        chosen_ss, chosen = ss_trf, cand
    ss_proj, proj = _solve_linear_for_b1(z, ys, cand[2])
    if proj is not None and ss_proj < chosen_ss:
        chosen_ss, chosen = ss_proj, proj
    return chosen_ss, chosen


def _estimate_scaled(z, ys):
    """Global 1D variable projection over u = ln(1 + B1) + bounded TRF polish."""
    u_min = float(np.log(DENOMINATOR_MIN))
    # Log-uniform grid in (1 + B1) covering [1e-6, 1] and [1, ~1.63e5], with u = 0 (B1 = 0) included.
    neg_grid = np.linspace(u_min, 0.0, 36)
    pos_grid = np.linspace(0.0, 12.0, 49)[1:]
    u_nodes = list(np.concatenate((neg_grid, pos_grid)))

    guess_b1 = _linearized_b1_guess(z, ys)
    if guess_b1 is not None:
        u_guess = float(np.log1p(guess_b1))
        if np.isfinite(u_guess) and u_min <= u_guess <= MAX_LOG_DENOM:
            u_nodes.append(u_guess)

    u_nodes = sorted(set(u_nodes))
    evaluated = []
    best_ss = np.inf
    best = None

    def probe_b1(b1):
        nonlocal best_ss, best
        ss, sol = _solve_linear_for_b1(z, ys, b1)
        if sol is not None and ss < best_ss:
            best_ss, best = ss, sol
        return ss, sol

    for u in u_nodes:
        ss, _ = probe_b1(_b1_from_u(u))
        evaluated.append((u, ss))

    # Adaptive extension toward larger positive B1 when the best mesh point sits at the upper end.
    while evaluated and evaluated[-1][0] < MAX_LOG_DENOM and evaluated[-1][1] <= best_ss * (1.0 + 1e-12):
        next_u = min(evaluated[-1][0] + 2.0, MAX_LOG_DENOM)
        prev_best = best_ss
        ss, sol = probe_b1(_b1_from_u(next_u))
        evaluated.append((next_u, ss))
        if sol is None or not (ss < prev_best * (1.0 - 1e-12)):
            break

    if best is None:
        raise ValueError("Could not estimate a finite Padé (1,1) calibration curve.")

    # Collect local-minimum brackets and refine the best ones with bounded Brent search.
    brackets = []
    n_eval = len(evaluated)
    for idx in range(n_eval):
        u_cur, ss_cur = evaluated[idx]
        if not np.isfinite(ss_cur):
            continue
        left_ok = idx == 0 or ss_cur <= evaluated[idx - 1][1]
        right_ok = idx == n_eval - 1 or ss_cur <= evaluated[idx + 1][1]
        if left_ok and right_ok:
            left = evaluated[max(0, idx - 1)][0]
            right = evaluated[min(n_eval - 1, idx + 1)][0]
            if right > left:
                brackets.append((ss_cur, left, right))

    brackets.sort(key=lambda item: item[0])
    seen_brackets = set()
    for _, left, right in brackets[:4]:
        key = (round(left, 9), round(right, 9))
        if key in seen_brackets:
            continue
        seen_brackets.add(key)
        opt = minimize_scalar(
            lambda u: _solve_linear_for_b1(z, ys, _b1_from_u(u))[0],
            bounds=(left, right),
            method="bounded",
            options={"xatol": 1e-12, "maxiter": 120},
        )
        if np.isfinite(opt.x):
            probe_b1(_b1_from_u(float(opt.x)))

    # Polish the best VarPro solution with bounded TRF.
    best_ss, best = _polish_least_squares(z, ys, best, best_ss)
    return best_ss, best


def is_identifiable(coefficients, observed_y):
    """Return True when the fitted curve is strictly monotone and distinguishable from a constant."""
    y0 = evaluate_z(coefficients, 0.0)
    y1 = evaluate_z(coefficients, 1.0)
    scale = max(float(np.max(np.abs(observed_y))), abs(y0), abs(y1))
    tol = tolerance(scale)
    if abs(y1 - y0) <= tol:
        return False
    a0, a1, b1 = coefficients
    det = a1 - a0 * b1
    det_scale = abs(a1) + abs(a0 * b1)
    if det_scale > 0.0 and abs(det) <= 1e-12 * det_scale:
        return False
    # Confirm monotonicity numerically on a dense grid (guards extreme rounding near the pole).
    grid = evaluate_z(coefficients, np.linspace(0.0, 1.0, 64))
    diff = np.diff(grid)
    if y1 > y0:
        return not bool(np.any(diff < -tol))
    return not bool(np.any(diff > tol))


def fit_pade(frame, x, y, *, standards=None):
    """Fit Padé (1,1) by unweighted OLS in Y on normalized z in [0, 1]."""
    xx, yy, z, x_min, x_max, span, distinct_x = validate_standards(frame, x, y, standards=standards)
    y_scale = float(np.max(np.abs(yy)))
    ys = yy / y_scale

    _, (a0_s, a1_s, b1) = _estimate_scaled(z, ys)
    a0 = float(a0_s * y_scale)
    a1 = float(a1_s * y_scale)
    b1 = float(b1)
    coeffs = (a0, a1, b1)
    if not np.isfinite(coeffs).all():
        raise ValueError("Could not estimate a finite Padé (1,1) calibration curve.")
    min_denom = float(min(1.0, 1.0 + b1))
    if not np.isfinite(min_denom) or min_denom < DENOMINATOR_MIN:
        raise ValueError("Padé (1,1) denominator constraint could not be satisfied.")

    predicted = evaluate_z(coeffs, z)
    residuals = yy - predicted
    residual_ss = float(np.dot(residuals, residuals))
    if not np.isfinite(residual_ss):
        raise ValueError("Residual sum of squares exceeds the numerical range.")
    n = int(len(xx))
    df = n - 3
    residual_sd = float(np.sqrt(residual_ss / df)) if df > 0 else np.nan
    centered = yy - float(np.mean(yy))
    total_ss = float(np.dot(centered, centered))
    r_squared = float(1.0 - residual_ss / total_ss) if total_ss > 0.0 else np.nan

    # Sample the calibration curve on the exact closed [x_min, x_max] domain.
    z_grid = np.linspace(0.0, 1.0, CURVE_POINTS)
    x_grid = x_min + span * z_grid
    x_grid[0] = x_min
    x_grid[-1] = x_max
    y_grid = evaluate_z(coeffs, z_grid)
    curve = np.column_stack((x_grid, y_grid))

    y_at_min = float(y_grid[0])
    y_at_max = float(y_grid[-1])
    identifiable = is_identifiable(coeffs, yy)

    parameters = pd.DataFrame({"Estimate": [a0, a1, b1]}, index=list(PARAMETERS))
    diagnostics = {
        "Model": MODEL,
        "N": n,
        "Distinct X": distinct_x,
        "df": df,
        "Residual SS (Y)": residual_ss,
        "Residual SD": residual_sd,
        "R²": r_squared,
        "X origin (X min)": x_min,
        "X scale (X max - X min)": span,
        "Minimum denominator": min_denom,
    }
    return PadeFit(
        a0=a0,
        a1=a1,
        b1=b1,
        x_min=x_min,
        x_max=x_max,
        x_scale=span,
        n=n,
        distinct_x=distinct_x,
        df=df,
        residual_ss=residual_ss,
        residual_sd=residual_sd,
        r_squared=r_squared,
        min_denominator=min_denom,
        y_at_min=y_at_min,
        y_at_max=y_at_max,
        identifiable=identifiable,
        parameters=parameters,
        diagnostics=diagnostics,
        curve=curve,
    )


def predict_pade(fitted, x_values):
    """Evaluate fitted Padé (1,1) at X values inside [x_min, x_max]."""
    arr = np.asarray(x_values, dtype=float).reshape(-1)
    if arr.size == 0:
        return np.empty(0, dtype=float)
    z = np.clip((arr - fitted.x_min) / fitted.x_scale, 0.0, 1.0)
    return evaluate_z(fitted.coefficients, z)


def invert_pade(fitted, responses):
    """Invert fitted Padé (1,1) for an array of Y responses.

    Returns ``(interpolated_x, statuses)`` with one entry per response.
    """
    resp = np.asarray(responses, dtype=float).reshape(-1)
    solved = np.full(resp.shape, np.nan, dtype=float)
    statuses = np.empty(resp.shape, dtype=object)
    if resp.size == 0:
        return solved, statuses
    if not fitted.identifiable:
        statuses[:] = NOT_IDENTIFIABLE
        return solved, statuses

    a0, a1, b1 = fitted.coefficients
    f0, f1 = fitted.y_at_min, fitted.y_at_max
    low, high = (f0, f1) if f0 <= f1 else (f1, f0)
    span_y = abs(f1 - f0)
    increasing = f1 > f0

    # Vectorized analytic inverse with per-endpoint rounding tolerance.
    scales = np.maximum(np.maximum(abs(f0), abs(f1)), np.abs(resp))
    tols = np.minimum(np.maximum(FLAT_REL_TOL * scales, FLAT_ABS_TOL), 1e-4 * span_y)

    outside = (~np.isfinite(resp)) | (resp < low - tols) | (resp > high + tols)
    statuses[outside] = OUT_OF_RANGE

    active = ~outside
    if not np.any(active):
        return solved, statuses

    y_act = resp[active]
    tol_act = tols[active]
    # Exact or rounding-equivalent endpoint matches on the outer side of f0/f1.
    at_f0 = (y_act == f0) | ((y_act < f0) & (f0 - y_act <= tol_act) if increasing else (y_act > f0) & (y_act - f0 <= tol_act))
    at_f1 = (y_act == f1) | ((y_act > f1) & (y_act - f1 <= tol_act) if increasing else (y_act < f1) & (f1 - y_act <= tol_act))

    x_act = np.full(y_act.shape, np.nan, dtype=float)
    st_act = np.full(y_act.shape, NOT_IDENTIFIABLE, dtype=object)

    x_act[at_f0] = fitted.x_min
    st_act[at_f0] = IN_RANGE
    only_f1 = at_f1 & ~at_f0
    x_act[only_f1] = fitted.x_max
    st_act[only_f1] = IN_RANGE

    interior = ~(at_f0 | at_f1)
    if np.any(interior):
        yi = y_act[interior]
        denom = a1 - yi * b1
        valid = np.isfinite(denom) & (denom != 0.0)
        z_est = np.full(yi.shape, np.nan, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            z_est[valid] = (yi[valid] - a0) / denom[valid]
        # Accept tiny floating-point overshoot at 0 or 1.
        near_zero = np.isfinite(z_est) & (z_est < 0.0) & (z_est >= -1e-8)
        near_one = np.isfinite(z_est) & (z_est > 1.0) & (z_est <= 1.0 + 1e-8)
        z_est[near_zero] = 0.0
        z_est[near_one] = 1.0
        in_unit = np.isfinite(z_est) & (z_est >= 0.0) & (z_est <= 1.0)
        if np.any(in_unit):
            z_ok = z_est[in_unit]
            y_check = (a0 + a1 * z_ok) / (1.0 + b1 * z_ok)
            check_tol = np.maximum(1e-6 * np.maximum(np.maximum(abs(f0), abs(f1)), np.abs(yi[in_unit])), 1e-10)
            verified = np.isfinite(y_check) & (np.abs(y_check - yi[in_unit]) <= check_tol)
            x_ok = np.full(z_ok.shape, np.nan, dtype=float)
            st_ok = np.full(z_ok.shape, NOT_IDENTIFIABLE, dtype=object)
            if np.any(verified):
                zv = z_ok[verified]
                xv = np.where(zv == 0.0, fitted.x_min,
                              np.where(zv == 1.0, fitted.x_max,
                                       np.clip(fitted.x_min + fitted.x_scale * zv, fitted.x_min, fitted.x_max)))
                x_ok[verified] = xv
                st_ok[verified] = IN_RANGE
            xi = np.full(yi.shape, np.nan, dtype=float)
            sti = np.full(yi.shape, NOT_IDENTIFIABLE, dtype=object)
            xi[in_unit] = x_ok
            sti[in_unit] = st_ok
            x_act[interior] = xi
            st_act[interior] = sti

    solved[active] = x_act
    statuses[active] = st_act
    return solved, statuses
