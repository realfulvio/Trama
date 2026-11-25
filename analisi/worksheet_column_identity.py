"""Stable worksheet column references for the presentation of a graph (the labels of its observations).

A graph style names a worksheet column by its name, which anyone can change or reuse. A column therefore has an
identity of its own, in the same spirit as the row identities of ``analisi.worksheet_row_identity``:

- a worksheet that was never edited gives its columns the positional identities ``base:1``, ``base:2``, …;
- the first structural edit (insert, rename, delete) writes the identities down (``COLUMN_IDS`` in the attributes
  of the worksheet frame) and from then on they follow the column: a rename keeps the identity, a deletion drops
  it, a new column gets a new one, so a column created later with a deleted column's name is another column;
- the identities are saved with the table and restored on opening, and an Undo that restores the old worksheet
  restores them too;
- a calculated column is ``formula:<name>`` and a column of a frame that did not come from a worksheet (the result
  of another analysis) is ``name:<name>``: neither can be edited as a source column.

Only the style of a graph reads them: nothing else about a worksheet depends on them.
"""
import re
from uuid import uuid4

COLUMN_IDS = "column_ids"
FORMULA = "formula:"
DERIVED = "name:"
_ORIGIN = r"(?:base|[a-f0-9]{32})"
_TOKEN = re.compile(_ORIGIN + r":[1-9][0-9]{0,9}")
MAX_ID = 1100


def valid_token(token):
    """A stored column identity: ``base:<n>`` or ``<32 hex>:<n>``."""
    return isinstance(token, str) and _TOKEN.fullmatch(token) is not None


def valid_reference(token):
    """An identity as a graph style stores it: a stored identity or a derived one."""
    return isinstance(token, str) and 0 < len(token) <= MAX_ID and (
        valid_token(token) or token.startswith((FORMULA, DERIVED)))


def saved_ids(ids, columns):
    """Validate identities read from a project file: known columns, well-formed and distinct."""
    problem = "Invalid worksheet column identities."
    if not isinstance(ids, dict) or len(ids) > len(columns):
        raise ValueError(problem)
    names = set(columns)
    for name, token in ids.items():
        if name not in names or not valid_token(token):
            raise ValueError(problem)
    if len(set(ids.values())) != len(ids):
        raise ValueError(problem)
    return dict(ids)


def kept_ids(ids, columns):
    """The identities to write for ``columns`` (those of columns that no longer exist are left out)."""
    names = set(columns)
    return {name: token for name, token in ids.items() if name in names and valid_token(token)}


def current_ids(frame, formulas=()):
    """``{column: identity}`` for every column of ``frame`` (and the calculated ``formulas`` after them)."""
    stored = frame.attrs.get(COLUMN_IDS)
    ids = {}
    for position, name in enumerate(frame.columns):
        if stored is None:
            ids[name] = f"base:{position + 1}"
        else:
            ids[name] = stored.get(name) or DERIVED + str(name)
    for name in formulas:
        ids.setdefault(name, FORMULA + str(name))
    return ids


def frame_ids(frame):
    """The identities of a frame handed to an analysis: the worksheet's, or by name for any other frame."""
    stored = frame.attrs.get(COLUMN_IDS)
    if stored is None:
        return {name: DERIVED + str(name) for name in frame.columns}
    return {name: stored.get(name) or DERIVED + str(name) for name in frame.columns}


def after_rename(raw, renames):
    """The identities after ``renames`` (``{old: new}``): every column keeps its own."""
    return {renames.get(name, name): token for name, token in current_ids(raw).items()}


def after_deletion(raw, names):
    names = set(names)
    return {name: token for name, token in current_ids(raw).items() if name not in names}


def after_insertion(raw, name):
    """The identities with one new column: it never takes the identity of a column that was deleted."""
    ids = dict(current_ids(raw))
    ids[name] = f"{uuid4().hex}:1"
    return ids


def store(frame, ids):
    """Write ``ids`` into the attributes of ``frame``, keeping only its columns."""
    names = set(frame.columns)
    kept = {name: token for name, token in ids.items() if name in names}
    if kept:
        frame.attrs[COLUMN_IDS] = kept
    else:
        frame.attrs.pop(COLUMN_IDS, None)
