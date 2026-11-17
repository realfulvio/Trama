"""Ordered project metadata and table-linked Info sheets."""

from collections import ChainMap
from dataclasses import dataclass, field
from datetime import date
import re
from uuid import uuid4


MAX_INFO_SHEETS = 500
MAX_INFO_FIELDS = 500
MAX_INFO_NAME = 160
MAX_INFO_VALUE = 8192
MAX_INFO_NOTES = 256 * 1024
MAX_NOTE_STYLES = 4096
NOTE_BOLD, NOTE_ITALIC, NOTE_UNDERLINE = 1, 2, 4
NOTE_STYLE_MASK = NOTE_BOLD | NOTE_ITALIC | NOTE_UNDERLINE
DEFAULT_INFO_FIELDS = ("Experiment Date", "Experiment ID", "Notebook ID", "Project", "Experimenter", "Protocol")
_INVALID_TEXT = re.compile(r"[\x00\ud800-\udfff]")


def _text(value, limit):
    return isinstance(value, str) and len(value) <= limit and not _INVALID_TEXT.search(value)


def _note_styles(styles, text_length):
    if not isinstance(styles, (list, tuple)) or len(styles) > MAX_NOTE_STYLES:
        raise ValueError("Invalid Info note formatting.")
    spans, previous_end = [], 0
    for span in styles:
        if (not isinstance(span, (list, tuple)) or len(span) != 3
                or any(type(value) is not int for value in span)):
            raise ValueError("Invalid Info note formatting.")
        start, end, mask = span
        if not previous_end <= start < end <= text_length or not 1 <= mask <= NOTE_STYLE_MASK:
            raise ValueError("Invalid Info note formatting.")
        if spans and start == previous_end and mask == spans[-1][2]:
            spans[-1] = spans[-1][0], end, mask
        else:
            spans.append((start, end, mask))
        previous_end = end
    return tuple(spans)


@dataclass(frozen=True)
class InfoSheet:
    title: str
    fields: tuple[tuple[str, str], ...] = ()
    notes: str = ""
    table: str | None = None
    uid: str = field(default_factory=lambda: uuid4().hex)
    note_styles: tuple[tuple[int, int, int], ...] = ()

    def __post_init__(self):
        if not _text(self.title, MAX_INFO_NAME) or not self.title.strip() or any(c in self.title for c in "\r\n"):
            raise ValueError("Enter a one-line Info sheet title of up to 160 characters.")
        if not isinstance(self.uid, str) or not re.fullmatch(r"[0-9a-f]{32}", self.uid):
            raise ValueError("Invalid Info sheet identifier.")
        if self.table is not None and (not isinstance(self.table, str) or not self.table):
            raise ValueError("Invalid linked data table.")
        if not _text(self.notes, MAX_INFO_NOTES):
            raise ValueError("Info notes exceed the size limit or contain invalid text.")
        object.__setattr__(self, "note_styles", _note_styles(self.note_styles, len(self.notes)))
        if (not isinstance(self.fields, (list, tuple)) or len(self.fields) > MAX_INFO_FIELDS
                or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                       or not _text(pair[0], MAX_INFO_NAME) or not _text(pair[1], MAX_INFO_VALUE)
                       or any(c in pair[0] for c in "\r\n") for pair in self.fields)):
            raise ValueError("Invalid Info constants or field size.")
        object.__setattr__(self, "fields", tuple(tuple(pair) for pair in self.fields))

    @classmethod
    def new(cls, title, table=None):
        return cls(title, tuple((name, date.today().isoformat() if index == 0 else "")
                                for index, name in enumerate(DEFAULT_INFO_FIELDS)), table=table)


def validate_info_sheets(sheets, tables):
    if len(sheets) > MAX_INFO_SHEETS or len({sheet.uid for sheet in sheets}) != len(sheets):
        raise ValueError("Invalid Info sheet count or duplicate identifier.")
    if any(sheet.table is not None and sheet.table not in tables for sheet in sheets):
        raise ValueError("An Info sheet references an unknown data table.")


def info_contexts(sheets):
    """Share global constants across worksheets and overlay their local names."""
    scopes = {None: {}}
    for sheet in sheets:
        target = scopes.setdefault(sheet.table, {})
        for label, value in sheet.fields:
            key = label.strip().casefold()
            if key:
                target[key] = None if key in target else value
    global_values = scopes[None]
    return {table: ChainMap(values, global_values) if table is not None else global_values
            for table, values in scopes.items()}
