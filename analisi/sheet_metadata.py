"""Optional worksheet presentation state stored in a project."""
import re

KINDS = {"data", "info", "result", "graph", "layout", "saved-layout"}
RUN_KINDS = {"result", "graph", "saved-layout"}
HIGHLIGHTS = ("amber", "green", "blue", "purple")
INVALID_TITLE = re.compile(r"[\r\n\x00\ud800-\udfff]")


def validate_sheet_title(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 160 or INVALID_TITLE.search(name):
        raise ValueError("Enter a one-line sheet name of up to 160 characters.")
    return name.strip()


def validate_sheet_metadata(raw):
    if not isinstance(raw, dict) or set(raw) - {"sheets", "frozen_runs"}:
        raise ValueError("Invalid worksheet state.")
    sheets = raw.get("sheets", {})
    frozen = raw.get("frozen_runs", {})
    if not isinstance(sheets, dict) or not isinstance(frozen, dict) or len(sheets) > 200_000 or len(frozen) > 65_536:
        raise ValueError("Invalid worksheet state.")
    for key, record in sheets.items():
        kind, separator, identifier = key.partition(":")
        if not separator or kind not in KINDS or not identifier or not isinstance(record, dict):
            raise ValueError("Invalid worksheet state.")
        if set(record) - {"name", "highlight", "position", "hidden", "locked", "info"}:
            raise ValueError("Invalid worksheet state.")
        if "name" in record:
            validate_sheet_title(record["name"])
        if "info" in record:
            info = record["info"]
            if (kind != "data" or record.get("locked") is not True or not isinstance(info, dict)
                    or any(value is not None and not isinstance(value, str) for value in info.values())):
                raise ValueError("Invalid frozen worksheet constants.")
        if ("highlight" in record and record["highlight"] not in HIGHLIGHTS
                or "position" in record and (type(record["position"]) is not int or record["position"] < 0)
                or any(flag in record and type(record[flag]) is not bool for flag in ("hidden", "locked"))):
            raise ValueError("Invalid worksheet state.")
    if any(not isinstance(record, dict) for record in frozen.values()):
        raise ValueError("Invalid frozen analysis state.")
    return raw
