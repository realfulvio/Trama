"""Recover a saved one-site binding recipe from an older XML project template."""

from struct import error as StructError, unpack

from pandas.api.types import is_numeric_dtype

from .prism_binary import _records, _source_ids
from .prism_binary_editable import _id_array, _one, _require, _subgroups
from .prism_binary_results import _analysis_ids, _title
from .prism_restore import PRISM_NOTES, PRISM_TITLE

_EQUATION = b"Y=Bmax*X/(Kd+X)"
_RESULT_HEADING = b"One site binding (hyperbola)Least squares fit"
# The observed legacy least-squares profile uses two positive, fitted coefficients.
# Keep unfamiliar fit settings out of the native recipe.
_FIT_OPTIONS = (1, 0, 2, 0, 35, 16, 0, 9, 1, 1, 1, 1, -1, -1)


def restored_binding_fits(data, sources):
    """Yield worksheet and recipe pairs whose analysis and source indexes agree."""
    single_series = {key: (frame, x, groups[0][1][0]) for key, (frame, x, groups) in sources.items()
                     if len(groups) == 1 and len(groups[0][1]) == 1}
    if not single_series:
        return
    records = [(tag, parents[1:], payload) for tag, parents, payload in _records(data)
               if parents == (1,) or parents[:2] == (1, 57)]
    index = _one(records, 0x8002)
    sheets = set(_source_ids(index))
    analyses = {}
    for header, contents in _subgroups(records, 0x8039):
        if len(header) == 2:
            uid, = unpack("<H", header)
            analyses[uid] = None if uid in analyses else contents
    for uid in _analysis_ids(index) or ():
        contents = analyses.get(uid)
        if not contents:
            continue
        try:
            sheet, = _id_array(_one(contents, 0x3B))
            if sheet not in sheets or sheet not in single_series:
                continue
            options = _binding_options(contents)
        except (ValueError, StructError):
            continue
        frame, x, y = single_series[sheet]
        if is_numeric_dtype(frame[x]) and is_numeric_dtype(frame[y]):
            yield frame, {"X": x, "Y": y, **options}


def _binding_options(contents):
    summary = _one(contents, 0xA)
    _require(len(summary) == 300 and summary[24:].tobytes().split(b"\0", 1)[0] == _RESULT_HEADING)
    kind = unpack("<8H", _one(contents, 0x3A))
    _require(kind[:2] == (0, 5) and kind[3:] == (1, 255, 1, 65535, 0))
    selection = _one(contents, 0x3D)
    _require(unpack("<7H", selection) == (1, 1, 0, 65535, 65535, 65535, 65535))
    settings, = _subgroups(contents, 0x8047)
    _require(unpack("<4i4B6i", settings[0]) == _FIT_OPTIONS)
    formulae = list(_subgroups(settings[1], 0x8048))
    _require(1 <= len(formulae) <= 2)
    for header, records in formulae:
        _require(len(header) == 114 and bytes(_one(records, 0x49)).rstrip(b"\r\n\0") == _EQUATION)

    return {"Model": "One-site specific binding", "Weighting": "Unweighted",
            PRISM_TITLE: _title(_one(contents, 9))[:160],
            PRISM_NOTES: "Fit recovered from the original XY worksheet and the saved analysis settings."}
