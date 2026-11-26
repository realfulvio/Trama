"""Presentation titles for worksheet columns and replicate subcolumns."""
from dataclasses import dataclass, field

from .worksheet_column_identity import current_ids


@dataclass(frozen=True)
class WorksheetTitles:
    show_rows: bool = True
    automatic_widths: bool = True
    show_subtitles: bool = True
    shared: bool = True
    # Column captions follow source identities through column moves and renames.
    columns: dict = field(default_factory=dict)
    individual: dict = field(default_factory=dict)
    # One-based replicate positions, stored as strings in the project.
    common: dict = field(default_factory=dict)

    def record(self, raw):
        ids = set(current_ids(raw).values()) if self.columns or self.individual else set()
        record = {}
        for key in ("show_rows", "automatic_widths", "show_subtitles", "shared"):
            if not getattr(self, key):
                record[key] = False
        for key in ("columns", "individual", "common"):
            values = {token: title for token, title in getattr(self, key).items()
                      if key == "common" or token in ids}
            if values:
                record[key] = values
        return record

    @classmethod
    def from_record(cls, record, raw):
        problem = "Invalid worksheet titles."
        if not isinstance(record, dict) or record.keys() - cls.__dataclass_fields__.keys():
            raise ValueError(problem)
        known = set(current_ids(raw).values())
        parsed = {}
        for key, value in record.items():
            if key in ("columns", "individual", "common"):
                if not isinstance(value, dict):
                    raise ValueError(problem)
                for token, text in value.items():
                    if not isinstance(token, str) or not isinstance(text, str) or len(text) > 512:
                        raise ValueError(problem)
                    if key == "common":
                        if not (token.isascii() and token.isdigit() and len(token) <= 7
                                and 1 <= int(token) <= 2_000_000 and str(int(token)) == token):
                            raise ValueError(problem)
                    elif token not in known:
                        raise ValueError(problem)
                parsed[key] = dict(value)
            elif type(value) is bool:
                parsed[key] = value
            else:
                raise ValueError(problem)
        return cls(**parsed)
