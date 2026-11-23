"""Recover binding analyses from a legacy XML project template."""

from struct import error as StructError, unpack

import numpy as np
from pandas import DataFrame
from pandas.api.types import is_numeric_dtype

from .legacy_binary import _records, _source_ids
from .legacy_binary_editable import _id_array, _one, _require, _subgroups
from .legacy_binary_results import _analysis_ids, _title
from .legacy_restore import LEGACY_NOTES, LEGACY_TITLE
from .reporting import Result
from .xy_series import _numbers

SCATCHARD = "Scatchard transformation"
_EQUATION = b"Y=Bmax*X/(Kd+X)"
_RESULT_HEADING = b"One site binding (hyperbola)Least squares fit"
_SCATCHARD_HEADING = b"Transform: Pharmacology and biochemistry transforms: Scatchard"
# The observed legacy least-squares profile uses two positive, fitted coefficients.
# Keep unfamiliar fit settings out of the native recipe.
_FIT_OPTIONS = (1, 0, 2, 0, 35, 16, 0, 9, 1, 1, 1, 1, -1, -1)


def indexed_analyses(data):
    """Read the original worksheet IDs and the indexed single-input analyses."""
    records = [(tag, parents[1:], payload) for tag, parents, payload in _records(data)
               if parents == (1,) or parents[:2] == (1, 57)]
    index = _one(records, 0x8002)
    sheets = set(_source_ids(index))
    analyses = {}
    for header, contents in _subgroups(records, 0x8039):
        if len(header) == 2:
            uid, = unpack("<H", header)
            analyses[uid] = None if uid in analyses else contents
    selected = []
    for uid in _analysis_ids(index) or ():
        contents = analyses.get(uid)
        if not contents:
            continue
        try:
            kind = unpack("<8H", _one(contents, 0x3A))
            source = _one(contents, 0x3B)
            if len(source) == 4:
                sheet, = unpack("<I", source)
                if sheet not in sheets:
                    continue
            else:
                sheet, = _id_array(source)
        except (ValueError, StructError):
            continue
        selected.append((uid, sheet, kind, contents))
    return sheets, selected


def restored_binding_recipes(analyses, sources):
    """Yield binding recipes and their original sheet identities."""
    for uid, sheet, kind, contents in analyses:
        frame, x, groups = sources[sheet]
        if len(groups) != 1 or len(groups[0][1]) != 1:
            continue
        try:
            if kind[:2] == (0, 5):
                method, options = "Nonlinear regression", _binding_options(contents, kind)
            elif kind[:2] == (3, 255):
                method, options = SCATCHARD, _scatchard_options(contents, kind)
            else:
                continue
        except (ValueError, StructError):
            continue
        y, = groups[0][1]
        if is_numeric_dtype(frame[x]) and is_numeric_dtype(frame[y]):
            yield uid, sheet, frame, method, {"X": x, "Y": y, **options}


def _summary(contents, heading):
    summary = _one(contents, 0xA)
    _require(len(summary) == 300 and summary[24:].tobytes().split(b"\0", 1)[0] == heading)
    selection = _one(contents, 0x3D)
    _require(unpack("<7H", selection) == (1, 1, 0, 65535, 65535, 65535, 65535))


def _binding_options(contents, kind):
    _summary(contents, _RESULT_HEADING)
    _require(kind[3:] == (1, 255, 1, 65535, 0))
    settings, = _subgroups(contents, 0x8047)
    _require(unpack("<4i4B6i", settings[0]) == _FIT_OPTIONS)
    formulae = list(_subgroups(settings[1], 0x8048))
    _require(1 <= len(formulae) <= 2)
    for header, records in formulae:
        _require(len(header) == 114 and bytes(_one(records, 0x49)).rstrip(b"\r\n\0") == _EQUATION)

    return {"Model": "One-site specific binding", "Weighting": "Unweighted",
            LEGACY_TITLE: _title(_one(contents, 9))[:160],
            LEGACY_NOTES: "Fit recovered from the original XY worksheet and the saved analysis settings."}


def _scatchard_options(contents, kind):
    _summary(contents, _SCATCHARD_HEADING)
    _require(kind[3:] == (1, 191, 0, 1, 0))
    _require(unpack("<11i", _one(contents, 0x3C)) == (10, 3) + (-1,) * 9)
    return {LEGACY_TITLE: _title(_one(contents, 9))[:160],
            LEGACY_NOTES: "Scatchard coordinates calculated from the original bound and free values."}


def scatchard(frame, options):
    """The plotted abscissa is bound; the ordinate is the bound/free ratio."""
    free, bound = (_numbers(frame, options[name]) for name in ("X", "Y"))
    valid = np.isfinite(free) & np.isfinite(bound) & (free != 0)
    with np.errstate(over="ignore", invalid="ignore"):
        ratio = np.divide(bound, free, out=np.full(len(frame), np.nan), where=valid)
    points = DataFrame({"Bound": np.where(np.isfinite(bound), bound, np.nan),
                        "Bound / free": np.where(np.isfinite(ratio), ratio, np.nan)})
    return Result({"Scatchard": points})
