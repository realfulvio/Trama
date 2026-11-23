"""Normalize saved Kaplan–Meier status codes without changing source values."""
from decimal import Decimal, InvalidOperation

from pandas.api.types import is_complex_dtype, is_float_dtype, is_numeric_dtype

from . import fdr_control
from .processing import FieldError


EVENT_CODE = "Event code"
CENSOR_CODE = "Censor code"
OTHER_STATUS = "Other status values"
STATUS_POLICIES = ("Report an error", "Treat as missing")
STATUS_DEFAULTS = {EVENT_CODE: "1", CENSOR_CODE: "0", OTHER_STATUS: STATUS_POLICIES[0]}

PAIRWISE_CORRECTION = "Pairwise correction"
PAIRWISE_SCOPE = "Pairwise scope"
PAIRWISE_CONTROL = "Pairwise control group"
PAIRWISE_PAIRS = "Selected survival pairs"
PAIRWISE_PAIR_LIST = "Survival pair list"
PAIRWISE_ADJUSTED = "Show adjusted pairwise p"
PAIRWISE_ALPHA = "Pairwise alpha"
PAIRWISE_FDR = fdr_control.LEVEL
ALL_PAIRS, CONTROL_PAIRS, SELECTED_PAIRS = PAIRWISE_SCOPES = ("All pairs", "Versus control", "Selected pairs")
UNADJUSTED = "Unadjusted"
PAIRWISE_METHODS = {"Holm": "holm", "Bonferroni": "bonferroni", "FDR": "fdr_bh",
                    "Holm–Šídák": "holm-sidak", "Šídák": "sidak"}
PAIRWISE_CORRECTIONS = ("None", *PAIRWISE_METHODS, *fdr_control.FDR_METHODS, UNADJUSTED)
PAIRWISE_FIELDS = (PAIRWISE_CORRECTION, PAIRWISE_SCOPE, PAIRWISE_CONTROL, PAIRWISE_PAIRS,
                   PAIRWISE_ADJUSTED, PAIRWISE_ALPHA, PAIRWISE_FDR)


def pairwise_corrections(saved):
    # The original FDR value keeps its pre-existing BH report. New analyses offer named FDR procedures.
    return tuple(value for value in PAIRWISE_CORRECTIONS if value != "FDR" or saved.get(PAIRWISE_CORRECTION) == "FDR")


def pairwise_scope(options):
    """Infer the comparison family of projects saved before scope was explicit."""
    return options.get(PAIRWISE_SCOPE, CONTROL_PAIRS if options.get(PAIRWISE_CONTROL) else ALL_PAIRS)


def pairwise_fields(correction, scope, adjusted):
    active = correction != "None"
    fdr = correction in fdr_control.FDR_METHODS
    return {PAIRWISE_SCOPE: active, PAIRWISE_CONTROL: active and scope == CONTROL_PAIRS,
            PAIRWISE_PAIRS: active and scope == SELECTED_PAIRS,
            PAIRWISE_ADJUSTED: active and not fdr and correction != UNADJUSTED,
            PAIRWISE_ALPHA: active and not fdr and (not adjusted or correction == UNADJUSTED),
            PAIRWISE_FDR: fdr}


def _code(value, field, numeric):
    if not isinstance(value, (str, int)) or not str(value).strip():
        raise FieldError(field, f"Enter a value for {field.lower()}.")
    if not numeric:
        return str(value)
    try:
        code = Decimal(str(value))
    except InvalidOperation:
        code = Decimal("NaN")
    if not code.is_finite() or not -(2**63) <= code < 2**63 or code != code.to_integral_value():
        raise FieldError(field, f"{field} must be a whole number for numeric status columns.")
    return int(code)


def recode_statuses(frame, columns, options):
    """Map event and censor statuses to 1 and 0, retaining gaps for each response."""
    if not columns or not STATUS_DEFAULTS.keys() & options.keys():
        return frame
    types = {is_numeric_dtype(frame[column].dtype) for column in columns}
    if len(types) > 1 or any(is_complex_dtype(frame[column].dtype) for column in columns):
        raise FieldError("Event columns", "Use status columns that are all numeric or all text.")
    numeric, = types
    event = _code(options.get(EVENT_CODE, "1"), EVENT_CODE, numeric)
    censor = _code(options.get(CENSOR_CODE, "0"), CENSOR_CODE, numeric)
    if event == censor:
        raise FieldError(CENSOR_CODE, "Event and censor codes must be different.")
    policy = options.get(OTHER_STATUS, STATUS_POLICIES[0])
    if policy not in STATUS_POLICIES:
        raise FieldError(OTHER_STATUS, "Choose how to handle undefined statuses.")
    coded = {}
    for column in columns:
        status = frame[column]
        values = status if numeric else status.astype("string")
        floating = is_float_dtype(values.dtype)
        if floating:
            values = values.astype("Float64")
        matches_event = values.eq(event).fillna(False)
        matches_censor = values.eq(censor).fillna(False)
        if floating:
            # A floating column cannot contain an integer rounded away by its dtype.
            if int(float(event)) != event:
                matches_event[:] = False
            if int(float(censor)) != censor:
                matches_censor[:] = False
        unknown = status.notna() & ~(matches_event | matches_censor)
        if policy == STATUS_POLICIES[0] and unknown.any():
            example = status[unknown].iloc[0]
            raise FieldError(OTHER_STATUS, f'{column} contains an undefined status {str(example)!r}.')
        coded[column] = matches_event.astype(float).where(matches_event | matches_censor)
    return frame.assign(**coded)
