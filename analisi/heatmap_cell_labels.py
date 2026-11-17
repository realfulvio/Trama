"""Validation and text formatting for heat-map cell value labels."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from numbers import Integral, Real

from matplotlib.colors import is_color_like

from .data import decimal_comma
from .field_error import FieldError

CELL_LABEL_NUMBER_FORMAT = "Cell label number format"
CELL_LABEL_DECIMALS = "Cell label decimals"
CELL_LABEL_FONT_SIZE = "Cell label font size"
CELL_LABEL_COLOR_MODE = "Cell label color mode"
CELL_LABEL_COLOR = "Cell label color"
CELL_LABEL_PREFIX = "Cell label prefix"
CELL_LABEL_SUFFIX = "Cell label suffix"

AUTO_FORMAT, FIXED_FORMAT, SCIENTIFIC_FORMAT = CELL_LABEL_NUMBER_FORMATS = (
    "Automatic",
    "Fixed",
    "Scientific",
)
AUTO_CONTRAST, CUSTOM_COLOR = CELL_LABEL_COLOR_MODES = ("Auto contrast", "Custom")

DEFAULT_DECIMALS = 2
MIN_DECIMALS = 0
MAX_DECIMALS = 8
MIN_FONT_SIZE = 6.0
MAX_FONT_SIZE = 36.0
DEFAULT_LABEL_COLOR = "#162633"
MAX_AFFIX_LENGTH = 80


@dataclass(frozen=True)
class CellLabelSettings:
    """Validated cell label settings for a single heat-map draw."""

    number_format: str = AUTO_FORMAT
    decimals: int | None = None
    font_size: float | None = None
    color_mode: str = AUTO_CONTRAST
    color: str | None = None
    prefix: str = ""
    suffix: str = ""


def _is_bool(value):
    return isinstance(value, bool) or (type(value).__name__ == "bool_" and type(value).__module__ == "numpy")


def _decimals_error():
    return FieldError(CELL_LABEL_DECIMALS, f"{CELL_LABEL_DECIMALS} must be a whole number from 0 to 8.")


def _font_size_error():
    return FieldError(CELL_LABEL_FONT_SIZE, f"{CELL_LABEL_FONT_SIZE} must be blank or a number from 6 to 36.")


def parse_cell_label_decimals(value):
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


def parse_cell_label_font_size(value):
    """Parse a finite font size in 6..36 pt, or return None for blank/legacy font."""
    if value is None:
        return None
    if _is_bool(value):
        raise _font_size_error()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if "_" in text:
            raise _font_size_error()
        try:
            number = float(decimal_comma(text))
        except (TypeError, ValueError, OverflowError):
            raise _font_size_error() from None
    elif isinstance(value, Real):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise _font_size_error() from None
    else:
        raise _font_size_error()
    if not math.isfinite(number) or not MIN_FONT_SIZE <= number <= MAX_FONT_SIZE:
        raise _font_size_error()
    return number


def parse_cell_label_color(value):
    """Validate a custom Matplotlib color string, falling back to default only when omitted/None."""
    if value is None:
        return DEFAULT_LABEL_COLOR
    if not isinstance(value, str):
        raise FieldError(CELL_LABEL_COLOR, "Choose a valid color name or hexadecimal color.")
    text = value.strip()
    if not text or not is_color_like(text):
        raise FieldError(CELL_LABEL_COLOR, "Choose a valid color name or hexadecimal color.")
    return text


def parse_cell_label_affix(value, field):
    """Validate a literal prefix/suffix string up to 80 characters."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FieldError(field, f"{field} must be text.")
    if len(value) > MAX_AFFIX_LENGTH:
        raise FieldError(field, f"{field} must be at most {MAX_AFFIX_LENGTH} characters.")
    return value


def parse_cell_label_options(options, *, categorical=False):
    """Validate and return active cell label settings for a heat map with Show cell values enabled."""
    if categorical:
        number_format = AUTO_FORMAT
        decimals = None
    else:
        number_format = options.get(CELL_LABEL_NUMBER_FORMAT, AUTO_FORMAT)
        if not isinstance(number_format, str) or number_format not in CELL_LABEL_NUMBER_FORMATS:
            raise FieldError(CELL_LABEL_NUMBER_FORMAT, f"Choose a valid {CELL_LABEL_NUMBER_FORMAT.lower()}.")
        decimals = (
            parse_cell_label_decimals(options.get(CELL_LABEL_DECIMALS, DEFAULT_DECIMALS))
            if number_format in (FIXED_FORMAT, SCIENTIFIC_FORMAT)
            else None
        )
    font_size = parse_cell_label_font_size(options.get(CELL_LABEL_FONT_SIZE))
    color_mode = options.get(CELL_LABEL_COLOR_MODE, AUTO_CONTRAST)
    if not isinstance(color_mode, str) or color_mode not in CELL_LABEL_COLOR_MODES:
        raise FieldError(CELL_LABEL_COLOR_MODE, f"Choose a valid {CELL_LABEL_COLOR_MODE.lower()}.")
    color = parse_cell_label_color(options.get(CELL_LABEL_COLOR)) if color_mode == CUSTOM_COLOR else None
    prefix = parse_cell_label_affix(options.get(CELL_LABEL_PREFIX), CELL_LABEL_PREFIX)
    suffix = parse_cell_label_affix(options.get(CELL_LABEL_SUFFIX), CELL_LABEL_SUFFIX)
    return CellLabelSettings(
        number_format=number_format,
        decimals=decimals,
        font_size=font_size,
        color_mode=color_mode,
        color=color,
        prefix=prefix,
        suffix=suffix,
    )


def format_cell_label(value, settings, *, categorical=False):
    """Format a single non-missing cell value using validated CellLabelSettings."""
    if value is None:
        return None
    if categorical:
        return f"{settings.prefix}{value}{settings.suffix}"
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    if settings.number_format == AUTO_FORMAT:
        text = f"{numeric:.4g}"
    else:
        spec = f".{int(settings.decimals)}{'f' if settings.number_format == FIXED_FORMAT else 'e'}"
        text = format(numeric, spec)
        # Remove negative sign only when Fixed/Scientific rounding produces signed zero.
        if text.startswith("-") and float(text) == 0:
            text = text[1:]
    return f"{settings.prefix}{text}{settings.suffix}"
