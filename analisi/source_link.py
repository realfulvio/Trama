"""Worksheets linked to the CSV or TSV file they were imported from (File → Update from file…).

A linked worksheet keeps the last confirmed copy of the file in its cells: a project opens and calculates offline,
and nothing changes until the person reads the file again and confirms. The link (``SourceLink``) stores:

* **where**: the absolute path and, after a save, the path relative to the project folder. Nothing else is ever
  searched for: a file with the same name in another folder is never taken. The absolute path comes first; the
  relative one is only offered (and must be confirmed) when the absolute one is gone;
* **how**: the delimiter actually used, the UTF-8 encoding, the header choice, the row range, the missing code and
  the exclusion mark of ``analisi.text_import``, and which file column fills which worksheet column: by header text
  (by position without a header) on the file side, by the stable column identity of
  ``analisi.worksheet_column_identity`` on the worksheet side, so renaming a worksheet column keeps the link;
* **identity**: an optional key column whose values identify a row across reorders and updates;
* **the last confirmed version**: the size and SHA-256 of the file and, for every file row, 8 bytes that digest
  its key and 8 bytes that digest its imported cells, with the worksheet row identities
  (``analisi.worksheet_row_identity``) those rows had at that moment. No copy of the values is kept twice.

``plan_update`` reads the file with the same options and compares three versions of each row: the confirmed digest
(*base*), the worksheet now (*project*) and the file now (*file*). A row changed only in the file is updated, a row
changed only in the project keeps its edit, a row changed in both is a **conflict** that needs a visible decision.
Rows are matched by key; without a key only when the identity can be proven (the confirmed rows are found again,
each exactly once, unchanged) or after an explicit replacement of every row. Problems (duplicate or empty keys,
missing headers, a column that changed type, a linked column deleted from the worksheet) block the update and say
why. ``arrange`` turns a plan and the decisions into the new row order; ``trama_qt.project`` applies it as one
worksheet edit, so excluded cells, backgrounds, text styles, row heights and the point styles and labels of graphs
follow their row, Undo restores data, order and link in one step, and the analyses recalculate once.

The file is only ever opened for reading. Paths are local files: a URL is refused.
"""
import base64
from dataclasses import asdict, dataclass, field, fields, replace
import hashlib
import os
from pathlib import Path
import re
import time
from uuid import uuid4

import numpy as np
import pandas as pd

from .text_import import (DECIMAL_MARKS, DELIMITERS, ImportCancelled, ImportOptions, TextImport, decode_text)
from .worksheet_column_identity import COLUMN_IDS, after_insertion as column_ids_after_insertion, current_ids
from .worksheet_column_identity import valid_token as valid_column_token
from .worksheet_row_identity import ROW_SPANS, RowSpans, current_spans, saved_spans

SOURCE_LINK = "source_link"
FORMAT = 1
ROW_BYTES = 16  # Key digest, then row digest: 8 bytes each, little endian.
MAX_PATH = 4096
MAX_SHOWN = 8  # Keys or lines named in one message.
CHUNK = 1 << 20
_DELIMITER_NAMES = {char: name for name, char in DELIMITERS.items() if char}
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+://")
_SHA = re.compile(r"[0-9a-f]{64}")
OPTION_FIELDS = tuple(item.name for item in fields(ImportOptions))

# States of a file row (``Plan.states``) and of a worksheet row that the file no longer has (``Plan.removed``).
ADDED, MODIFIED, UNCHANGED, LOCAL, CONFLICT, DELETED, DELETED_CONFLICT = range(7)
REMOVED, REMOVED_CONFLICT = 0, 1


class UpdateCancelled(Exception):
    """The person pressed Cancel while the file was read or compared: nothing changed."""


@dataclass(frozen=True)
class Message:
    """A text in English with its values; the interface translates ``template`` and then formats it."""
    template: str
    values: tuple = ()

    def text(self, translate=None):
        template = translate(self.template) if translate is not None else self.template
        return template.format(**dict(self.values))

    def __str__(self):
        return self.text()


def message(template, **values):
    return Message(template, tuple(values.items()))


@dataclass(frozen=True, eq=False)
class SourceLink:
    """Immutable: a worksheet change replaces it, so Undo snapshots share it and ``copy`` returns it."""
    path: str
    relative: str | None
    delimiter: str
    options: ImportOptions
    columns: tuple  # ((source, column identity), ...): source = header text, or 0-based position without one.
    key: object  # The source of the key column, or None.
    size: int
    sha256: str
    spans: RowSpans  # Row identities of the confirmed file rows, in file order.
    digests: bytes  # ROW_BYTES per confirmed file row.
    encoding: str = "utf-8"

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    @property
    def rows(self):
        return len(self.digests) // ROW_BYTES

    @property
    def name(self):
        return _path_name(self.path)

    def key_column(self, raw):
        """The worksheet name of the key column (None without a key or when it was deleted)."""
        if self.key is None:
            return None
        names = {token: name for name, token in current_ids(raw).items()}
        return next((names.get(token) for source, token in self.columns if source == self.key), None)

    def imported_names(self, raw):
        """Worksheet names of the imported columns that still exist, in link order."""
        names = {token: name for name, token in current_ids(raw).items()}
        return [names[token] for _, token in self.columns if token in names]

    def with_relative(self, folder):
        """The link with its path relative to ``folder`` (the project folder), or without one when the file is on
        another drive."""
        try:
            relative = Path(os.path.relpath(self.path, folder)).as_posix()
        except (ValueError, TypeError, OSError):
            relative = None
        return self if relative == self.relative else replace(self, relative=relative)


def _path_name(path):
    return re.split(r"[\\/]", str(path))[-1]


# == the record saved in a .alab project ==========================================================================
def link_record(link):
    record = {"format": FORMAT, "path": link.path, "encoding": link.encoding, "delimiter": link.delimiter,
              "options": asdict(link.options), "columns": [[source, token] for source, token in link.columns],
              "key": link.key, "file": {"size": link.size, "sha256": link.sha256},
              "rows": {"spans": [list(span) for span in link.spans],
                       "digests": base64.b64encode(link.digests).decode("ascii")}}
    if link.relative:
        record["relative"] = link.relative
    return record


def read_link_record(record):
    """Validate a saved link. A damaged record is refused, never guessed."""
    problem = "Invalid link to a source file."
    if not isinstance(record, dict) or record.get("format") != FORMAT:
        raise ValueError(problem)
    path, relative = record.get("path"), record.get("relative")
    if not _valid_path(path) or (relative is not None and not _valid_path(relative)):
        raise ValueError(problem)
    if record.get("encoding") != "utf-8" or record.get("delimiter") not in _DELIMITER_NAMES:
        raise ValueError(problem)
    options = read_options(record.get("options"))
    columns = record.get("columns")
    if not isinstance(columns, list) or not columns or len(columns) > 1100:
        raise ValueError(problem)
    pairs = []
    for item in columns:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(problem)
        source, token = item
        if not _valid_source(source) or not valid_column_token(token):
            raise ValueError(problem)
        pairs.append((source, token))
    if len({source for source, _ in pairs}) != len(pairs) or len({token for _, token in pairs}) != len(pairs):
        raise ValueError(problem)
    key = record.get("key")
    if key is not None and key not in {source for source, _ in pairs}:
        raise ValueError(problem)
    stamp, rows = record.get("file"), record.get("rows")
    if (not isinstance(stamp, dict) or type(stamp.get("size")) is not int or stamp["size"] < 0
            or not isinstance(stamp.get("sha256"), str) or not _SHA.fullmatch(stamp["sha256"])
            or not isinstance(rows, dict) or not isinstance(rows.get("digests"), str)):
        raise ValueError(problem)
    try:
        digests = base64.b64decode(rows["digests"].encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError(problem) from error
    if len(digests) % ROW_BYTES:
        raise ValueError(problem)
    spans = saved_spans(rows.get("spans"), len(digests) // ROW_BYTES)
    return SourceLink(path, relative, record["delimiter"], options, tuple(pairs), key, stamp["size"],
                      stamp["sha256"], spans, digests)


def read_options(record):
    problem = "Invalid link to a source file."
    if not isinstance(record, dict) or set(record) != set(OPTION_FIELDS):
        raise ValueError(problem)
    for name in ("first_row", "skip_rows", "first_column", "skip_columns"):
        if type(record[name]) is not int or record[name] < (0 if name.startswith("skip") else 1):
            raise ValueError(problem)
    for name in ("last_row", "last_column"):
        if record[name] is not None and (type(record[name]) is not int or record[name] < 1):
            raise ValueError(problem)
    if (type(record["header"]) is not bool or type(record["mark_excluded"]) is not bool
            or record["decimal"] not in DECIMAL_MARKS or not isinstance(record["missing_code"], str)
            or len(record["missing_code"]) > 200):
        raise ValueError(problem)
    return ImportOptions(**record)


def _valid_path(path):
    return isinstance(path, str) and 0 < len(path) <= MAX_PATH and "\x00" not in path and not _URL.match(path)


def _valid_source(source):
    if isinstance(source, str):
        return 0 < len(source) <= 1000
    return type(source) is int and 0 <= source < 1_000_000


# == locating and reading the file =================================================================================
def locate(link, project_path):
    """``(path, found_elsewhere)``: the saved absolute path when it exists; otherwise the saved relative path from
    the folder of ``project_path`` (which the person must confirm); otherwise ``(None, False)``. Never searches."""
    absolute = Path(link.path)
    if absolute.is_file():
        return absolute, False
    if link.relative and project_path is not None:
        candidate = Path(project_path).parent / link.relative
        if candidate.is_file():
            return candidate.resolve(), True
    return None, False


def local_path(path):
    """Refuse anything but a local file name (a URL is never opened)."""
    text = str(path)
    if not _valid_path(text):
        raise ValueError("Choose a file on this computer or on a network folder.")
    return Path(text)


@dataclass(frozen=True)
class SourceFile:
    path: Path
    size: int
    mtime_ns: int
    sha256: str
    content: str

    @property
    def stamp(self):
        return self.size, self.mtime_ns


def stamp_of(path):
    status = os.stat(path)
    return status.st_size, status.st_mtime_ns


def read_file(path, *, cancel=None, progress=None, attempts=3):
    """Read the file for reading only and digest it. A file whose size or modification time moves during the read
    is read again (a network folder can settle the time of a file just copied there); one that keeps changing is
    refused."""
    path = local_path(path)
    for attempt in range(attempts):
        source = _read_once(path, cancel, progress)
        if source is not None:
            return source
        for _ in range(5):  # A short pause before reading again, still answering Cancel.
            if cancel is not None and cancel():
                raise UpdateCancelled
            time.sleep(0.05 * (attempt + 1))
    raise ValueError("The file changed while it was being read. Try again when it is complete.")


def _read_once(path, cancel, progress):
    from .data import MAX_ENTRY

    try:
        before = os.stat(path)
    except FileNotFoundError as error:
        raise ValueError(str(message("The linked file was not found: {path}", path=str(path)))) from error
    if before.st_size > MAX_ENTRY:
        raise ValueError("Input file exceeds 32 MiB.")
    digest, pieces, done = hashlib.sha256(), [], 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            if cancel is not None and cancel():
                raise UpdateCancelled
            digest.update(chunk)
            pieces.append(chunk)
            done += len(chunk)
            if done > MAX_ENTRY:
                raise ValueError("Input file exceeds 32 MiB.")
            if progress is not None:
                progress(done, max(done, before.st_size))
    after = os.stat(path)
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns) or done != after.st_size:
        return None
    return SourceFile(path, after.st_size, after.st_mtime_ns, digest.hexdigest(), decode_text(b"".join(pieces)))


def same_file(path, stamp, sha256):
    """True when ``path`` is still the file read: same size and time, or (a network folder may report another time
    for the same bytes) the same SHA-256."""
    try:
        if stamp_of(path) == stamp:
            return True
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
        return digest.hexdigest() == sha256
    except OSError:
        return False


# == digests ======================================================================================================
def _kind(series):
    if not series.notna().any():
        return "empty"
    if pd.api.types.is_bool_dtype(series):
        return "logical"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    return "text"


def canonical(series):
    """Python values equal exactly when two cells hold the same value: None, a float (an integer beyond 2**53
    stays an integer) or a string. Integer and decimal columns of the same numbers give the same values."""
    missing = series.isna().to_numpy(dtype=bool)
    if pd.api.types.is_bool_dtype(series):
        values = ["TRUE" if value else "FALSE" for value in series.astype(object).tolist()]
    elif pd.api.types.is_numeric_dtype(series):
        if (pd.api.types.is_integer_dtype(series) and not missing.all()
                and series.dropna().abs().max() > 2 ** 53):
            values = [int(value) for value in series.astype(object).where(~missing, 0).tolist()]
        else:
            values = series.astype("Float64").to_numpy(dtype="float64", na_value=np.nan).tolist()
    else:
        values = [str(value) for value in series.astype(object).where(~missing, "").tolist()]
    if missing.any():
        for row in np.flatnonzero(missing).tolist():
            values[row] = None
    return values


def _blake(data):
    return hashlib.blake2b(data, digest_size=8).digest()


def digests(columns, key=None, flags=None, *, cancel=None):
    """``(keys, rows)``: two little-endian uint64 arrays, one digest per row. ``columns`` are canonical value lists
    of the imported columns in link order, ``key`` the canonical key values (None: zero), ``flags`` an optional
    list of excluded-cell masks per row (the exclusion mark of the file is part of the row)."""
    count = len(columns[0]) if columns else 0
    rows = []
    source = zip(*columns, flags) if flags is not None else zip(*columns)
    for index, values in enumerate(source):
        if cancel is not None and not index % 4096 and cancel():
            raise UpdateCancelled
        rows.append(_blake(repr(values).encode("utf-8", "surrogatepass")))
    row_array = np.frombuffer(b"".join(rows), dtype="<u8") if rows else np.zeros(0, dtype="<u8")
    if key is None:
        key_array = np.zeros(count, dtype="<u8")
    else:
        key_array = np.frombuffer(b"".join(_blake(repr((value,)).encode("utf-8", "surrogatepass"))
                                           for value in key), dtype="<u8") if count else np.zeros(0, dtype="<u8")
    return key_array.astype(np.uint64), row_array.astype(np.uint64)


def pack(keys, rows):
    both = np.empty((len(rows), 2), dtype="<u8")
    both[:, 0], both[:, 1] = keys, rows
    return both.tobytes()


def unpack(data):
    both = np.frombuffer(data, dtype="<u8").reshape(-1, 2)
    return both[:, 0].astype(np.uint64), both[:, 1].astype(np.uint64)


def _flags(excluded, positions, count):
    """Per row, the tuple of imported-column indices (link order) whose cell is excluded."""
    marks = [()] * count
    found = {}
    for row, column in excluded:
        if column in positions and 0 <= row < count:
            found.setdefault(row, []).append(positions[column])
    for row, columns in found.items():
        marks[row] = tuple(sorted(columns))
    return marks


# == creating a link at import ======================================================================================
@dataclass(frozen=True)
class LinkSpec:
    """What the import dialog chose: enough to create the link once the worksheet exists."""
    path: Path
    size: int
    sha256: str
    delimiter: str
    options: ImportOptions
    sources: tuple  # File column of each imported worksheet column, in worksheet order.
    key: object = None  # The source of the key column, or None.


def column_sources(text_import, options, positions):
    """How each chosen file column is found again: its header text when it has one that is unique in the header,
    otherwise its position."""
    header = [name.strip() for name in text_import.records[0]] if options.header and text_import.records else []
    counts = {}
    for name in header:
        counts[name] = counts.get(name, 0) + 1
    return tuple(header[position] if position < len(header) and header[position] and counts[header[position]] == 1
                 else position for position in positions)


def key_problem(frame, name):
    """Why the column ``name`` of ``frame`` cannot identify its rows (empty or repeated values), or None."""
    if name is None:
        return None
    values = canonical(frame[name])
    empty = [str(row + 1) for row, value in enumerate(values) if value is None or value == ""]
    if empty:
        return message("The key column {name} is empty in row(s) {rows}.", name=name,
                       rows=_shown(empty))
    seen, repeated = set(), []
    for row, value in enumerate(values):
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    if repeated:
        return message("The key column {name} repeats {keys}.", name=name,
                       keys=_shown([_display(value) for value in repeated]))
    return None


def new_link(spec, raw, excluded=frozenset()):
    """The link of a worksheet just imported from ``spec.path``: its rows are the confirmed version."""
    names = list(raw.columns)
    if len(names) != len(spec.sources):
        raise ValueError("The imported columns do not match the file.")
    ids = current_ids(raw)
    columns = tuple((source, ids[name]) for source, name in zip(spec.sources, names))
    key_name = names[spec.sources.index(spec.key)] if spec.key is not None else None
    if (problem := key_problem(raw, key_name)) is not None:
        raise ValueError(str(problem))
    values = [canonical(raw[name]) for name in names]
    flags = (_flags(excluded, {index: index for index in range(len(names))}, len(raw))
             if spec.options.mark_excluded else None)
    keys, rows = digests(values, canonical(raw[key_name]) if key_name is not None else None, flags)
    return SourceLink(str(Path(spec.path).absolute()), None, spec.delimiter, spec.options, columns, spec.key,
                      spec.size, spec.sha256, current_spans(raw), pack(keys, rows))


# == planning an update =============================================================================================
@dataclass(frozen=True)
class Relink:
    """Read another file (or the same one with other options) into an existing worksheet: Change source…"""
    delimiter: str
    options: ImportOptions
    sources: tuple
    names: tuple  # The names the import gives these columns (matched to worksheet columns by name).
    key: object = None


@dataclass
class Plan:
    """What reading the file again would change. Built on the worker; ``arrange`` applies the decisions."""
    path: Path
    found_elsewhere: bool
    located: bool
    stamp: tuple
    size: int
    sha256: str
    link: SourceLink | None  # The link the plan was made from (None when a worksheet is linked for the first time).
    raw: pd.DataFrame  # The worksheet frame the plan was made from: applying checks it is still the same object.
    relink: Relink | None
    delimiter: str
    options: ImportOptions
    names: list  # Worksheet names of the imported columns, in link order.
    sources: tuple
    tokens: tuple  # Worksheet column identities of ``names`` (new ones for columns added by Change source…).
    new_columns: list  # Names of the file columns that Change source… adds at the right of the worksheet.
    key_name: str | None
    key_source: object
    frame: pd.DataFrame | None  # The file rows, imported columns renamed to the worksheet names.
    excluded_marks: list  # File (row, link column) cells marked excluded with a trailing *.
    source_keys: np.ndarray
    source_rows: np.ndarray
    states: np.ndarray  # One state per file row.
    match: np.ndarray  # Worksheet row of each file row, -1 for none.
    base_tokens: list  # Confirmed (origin, ordinal) of each file row deleted from the worksheet, else None.
    removed: list  # (worksheet row, REMOVED | REMOVED_CONFLICT) for confirmed rows the file no longer has.
    project_rows: list  # Worksheet rows that were never in the file: they stay, at the bottom.
    problems: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    identity_problem: Message | None = None  # Without a key: rows cannot be matched one by one.

    @property
    def keyed(self):
        return self.key_source is not None

    @property
    def blocked(self):
        return bool(self.problems)

    def count(self, state):
        return int(np.count_nonzero(self.states == state))

    @property
    def conflicts(self):
        return (self.count(CONFLICT) + self.count(DELETED_CONFLICT)
                + sum(1 for _, kind in self.removed if kind == REMOVED_CONFLICT))

    @property
    def unchanged_file(self):
        return self.link is not None and self.sha256 == self.link.sha256

    def reordered(self):
        """True when the file rows that stay are not in the order they have in the worksheet."""
        kept = self.match[self.match >= 0]
        return bool(len(kept) > 1 and np.any(np.diff(kept) < 0))

    def moved(self):
        """File rows that change place among the rows that stay: the fewest rows whose move explains the new
        order (those outside a longest run of rows already in order)."""
        rows = np.flatnonzero(self.match >= 0)
        return set(rows.tolist()) - set(rows[_longest_increasing(self.match[rows])].tolist())


def _longest_increasing(values):
    """Indices of one longest strictly increasing subsequence of ``values`` (patience sorting, O(n log n))."""
    from bisect import bisect_left

    tails, tail_index, previous = [], [], [-1] * len(values)
    for index, value in enumerate(values.tolist()):
        at = bisect_left(tails, value)
        if at == len(tails):
            tails.append(value), tail_index.append(index)
        else:
            tails[at], tail_index[at] = value, index
        previous[index] = tail_index[at - 1] if at else -1
    chain, index = [], tail_index[-1] if tail_index else -1
    while index >= 0:
        chain.append(index)
        index = previous[index]
    return np.array(chain[::-1], dtype=np.int64)


def _shown(items):
    items = list(items)
    text = ", ".join(items[:MAX_SHOWN])
    return text + (f", … (+{len(items) - MAX_SHOWN})" if len(items) > MAX_SHOWN else "")


def _display(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return str(int(value))
    return str(value)


def _token_arrays(spans):
    """``(origins, origin index per row, ordinal per row)`` of contiguous identity spans."""
    origins, index, ordinal = [], [], []
    lookup = {}
    for origin, first, count in spans:
        number = lookup.setdefault(origin, len(origins))
        if number == len(origins):
            origins.append(origin)
        index.append(np.full(count, number, dtype=np.int64))
        ordinal.append(np.arange(first, first + count, dtype=np.int64))
    if not index:
        return origins, np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    return origins, np.concatenate(index), np.concatenate(ordinal)


def _positions_of(base_spans, sheet_spans):
    """Current worksheet row of each confirmed row (-1 when the row was deleted from the worksheet)."""
    base_origins, base_index, base_ordinal = _token_arrays(base_spans)
    sheet_origins, sheet_index, sheet_ordinal = _token_arrays(sheet_spans)
    where = {}
    for row, (number, ordinal) in enumerate(zip(sheet_index.tolist(), sheet_ordinal.tolist())):
        where[(sheet_origins[number], ordinal)] = row
    return np.array([where.get((base_origins[number], ordinal), -1)
                     for number, ordinal in zip(base_index.tolist(), base_ordinal.tolist())], dtype=np.int64)


def _source_columns(text_import, options, sources):
    """File positions of the linked columns, or the problems that prevent finding them."""
    problems, positions = [], []
    header = [name.strip() for name in text_import.records[0]] if options.header and text_import.records else []
    for source in sources:
        if isinstance(source, int):
            if source >= text_import.width:
                problems.append(message("The file has only {count} columns: column {position} is missing.",
                                        count=text_import.width, position=source + 1))
            positions.append(source)
            continue
        found = [position for position, name in enumerate(header) if name == source]
        if not found:
            problems.append(message("The file no longer has the column {name}.", name=source))
        elif len(found) > 1:
            problems.append(message("The file has the column {name} more than once.", name=source))
        positions.append(found[0] if found else -1)
    return positions, problems


def plan_update(link, raw, excluded, path, *, project_rows_allowed=True, relink=None, found_elsewhere=False,
                located=False, cancel=None, progress=None):
    """Read ``path`` and compare it with the worksheet ``raw`` (its exclusions ``excluded``). ``relink`` reads
    with new options (Change source…, or linking a worksheet for the first time when ``link`` is None).

    Raises ``UpdateCancelled`` when ``cancel()`` turns true and ``ValueError`` when the file cannot be read;
    every other difficulty is a problem of the returned plan."""
    stop = cancel if cancel is not None else (lambda: False)

    def report(step):
        if progress is not None:
            progress(step, 100)

    source = read_file(path, cancel=stop,
                       progress=None if progress is None else lambda done, total: report(int(30 * done / total)))
    report(30)
    delimiter = relink.delimiter if relink is not None else link.delimiter
    options = relink.options if relink is not None else link.options
    try:
        text = TextImport.parse(source.content, Path(path).suffix.lower(), _DELIMITER_NAMES[delimiter], cancel=stop)
        text.plan(options)  # Refuses a row or column range the file no longer has.
    except ImportCancelled as error:
        raise UpdateCancelled from error
    report(45)
    problems, notices = [], []
    sheet_ids = current_ids(raw)
    by_token = {token: name for name, token in sheet_ids.items()}
    new_columns = []
    if relink is None:
        sources = tuple(source_name for source_name, _ in link.columns)
        tokens = tuple(token for _, token in link.columns)
        names = []
        for source_name, token in link.columns:
            name = by_token.get(token)
            if name is None:
                problems.append(message("The imported column {name} is no longer in the worksheet.",
                                        name=source_name if isinstance(source_name, str)
                                        else f"#{source_name + 1}"))
            names.append(name)
        key_source = link.key
    else:
        sources, key_source = relink.sources, relink.key
        names, tokens = [], []
        fresh = column_ids_after_insertion(raw, *[name for name in relink.names if name not in raw.columns])
        for name in relink.names:
            if name in raw.columns:
                names.append(name)
                tokens.append(sheet_ids[name])
            elif name in sheet_ids:  # A calculated column has this name.
                problems.append(message("The worksheet column {name} is calculated: it cannot receive the file.",
                                        name=name))
                names.append(None)
                tokens.append(None)
            else:
                names.append(name)
                tokens.append(fresh[name])
                new_columns.append(name)
        tokens = tuple(tokens)
    positions, column_problems = _source_columns(text, options, sources)
    problems.extend(column_problems)
    if options.header and text.records:
        linked = {source_name for source_name in sources if isinstance(source_name, str)}
        extra = [name.strip() for position, name in enumerate(text.records[0])
                 if name.strip() and name.strip() not in linked and position not in sources]
        if extra and relink is None:
            notices.append(message("The file has columns that are not linked: {names}. Change source… reads them.",
                                   names=_shown(extra)))
    key_name = names[sources.index(key_source)] if key_source is not None and key_source in sources else None
    plan = Plan(Path(path), found_elsewhere, located, source.stamp, source.size, source.sha256, link, raw, relink,
                delimiter, options, names, sources, tokens, new_columns, key_name, key_source, None, [],
                np.zeros(0, np.uint64), np.zeros(0, np.uint64), np.zeros(0, np.int64), np.zeros(0, np.int64), [], [],
                [], problems, notices)
    if problems:
        return plan
    try:
        frame = text.table(options, columns=positions, cancel=stop)
    except ImportCancelled as error:
        raise UpdateCancelled from error
    frame.columns = names
    marks = frame.attrs.pop("excluded", [])
    report(60)
    for name in names:
        if name in new_columns:
            continue
        local, incoming = _kind(raw[name]), _kind(frame[name])
        if "empty" in (local, incoming) or local == incoming:
            continue
        if incoming == "text":
            values = frame[name]
            numeric = pd.to_numeric(values, errors="coerce")
            line = int(np.flatnonzero(values.notna().to_numpy() & numeric.isna().to_numpy())[0])
            problems.append(message("The column {name} now holds text in the file (row {row}: {value}).",
                                    name=name, row=line + 1, value=str(values.iloc[line])))
        else:
            problems.append(message("The column {name} holds {local} values in the worksheet and {incoming} values "
                                    "in the file.", name=name, local=local, incoming=incoming))
    if key_name is not None and (problem := key_problem(frame, key_name)) is not None:
        problems.append(problem)
    if problems:
        return plan
    count = len(frame)
    link_positions = {}
    raw_index = {name: position for position, name in enumerate(raw.columns)}
    for order, name in enumerate(names):
        if name in raw_index:
            link_positions[raw_index[name]] = order
    file_flags = _flags(marks, {index: index for index in range(len(names))}, count) if options.mark_excluded else None
    source_keys, source_rows = digests([canonical(frame[name]) for name in names],
                                       canonical(frame[key_name]) if key_name is not None else None, file_flags,
                                       cancel=stop)
    report(75)
    existing = [name for name in names if name not in new_columns]
    local_flags = _flags(excluded, {position: order for position, order in link_positions.items()}, len(raw)) \
        if options.mark_excluded else None
    if relink is not None and new_columns:
        # Columns that Change source… adds are compared on the columns the worksheet already has.
        compare = [names.index(name) for name in existing]
        source_keys, source_rows = digests([canonical(frame[names[index]]) for index in compare],
                                           canonical(frame[key_name]) if key_name is not None else None,
                                           None if file_flags is None else
                                           [tuple(mark for mark in row if mark in compare) for row in file_flags],
                                           cancel=stop)
    local_keys, local_rows = digests([canonical(raw[name]) for name in existing] if existing else
                                     [[None] * len(raw)],
                                     canonical(raw[key_name]) if key_name is not None and key_name in raw else None,
                                     local_flags, cancel=stop)
    if not existing:
        local_rows = np.zeros(len(raw), dtype=np.uint64)
    report(90)
    plan.frame = frame
    plan.excluded_marks = list(marks)
    plan.source_keys, plan.source_rows = source_keys, source_rows
    sheet_spans = current_spans(raw)
    if link is not None and relink is None:
        base_keys, base_rows = unpack(link.digests)
        base_positions = _positions_of(link.spans, sheet_spans)
        base_origins, base_index, base_ordinal = _token_arrays(link.spans)
        base_tokens = [(base_origins[number], ordinal) for number, ordinal in zip(base_index.tolist(),
                                                                                  base_ordinal.tolist())]
    else:  # First link, or Change source…: the worksheet as it is now stands for the confirmed version.
        base_keys, base_rows = local_keys, local_rows
        base_positions = np.arange(len(raw), dtype=np.int64)
        base_tokens = [None] * len(raw)
    based = np.zeros(len(raw), dtype=bool)
    based[base_positions[base_positions >= 0]] = True
    if key_name is not None:
        _match_by_key(plan, raw, local_keys, local_rows, base_keys, base_rows, base_positions, base_tokens, based,
                      project_rows_allowed)
    else:
        _match_by_content(plan, local_rows, base_rows, base_positions, base_tokens, based)
    if plan.reordered():
        notices.append(message("The rows take the order of the file."))
    if plan.project_rows:
        notices.append(message("{count} row(s) added in the project stay at the bottom of the worksheet.",
                               count=len(plan.project_rows)))
    deleted = plan.count(DELETED)
    if deleted:
        notices.append(message("{count} row(s) deleted in the project stay deleted.", count=deleted))
    if new_columns:
        notices.append(message("New columns from the file: {names}.", names=_shown(new_columns)))
    if relink is not None:
        dropped = [name for name in (link.imported_names(raw) if link is not None else ())
                   if name not in names]
        if dropped:
            notices.append(message("These columns are no longer read from the file and stay as project columns: "
                                   "{names}.", names=_shown(dropped)))
    report(100)
    return plan


def _match_by_key(plan, raw, local_keys, local_rows, base_keys, base_rows, base_positions, base_tokens, based,
                  project_rows_allowed):
    candidates = {}
    for index, (key, position) in enumerate(zip(base_keys.tolist(), base_positions.tolist())):
        candidates.setdefault(key, []).append(("base", index, position))
    key_values = canonical(raw[plan.key_name]) if plan.key_name in raw else [None] * len(raw)
    for position in np.flatnonzero(~based).tolist():
        if key_values[position] not in (None, ""):
            candidates.setdefault(int(local_keys[position]), []).append(("sheet", None, position))
    count = len(plan.source_rows)
    states = np.full(count, ADDED, dtype=np.int64)
    match = np.full(count, -1, dtype=np.int64)
    tokens = [None] * count
    used = set()
    repeated = []
    source_key_values = canonical(plan.frame[plan.key_name])
    for row, (key, digest) in enumerate(zip(plan.source_keys.tolist(), plan.source_rows.tolist())):
        found = candidates.get(key, [])
        if len(found) > 1:
            rows = [str(position + 1) for _, _, position in found if position >= 0]
            repeated.append(message("The key {key} is in more than one row of the worksheet (rows {rows}).",
                                    key=_display(source_key_values[row]), rows=_shown(rows) or "-"))
            continue
        if not found:
            continue
        kind, index, position = found[0]
        used.add((kind, index, position))
        base = int(base_rows[index]) if kind == "base" else int(local_rows[position])
        if position < 0:  # Confirmed, then deleted in the project.
            states[row] = DELETED if digest == base else DELETED_CONFLICT
            tokens[row] = base_tokens[index]
            continue
        local = int(local_rows[position])
        match[row] = position
        if digest == local:
            states[row] = UNCHANGED
        elif local == base:
            states[row] = MODIFIED
        elif digest == base:
            states[row] = LOCAL
        else:
            states[row] = CONFLICT
    plan.problems.extend(repeated)
    plan.states, plan.match, plan.base_tokens = states, match, tokens
    removed = []
    for index, position in enumerate(base_positions.tolist()):
        if position >= 0 and ("base", index, position) not in used:
            removed.append((position, REMOVED if int(local_rows[position]) == int(base_rows[index])
                            else REMOVED_CONFLICT))
    plan.removed = sorted(removed)
    plan.project_rows = [position for position in np.flatnonzero(~based).tolist()
                         if ("sheet", None, position) not in used]
    if plan.link is None or plan.relink is not None:
        # Change source…: every row of the worksheet stood for the file. Rows without a match are removed.
        plan.removed = sorted(plan.removed + [(position, REMOVED) for position in plan.project_rows])
        plan.project_rows = []


def _match_by_content(plan, local_rows, base_rows, base_positions, base_tokens, based):
    count = len(plan.source_rows)
    states = np.full(count, ADDED, dtype=np.int64)
    match = np.full(count, -1, dtype=np.int64)
    tokens = [None] * count
    base_count = len(base_rows)
    pairs = None
    if base_count <= count and np.array_equal(plan.source_rows[:base_count], base_rows):
        pairs = list(zip(range(base_count), range(base_count)))  # The file only grew at the bottom.
    else:
        values, counts = np.unique(plan.source_rows, return_counts=True)
        once = dict(zip(values.tolist(), counts.tolist()))
        base_values = base_rows.tolist()
        if len(set(base_values)) == base_count and all(once.get(value) == 1 for value in base_values):
            where = {value: row for row, value in enumerate(plan.source_rows.tolist())}
            pairs = [(index, where[value]) for index, value in enumerate(base_values)]
    if pairs is None:
        plan.identity_problem = message(
            "Without a key column the rows of the file cannot be matched one by one with the worksheet (rows were "
            "changed or removed in the file). Choose a key with Change source…, or replace all rows.")
        plan.states, plan.match, plan.base_tokens = states, match, tokens
        plan.removed = [(position, REMOVED) for position in base_positions.tolist() if position >= 0]
        plan.project_rows = [position for position in np.flatnonzero(~based).tolist()]
        return
    for index, row in pairs:
        position = int(base_positions[index])
        if position < 0:
            states[row], tokens[row] = DELETED, base_tokens[index]
            continue
        match[row] = position
        states[row] = UNCHANGED if int(local_rows[position]) == int(plan.source_rows[row]) else LOCAL
    plan.states, plan.match, plan.base_tokens = states, match, tokens
    plan.removed = []
    plan.project_rows = [position for position in np.flatnonzero(~based).tolist()]


def can_apply(plan, *, choice=None, replace_rows=False):
    """None when ``arrange`` may run with these decisions, else the message that says what is missing."""
    if plan.problems:
        return plan.problems[0]
    if plan.identity_problem is not None and not replace_rows:
        return plan.identity_problem
    if plan.conflicts and choice not in ("project", "file") and not replace_rows:
        return message("Choose how to treat the rows changed both in the project and in the file.")
    return None


# == applying =======================================================================================================
@dataclass(frozen=True)
class Arrangement:
    order: np.ndarray  # Previous worksheet row of each new row, -1 for a new row.
    take: np.ndarray  # File row whose imported cells the new row receives, -1 to keep the worksheet's cells.
    host: np.ndarray  # File row each new row stands for (-1: a project row).
    tokens: list  # (origin, ordinal) for a new row that takes back a confirmed identity, else None.
    removed: list  # Previous worksheet rows that disappear.

    def mapping(self):
        return {int(old): new for new, old in enumerate(self.order.tolist()) if old >= 0}

    def changes_data(self, previous_length):
        return (len(self.order) != previous_length or np.any(self.take >= 0)
                or not np.array_equal(self.order, np.arange(previous_length)))


def arrange(plan, *, choice=None, replace_rows=False):
    """The new rows, in order: the file rows first, in file order, then the rows kept from the project."""
    if (problem := can_apply(plan, choice=choice, replace_rows=replace_rows)) is not None:
        raise ValueError(str(problem))
    order, take, host, tokens = [], [], [], []
    removed = set()
    if replace_rows:
        for row in range(len(plan.source_rows)):
            order.append(-1), take.append(row), host.append(row), tokens.append(None)
        removed = {position for position, _ in plan.removed} | {int(position) for position in plan.match
                                                               if position >= 0}
        kept = [position for position in plan.project_rows]
    else:
        use_file = choice == "file"
        for row, state in enumerate(plan.states.tolist()):
            position = int(plan.match[row])
            if state == ADDED:
                order.append(-1), take.append(row), host.append(row), tokens.append(None)
            elif state == MODIFIED or (state == CONFLICT and use_file):
                order.append(position), take.append(row), host.append(row), tokens.append(None)
            elif state in (UNCHANGED, LOCAL, CONFLICT):
                order.append(position), take.append(-1), host.append(row), tokens.append(None)
            elif state == DELETED_CONFLICT and use_file:
                order.append(-1), take.append(row), host.append(row), tokens.append(plan.base_tokens[row])
        kept = []
        for position, kind in plan.removed:
            if kind == REMOVED_CONFLICT and not use_file:
                kept.append(position)
            else:
                removed.add(position)
        kept += plan.project_rows
    for position in kept:
        order.append(position), take.append(-1), host.append(-1), tokens.append(None)
    return Arrangement(np.array(order, dtype=np.int64), np.array(take, dtype=np.int64),
                       np.array(host, dtype=np.int64), tokens, sorted(removed))


def _merged_dtype(local, incoming):
    local_kind, incoming_kind = _kind(local), _kind(incoming)
    if local_kind == "empty" and incoming_kind != "empty":
        return incoming.dtype
    if incoming_kind == "empty" or local_kind == "logical":
        return local.dtype
    if local_kind == "numeric":
        if pd.api.types.is_integer_dtype(local) and pd.api.types.is_integer_dtype(incoming):
            return "Int64"
        return "Float64"
    return local.dtype if local.dtype == object else "string"


def _nullable(column):
    """A numpy integer or logical column cannot hold a blank: as in ``grid_data.grow_rows``."""
    if isinstance(column.dtype, np.dtype) and column.dtype.kind in "iub":
        return column.convert_dtypes()
    return column


def build_frame(plan, arrangement):
    """The new worksheet frame: imported cells from the file where ``take`` says so, the others moved with their
    row; project columns keep their cells; new rows have them blank."""
    raw, frame = plan.raw, plan.frame
    order, take, host = arrangement.order, arrangement.take, arrangement.host
    taken = take >= 0
    columns = {}
    imported = {name for name in plan.names if name is not None}
    for name in raw.columns:
        column = _nullable(raw[name]) if (order < 0).any() else raw[name]
        if name in imported:
            dtype = _merged_dtype(raw[name], frame[name])
            values = column.astype(dtype).array.take(order, allow_fill=True)
            if taken.any():
                values = values.copy()
                values[taken] = frame[name].astype(dtype).array.take(take[taken])
            columns[name] = values
        else:
            columns[name] = column.array.take(order, allow_fill=True)
    hosted = host >= 0
    for name in plan.new_columns:
        incoming = frame[name]
        values = incoming.array.take(np.where(hosted, host, -1), allow_fill=True)
        columns[name] = values
    result = pd.DataFrame(columns)
    result.attrs = dict(raw.attrs)
    result.attrs[ROW_SPANS] = new_spans(raw, arrangement)
    if plan.new_columns:
        ids = current_ids(raw)
        ids.update({name: token for name, token in zip(plan.names, plan.tokens) if name in plan.new_columns})
        result.attrs[COLUMN_IDS] = {name: ids[name] for name in result.columns if name in ids}
    return result


def new_spans(raw, arrangement):
    """Row identities of the new rows: a row that stays keeps its identity, a row that takes back a confirmed
    identity gets it, a new row gets a new one."""
    origins, index, ordinal = _token_arrays(current_spans(raw))
    fresh, number = uuid4().hex, 0
    pairs = []
    for row, old in enumerate(arrangement.order.tolist()):
        if old >= 0:
            pairs.append((origins[index[old]], int(ordinal[old])))
        elif arrangement.tokens[row] is not None:
            pairs.append(arrangement.tokens[row])
        else:
            number += 1
            pairs.append((fresh, number))
    return _coalesce(pairs)


def _coalesce(pairs):
    spans = []
    for origin, ordinal in pairs:
        if spans and spans[-1][0] == origin and spans[-1][1] + spans[-1][2] == ordinal:
            spans[-1][2] += 1
        else:
            spans.append([origin, ordinal, 1])
    return RowSpans(tuple(span) for span in spans)


def file_exclusions(plan, arrangement, raw_columns):
    """(new row, raw column) cells marked excluded in the file, for the rows that take the file's cells."""
    positions = {order: list(raw_columns).index(name) for order, name in enumerate(plan.names)
                 if name in raw_columns}
    rows_of_file = {int(row): new for new, row in enumerate(arrangement.take.tolist()) if row >= 0}
    return {(rows_of_file[row], positions[column]) for row, column in plan.excluded_marks
            if row in rows_of_file and column in positions}


def confirmed_link(plan, arrangement, new_raw):
    """The link after the update: the file just read is the confirmed version."""
    spans = new_raw.attrs[ROW_SPANS]
    origins, index, ordinal = _token_arrays(spans)
    by_file = {}
    for row, file_row in enumerate(arrangement.host.tolist()):
        if file_row >= 0:
            by_file[file_row] = (origins[index[row]], int(ordinal[row]))
    pairs = []
    keys, rows = plan.source_keys, plan.source_rows
    keep = []
    for file_row in range(len(rows)):
        identity = by_file.get(file_row) or plan.base_tokens[file_row]
        if identity is None:  # Replaced without a key and deleted meanwhile: cannot happen, but never invent one.
            continue
        pairs.append(identity)
        keep.append(file_row)
    keep = np.array(keep, dtype=np.int64)
    if plan.new_columns:  # Change source… added columns: digest every imported column from now on.
        names = plan.names
        flags = (_flags(plan.excluded_marks, {index: index for index in range(len(names))}, len(plan.frame))
                 if plan.options.mark_excluded else None)
        keys, rows = digests([canonical(plan.frame[name]) for name in names],
                             canonical(plan.frame[plan.key_name]) if plan.key_name is not None else None, flags)
    path = str(plan.path)
    previous = plan.link
    relative = previous.relative if previous is not None and previous.path == path else None
    return SourceLink(path, relative, plan.delimiter, plan.options, tuple(zip(plan.sources, plan.tokens)),
                      plan.key_source, plan.size, plan.sha256, _coalesce(pairs),
                      pack(keys[keep] if len(keep) else keys[:0], rows[keep] if len(keep) else rows[:0]))


def same_link(first, second):
    """True when two links read the same file the same way and confirm the same version."""
    if first is None or second is None:
        return first is second
    return all(getattr(first, name) == getattr(second, name) for name in
               ("path", "delimiter", "options", "columns", "key", "size", "sha256", "spans", "digests"))


def reindex_styles(styles, arrangement, length):
    """Text styles of the rows after the update: removed rows lose theirs, rows keep theirs in the new order, new
    rows start plain."""
    order = arrangement.order
    kept = order[order >= 0]
    if not styles:
        return styles
    removed = sorted(set(range(length)) - set(kept.tolist()))
    styles = styles.delete_rows(removed)
    rank = np.empty(length, dtype=np.int64)
    survivors = np.sort(kept)
    rank[survivors] = np.arange(len(survivors))
    styles = styles.reorder_rows(len(kept), rank[kept]) if len(kept) else styles
    position = 0
    while position < len(order):
        if order[position] < 0:
            end = position
            while end < len(order) and order[end] < 0:
                end += 1
            styles = styles.insert_rows(position, end - position)
            position = end
        else:
            position += 1
    return styles


def values_text(frame, row, names):
    """Display text of the imported cells of one row: every stored digit (``str`` of the value)."""
    texts = []
    for name in names:
        value = frame[name].iloc[row] if name in frame else None
        try:
            missing = pd.isna(value)
        except (TypeError, ValueError):
            missing = False
        texts.append("" if missing else str(value))
    return texts
