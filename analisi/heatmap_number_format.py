"""Numeric label formatting and validation for heat-map color legends."""
from decimal import Decimal, InvalidOperation
import math
from numbers import Integral, Real

from .data import decimal_comma
from .field_error import FieldError

NUMBER_FORMAT = "Color legend number format"
LEGEND_DECIMALS = "Color legend decimals"
AUTO_FORMAT, FIXED_FORMAT, SCIENTIFIC_FORMAT = NUMBER_FORMATS = ("Automatic", "Fixed", "Scientific")
DEFAULT_DECIMALS = 2
MIN_DECIMALS = 0
MAX_DECIMALS = 8


def _is_bool(value):
    return isinstance(value, bool) or (type(value).__name__ == "bool_" and type(value).__module__ == "numpy")


def _decimals_error():
    return FieldError(LEGEND_DECIMALS, f"{LEGEND_DECIMALS} must be a whole number from 0 to 8.")


def format_legend_value(value, mode, decimals=DEFAULT_DECIMALS):
    """Format a finite numeric colorbar tick for Fixed/Scientific mode, or return None for Automatic."""
    if mode == AUTO_FORMAT:
        return None
    if mode not in (FIXED_FORMAT, SCIENTIFIC_FORMAT):
        raise ValueError(f"Unsupported color legend number format: {mode!r}")
    if _is_bool(decimals) or not isinstance(decimals, Integral) or not MIN_DECIMALS <= decimals <= MAX_DECIMALS:
        raise ValueError(f"Color legend decimals must be a whole number from {MIN_DECIMALS} to {MAX_DECIMALS}.")
    if _is_bool(value) or not isinstance(value, Real):
        raise ValueError("Color legend tick value must be a finite real number.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("Color legend tick value must be finite.")
    text = format(numeric, f".{int(decimals)}{'f' if mode == FIXED_FORMAT else 'e'}")
    # Strip negative sign only when rounding turns a negative number into signed zero.
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def parse_legend_decimals(value):
    """Parse an integer precision in 0..8 from a real number or integral string (including decimal comma)."""
    if _is_bool(value):
        raise _decimals_error()
    if isinstance(value, Integral):
        number = int(value)
    elif isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise _decimals_error()
        number = int(numeric)
    elif isinstance(value, str):
        text = value.strip()
        if not text or "_" in text:
            raise _decimals_error()
        try:
            parsed = Decimal(decimal_comma(text))
        except InvalidOperation:
            raise _decimals_error() from None
        if not parsed.is_finite() or parsed != parsed.to_integral_value():
            raise _decimals_error()
        if not MIN_DECIMALS <= parsed <= MAX_DECIMALS:
            raise _decimals_error()
        return int(parsed)
    else:
        raise _decimals_error()
    if not MIN_DECIMALS <= number <= MAX_DECIMALS:
        raise _decimals_error()
    return number


def parse_legend_number_format(options):
    """Validate and return (mode, decimals) for an active numeric heat-map legend."""
    mode = options.get(NUMBER_FORMAT, AUTO_FORMAT)
    if not isinstance(mode, str) or mode not in NUMBER_FORMATS:
        raise FieldError(NUMBER_FORMAT, f"Choose a valid {NUMBER_FORMAT.lower()}.")
    if mode == AUTO_FORMAT:
        return AUTO_FORMAT, None
    return mode, parse_legend_decimals(options.get(LEGEND_DECIMALS, DEFAULT_DECIMALS))
