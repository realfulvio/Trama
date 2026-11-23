"""Fit bounds and independent drawing coordinates for regression recipes."""
from math import isfinite

import numpy as np
import pandas as pd

from .field_error import FieldError
from .curve_models import MODELS

FIT_MIN, FIT_MAX = "Fit X minimum", "Fit X maximum"
CURVE_MIN, CURVE_MAX, CURVE_POINTS = "Curve X minimum", "Curve X maximum", "Curve points"
FIT_FIELDS = (FIT_MIN, FIT_MAX)
CURVE_FIELDS = (CURVE_MIN, CURVE_MAX, CURVE_POINTS)
FIELDS = (*FIT_FIELDS, *CURVE_FIELDS)
METHODS = {"Linear regression", "Nonlinear regression"}
TAB_TITLE = "Fit and curve range"
CURVE_SHEET = "Curve coordinates"
SHOW_OUTSIDE = "Show observations outside fit"
DEFAULT_POINTS, MAX_POINTS = 300, 2000


def _bound(raw, field):
    if isinstance(raw, str):
        raw = raw.strip().replace(",", ".")
    if raw is None or (isinstance(raw, str) and not raw):
        return None
    try:
        value = float(raw) if not isinstance(raw, (bool, np.bool_)) else np.nan
    except (TypeError, ValueError, OverflowError):
        value = np.nan
    if not isfinite(value):
        message = (f"Choose a whole number from 2 to {MAX_POINTS}." if field == CURVE_POINTS else
                   "Enter a finite X value or leave this field empty.")
        raise FieldError(field, message)
    return value


def ranges(options):
    """Return only the confirmed bounds and curve sample count."""
    settings = {}
    for field in FIELDS:
        if (value := _bound(options.get(field), field)) is not None:
            if field == CURVE_POINTS:
                if not value.is_integer() or not 2 <= value <= MAX_POINTS:
                    raise FieldError(field, f"Choose a whole number from 2 to {MAX_POINTS}.")
                value = int(value)
            settings[field] = value
    for lower, upper in (FIT_FIELDS, CURVE_FIELDS[:2]):
        if lower in settings and upper in settings and settings[lower] >= settings[upper]:
            raise FieldError(upper, "The maximum X must be greater than the minimum X.")
    model = options.get("Model")
    spec = MODELS.get(model) if isinstance(model, str) else None
    if spec is not None:
        for field in (CURVE_MIN, CURVE_MAX):
            if field not in settings:
                continue
            if spec.domain == "positive" and settings[field] <= 0:
                raise FieldError(field, "The drawn curve for this model requires positive X values.")
            if spec.domain == "nonnegative" and settings[field] < 0:
                raise FieldError(field, "The drawn curve for this model requires nonnegative X values.")
    return settings


def normalize(options):
    """Keep accepted recipes numeric and omit the blank fields of an existing recipe."""
    settings = ranges(options)
    for field in FIELDS:
        options.pop(field, None)
    options.update(settings)
    if options.get(SHOW_OUTSIDE) is False:
        options.pop(SHOW_OUTSIDE)
    return settings


def fitting_rows(frame, x, settings, *, return_outside=False):
    if not any(field in settings for field in FIT_FIELDS):
        return (frame, frame.iloc[:0]) if return_outside else frame
    if x not in frame:
        raise FieldError("X", "Select an X column.")
    source = frame[x]
    numeric = pd.to_numeric(source, errors="coerce")
    if np.iscomplexobj(numeric.to_numpy()):
        raise FieldError("X", "The X column must contain real, finite values.")
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    finite = np.isfinite(values)
    if (source.notna().to_numpy() & ~finite).any():
        raise FieldError("X", "The X column must contain real, finite values.")
    selected = finite & (values >= settings.get(FIT_MIN, -np.inf)) & (values <= settings.get(FIT_MAX, np.inf))
    if not selected.any():
        field = FIT_MIN if FIT_MIN in settings else FIT_MAX
        raise FieldError(field, "No observations fall within the fit X range.")
    fitted = frame.iloc[selected]
    return (fitted, frame.iloc[finite & ~selected]) if return_outside else fitted


def extra_xy(frame, x, y):
    """Finite observations available to draw outside the fit."""
    numbers = frame[[x, y]].apply(pd.to_numeric, errors="coerce")
    values = numbers.to_numpy(dtype=complex if np.iscomplexobj(numbers.to_numpy()) else float, na_value=np.nan)
    real = np.isfinite(values).all(axis=1) & np.isreal(values).all(axis=1)
    return pd.DataFrame(values[real].real, columns=[x, y])


def drawing_grid(observed_x, settings):
    if not any(field in settings for field in CURVE_FIELDS):
        return None
    lower = settings.get(CURVE_MIN, float(np.min(observed_x)))
    upper = settings.get(CURVE_MAX, float(np.max(observed_x)))
    if lower >= upper:
        field = CURVE_MAX if CURVE_MAX in settings else CURVE_MIN
        raise FieldError(field, "The drawn curve needs a maximum X greater than its minimum X.")
    fractions = np.linspace(0., 1., settings.get(CURVE_POINTS, DEFAULT_POINTS))
    return lower * (1 - fractions) + upper * fractions


def coordinate_table(grid, predicted, observed_x):
    if not np.isfinite(predicted).all():
        raise FieldError(CURVE_MAX, "The model must predict finite values on the drawn curve.")
    return pd.DataFrame({"X": grid, "Predicted": predicted,
                         "Extrapolated": (grid < np.min(observed_x)) | (grid > np.max(observed_x))})
