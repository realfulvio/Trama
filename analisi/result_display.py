"""Display preferences for analysis result tables."""

from numbers import Integral

from .field_error import FieldError
from .i18n import tr
from .pairwise_graph import p_label
from .worksheet_number_format import (DIGIT_RANGES, FIXED, SIGNIFICANT, display_decimal_mark, formatter,
                                      number_value)


METHODS = frozenset(("Multifactor ANOVA", "t-test", "Paired t-test (columns)", "Nonlinear regression",
                     "Kaplan–Meier survival"))
DIGITS = "Result significant digits (0 = automatic)"
P_STYLE = "P-value display"
P_DECIMALS = "P-value decimal places"
AUTO, DECIMALS, STARS, VALUE_AND_STARS = STYLES = ("Automatic", "P-value decimals", "Significance stars",
                                                "P value and significance stars")
OPTIONS = {DIGITS: 0, P_STYLE: STYLES, P_DECIMALS: 4}
_P_COLUMNS = {"p", "Adjusted p", "Uncorrected p"}
_P_METRICS = _P_COLUMNS | {"Pairing p (positive association)"}


def canonical(options):
    """Keep only active presentation preferences, leaving old recipes unchanged."""
    digits = options.get(DIGITS, 0)
    if type(digits) is not int or not 0 <= digits <= DIGIT_RANGES[SIGNIFICANT][1]:
        raise FieldError(DIGITS, tr("analysis.output.significant_error"))
    style = options.get(P_STYLE, AUTO)
    if style not in STYLES:
        raise FieldError(P_STYLE, tr("analysis.output.style_error"))
    selected = {DIGITS: digits} if digits else {}
    if style != AUTO:
        selected[P_STYLE] = style
    if style == DECIMALS:
        decimals = options.get(P_DECIMALS, 4)
        if type(decimals) is not int or not 1 <= decimals <= DIGIT_RANGES[FIXED][1]:
            raise FieldError(P_DECIMALS, tr("analysis.output.decimals_error"))
        selected[P_DECIMALS] = decimals
    return selected


def renderer(method, options):
    """Compile the result-only renderer. Copy and data export still use the raw result table."""
    if method not in METHODS:
        return None
    try:
        settings = canonical(options)
    except FieldError:
        return None  # A malformed saved display preference must not hide valid result data.
    if not settings:
        return None
    mark = display_decimal_mark()
    significant = (formatter({"mode": SIGNIFICANT, "digits": settings[DIGITS]}, mark)
                   if DIGITS in settings else None)
    style = settings.get(P_STYLE, AUTO)
    decimals = settings.get(P_DECIMALS, 4)
    fixed = formatter({"mode": FIXED, "digits": decimals}, mark)
    minimum = 10. ** -decimals

    def format_cell(column, value, metric=None):
        if isinstance(metric, tuple) and metric:
            metric = metric[-1]
        probability = column in _P_COLUMNS or column == "Value" and isinstance(metric, str) and metric in _P_METRICS
        if not probability:
            # Counts and ordinal identifiers keep every digit, even in a mixed-value report.
            return significant(value) if significant is not None and not isinstance(value, Integral) else None
        if style == AUTO or (number := number_value(value)) is None or not 0 <= number <= 1:
            return None
        if style == STARS:
            return p_label(number, "stars")
        text = f"<{fixed(minimum)}" if number < minimum else fixed(number)
        return f'{text} ({p_label(number, "stars")})' if style == VALUE_AND_STARS else text

    return format_cell


def imported_output(output):
    """Translate display settings recognized in compatible saved analysis recipes."""
    if not isinstance(output, dict):
        return {}
    digits = output.get("significantDigitCount")
    settings = {DIGITS: digits} if type(digits) is int and 1 <= digits <= DIGIT_RANGES[SIGNIFICANT][1] else {}
    style = output.get("pValueStyle")
    if isinstance(style, dict) and style.get("type") == "P_VALUE_STYLE_GP":
        settings[P_STYLE] = VALUE_AND_STARS
    return settings
