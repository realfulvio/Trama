"""Shared recipe and model helpers for the planned-contrast editors."""
from fractions import Fraction
import math

from . import anova_planned_contrasts as planned
from .anova_planned_contrasts import ALPHA, CONTRASTS, CORRECTION, DEFAULT_ALPHA, FACTORS, HOLM
from .data import decimal_comma
from .field_error import FieldError
from .i18n import active_language


def coefficient_text(value):
    """A saved coefficient as the editor shows it: integers plain, decimals with the comma in Italian."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if math.isfinite(value) and float(value).is_integer() and abs(value) < 1e15:
        text = str(int(value))
    else:
        text = repr(float(value))
    return text.replace(".", ",") if active_language() == "it" else text


def parse_coefficient(text):
    """Typed text → JSON number. Accepts ``0,5``, ``0.5``, ``-1/3`` and exponents. Raises ValueError."""
    text = str(text).strip()
    if not text:
        raise ValueError("empty")
    if "/" in text:
        numerator, denominator = (Fraction(decimal_comma(part.strip())) for part in text.split("/", 1))
        if denominator == 0:
            raise ValueError("division by zero")
        value = float(numerator / denominator)
    else:
        value = float(decimal_comma(text))
    if math.isfinite(value) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    return value


def clean_state(saved):
    """The four keys of a recipe as an editable state. Malformed parts are kept as far as they can be shown."""
    factors = saved.get(FACTORS)
    factors = [name for name in factors if isinstance(name, str)] if isinstance(factors, (list, tuple)) else []
    contrasts = []
    raw = saved.get(CONTRASTS)
    for record in raw if isinstance(raw, (list, tuple)) else ():
        if not isinstance(record, dict):
            continue
        weights = []
        raw_weights = record.get("weights")
        for weight in raw_weights if isinstance(raw_weights, (list, tuple)) else ():
            if not isinstance(weight, dict):
                continue
            levels = weight.get("levels")
            levels = list(levels) if isinstance(levels, (list, tuple)) else []
            weights.append({"levels": levels, "coefficient": weight.get("coefficient")})
        name = record.get("name")
        contrasts.append({"name": name if isinstance(name, str) else "", "weights": weights})
    correction = saved.get(CORRECTION, HOLM)
    alpha = saved.get(ALPHA, DEFAULT_ALPHA)
    return {FACTORS: factors, CONTRASTS: contrasts, CORRECTION: correction, ALPHA: alpha}


def contrast_context(frame, response, model):
    """The selected model factors, their complete-case levels and a category check for the editor."""
    try:
        levels = planned.frame_levels(frame, response, model) if model else {}
    except (ValueError, KeyError):
        # The response may still be unset. The ANOVA dialog checks it before running.
        levels = {name: sorted(frame[name].dropna().astype(str).unique()) for name in model if name in frame}

    def check(names):
        try:
            planned.check_categories(frame, response, names)
        except FieldError:
            raise
        except (ValueError, KeyError):
            pass

    return levels, check


def check_contrast_input(options, frame, model):
    """Check the recipe and the levels that are visible to the ANOVA before starting the fit."""
    request = planned.check_request(options, model)
    if request is None:
        return
    response = options.get("Response")
    try:
        planned.check_categories(frame, response, model)
        levels = planned.frame_levels(frame, response, model)
    except FieldError:
        raise
    except (ValueError, KeyError):
        return  # the fit reports invalid columns
    planned.check_levels(request[1], request[0], levels, model)
