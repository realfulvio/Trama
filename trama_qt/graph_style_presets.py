"""Reusable figure styles ("presets") for Qt graphs, and the local library that keeps them.

A preset is a small JSON document::

    {"version": 1, "name": "Publication", "style": {"accent": "#0B7A73", "grid": true, ...}}

It carries only the look of a figure (``TRANSFERABLE``). Titles, axis texts, scales and limits, group and
series formatting, guides, shapes, annotations, comparisons and per-entry legend options belong to the
graph that receives the preset and are never read from or written by it.

The module has no Qt dependency: the dialog (``graph_style_preset_dialog``) and the tests use it the same
way. Every function returns independent copies and raises ``ValueError`` with a short English message
(translated by the caller with ``analisi.i18n.translate_message`` when a catalog entry exists).
"""
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unicodedata

from analisi.presentation import validated_style

VERSION = 1
LIBRARY_VERSION = 1
LIBRARY_FILE = "graph-style-presets.json"
TRANSFERABLE = ("accent", "font_family", "title_size", "label_size", "tick_size", "legend_size", "frame", "grid",
                "grid_minor", "legend")
MAX_NAME = 64
MAX_PRESETS = 100
MAX_PRESET_BYTES = 64 * 1024
# A full library holds at most 100 presets of 64 KiB each; anything larger is not a Trama library.
MAX_LIBRARY_BYTES = MAX_PRESETS * MAX_PRESET_BYTES + 64 * 1024
PRESET_KEYS = {"version", "name", "style"}


class LibraryError(ValueError):
    """The library file exists but cannot be used; ``path`` is left untouched for recovery."""

    def __init__(self, message, path):
        super().__init__(message)
        self.path = Path(path)


# -- names --------------------------------------------------------------------------------------
def clean_name(name):
    """The literal name with surrounding spaces removed; 1–64 characters, no control characters."""
    if not isinstance(name, str):
        raise ValueError("Enter a style name.")
    name = name.strip()
    if not name:
        raise ValueError("Enter a style name.")
    if len(name) > MAX_NAME:
        raise ValueError(f"Style names are limited to {MAX_NAME} characters.")
    if any(unicodedata.category(char) in ("Cc", "Cs", "Zl", "Zp") for char in name):
        raise ValueError("Style names cannot contain line breaks or control characters.")
    return name


def name_key(name):
    """Identity used for uniqueness: Unicode NFC and case folding ("Pubblicazione" == "PUBBLICAZIONE")."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())


# -- values -------------------------------------------------------------------------------------
def _canonical_color(value):
    """RGB(A) tuples accepted by the renderer become JSON lists; strings stay as they are."""
    if isinstance(value, str):
        return value
    if hasattr(value, "tolist") and not isinstance(value, (list, tuple)):
        value = value.tolist()
    if isinstance(value, (list, tuple)) and 3 <= len(value) <= 4:
        if any(type(part) is bool for part in value):
            raise ValueError("Enter a valid color, for example #2866ae.")
        try:
            return [float(part) for part in value]
        except (TypeError, ValueError) as error:
            raise ValueError("Enter a valid color, for example #2866ae.") from error
    raise ValueError("Enter a valid color, for example #2866ae.")


def _canonical_style(style):
    """Validate a transferable style and return a JSON-ready copy with canonical value types."""
    if not isinstance(style, dict):
        raise ValueError("Invalid graph style.")
    extra = set(style) - set(TRANSFERABLE)
    if extra:
        raise ValueError("A figure style can only contain colour, font, frame, grid and legend settings.")
    if not style:
        raise ValueError("A figure style needs at least one setting.")
    result = {}
    for key in TRANSFERABLE:
        if key not in style:
            continue
        value = style[key]
        result[key] = _canonical_color(value) if key == "accent" else deepcopy(value)
    validated_style(deepcopy(result))
    # A value must survive a JSON round trip unchanged (no NaN, no exotic number types).
    try:
        text = json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("The figure style contains a value that cannot be saved.") from error
    if json.loads(text) != result:
        raise ValueError("The figure style contains a value that cannot be saved.")
    return result


def validate_preset(preset):
    """A canonical copy of ``preset``; anything unexpected rejects the whole preset."""
    if not isinstance(preset, dict) or set(preset) != PRESET_KEYS:
        raise ValueError("This is not a Trama figure style.")
    if type(preset["version"]) is not int or preset["version"] != VERSION:
        raise ValueError("This figure style was saved by a newer or unknown version of Trama.")
    name = clean_name(preset["name"])
    if name != preset["name"]:
        raise ValueError("Style names cannot start or end with spaces.")
    return {"version": VERSION, "name": name, "style": _canonical_style(preset["style"])}


def extract_preset(name, current_style):
    """The transferable part of a graph style, as a new preset called ``name``."""
    current_style = current_style or {}
    if not isinstance(current_style, dict):
        raise ValueError("Invalid graph style.")
    style = {key: current_style[key] for key in TRANSFERABLE if key in current_style}
    if not style:
        raise ValueError("This graph uses the analysis defaults: change its colour, fonts, frame, grid or "
                         "legend first.")
    return validate_preset({"version": VERSION, "name": clean_name(name), "style": style})


def apply_preset(current_style, preset):
    """A complete style: ``current_style`` with only the preset's fields replaced."""
    preset = validate_preset(preset)
    result = deepcopy(current_style or {})
    if not isinstance(result, dict):
        raise ValueError("Invalid graph style.")
    result.update(deepcopy(preset["style"]))
    validated_style(deepcopy(result))
    return result


def plan_preset_batch(styles_by_id, selected_ids, preset):
    """Complete updated styles for ``selected_ids`` in selection order, omitting graphs that do not change.

    Every target ID is validated before returning: missing or duplicate IDs raise ``ValueError``.
    Returned styles are independent deep copies; ``styles_by_id`` and ``preset`` are never mutated.
    """
    preset = validate_preset(preset)
    if not isinstance(styles_by_id, Mapping):
        raise ValueError("Invalid graph style.")
    if isinstance(selected_ids, (str, bytes)):
        raise ValueError("Invalid graph selection.")
    try:
        ids = list(selected_ids)
    except TypeError as error:
        raise ValueError("Invalid graph selection.") from error
    seen = set()
    for graph_id in ids:
        try:
            duplicate = graph_id in seen
            present = graph_id in styles_by_id
        except TypeError as error:
            raise ValueError("Invalid graph selection.") from error
        if duplicate:
            raise ValueError("A graph was selected more than once.")
        if not present:
            raise ValueError("A selected graph is no longer available.")
        seen.add(graph_id)
    planned = {}
    for graph_id in ids:
        current = styles_by_id[graph_id]
        if current is not None and not isinstance(current, dict):
            raise ValueError("Invalid graph style.")
        baseline = {} if current is None else current
        updated = apply_preset(baseline, preset)
        if updated != baseline:
            planned[graph_id] = updated
    return planned


def preset_bytes(preset):
    """The UTF-8 JSON of one preset, as it is exported."""
    return (json.dumps(validate_preset(preset), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_preset_file(path):
    """Import: one preset per file, at most 64 KiB, valid as a whole."""
    path = Path(path)
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_PRESET_BYTES + 1)
    except OSError as error:
        raise ValueError(f"The file could not be read: {error.strerror or error}") from error
    if len(data) > MAX_PRESET_BYTES:
        raise ValueError("A figure style file is limited to 64 KiB.")
    try:
        document = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as error:
        raise ValueError("The file is not valid JSON (it may be truncated).") from error
    return validate_preset(document)


def _reject_constant(name):
    raise ValueError(f"{name} is not allowed")


def write_atomic(path, data):
    """Write ``data`` next to ``path`` and replace it in one step; on failure the old file is intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="." + path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def write_preset_file(path, preset):
    write_atomic(path, preset_bytes(preset))


# -- library ------------------------------------------------------------------------------------
def library_path(folder=None):
    """``graph-style-presets.json`` in Trama's preferences folder (next to ``preferences.json``)."""
    if folder is None:
        from analisi.i18n import config_dir
        folder = config_dir()
    return Path(folder) / LIBRARY_FILE


class PresetLibrary:
    """The presets saved on this computer. Reading never changes the file; each change is one atomic write."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else library_path()
        self.presets = []
        self.problem = None

    # reading
    def load(self):
        """Read the file; a missing file is an empty library, a damaged one raises ``LibraryError``."""
        self.presets, self.problem = [], None
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return self
        except OSError as error:
            self.problem = LibraryError(f"The style library could not be read: {error.strerror or error}", self.path)
            raise self.problem from error
        try:
            if size > MAX_LIBRARY_BYTES:
                raise ValueError("The file is larger than a style library can be.")
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
            except json.JSONDecodeError as error:
                raise ValueError(f"the file is not valid JSON (line {error.lineno}, column {error.colno}).") from error
            except UnicodeError as error:
                raise ValueError("the file is not UTF-8 text.") from error
            self.presets = self._parse(document)
        except (OSError, ValueError) as error:
            self.presets = []
            reason = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
            self.problem = LibraryError(f"The style library is damaged and was not changed: {reason}", self.path)
            raise self.problem from error
        return self

    @staticmethod
    def _parse(document):
        if (not isinstance(document, dict) or set(document) != {"version", "presets"}
                or type(document["version"]) is not int or not isinstance(document["presets"], list)):
            raise ValueError("this is not a Trama style library.")
        if document["version"] != LIBRARY_VERSION:
            raise ValueError("the library was saved by a newer or unknown version of Trama.")
        if len(document["presets"]) > MAX_PRESETS:
            raise ValueError(f"a library holds at most {MAX_PRESETS} styles.")
        presets, seen = [], set()
        for number, entry in enumerate(document["presets"], 1):
            try:
                preset = validate_preset(entry)
            except ValueError as error:
                raise ValueError(f"style {number}: {error}") from error
            key = name_key(preset["name"])
            if key in seen:
                raise ValueError(f"style {number}: the name {preset['name']!r} is used twice.")
            seen.add(key)
            presets.append(preset)
        return presets

    def names(self):
        return [preset["name"] for preset in self.presets]

    def find(self, name):
        key = name_key(clean_name(name))
        for index, preset in enumerate(self.presets):
            if name_key(preset["name"]) == key:
                return index
        return None

    def get(self, name):
        index = self.find(name)
        return None if index is None else deepcopy(self.presets[index])

    # changing: every method writes the whole library first and updates memory only on success
    def _commit(self, presets):
        if self.problem is not None:
            raise ValueError("Set the damaged style library aside before changing it.")
        document = {"version": LIBRARY_VERSION, "presets": presets}
        write_atomic(self.path, (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        self.presets = deepcopy(presets)

    def save(self, preset, *, replace=False):
        """Add ``preset``; an existing name (ignoring case) is replaced only with ``replace=True``."""
        preset = validate_preset(preset)
        presets = deepcopy(self.presets)
        index = self.find(preset["name"])
        if index is not None:
            if not replace:
                raise FileExistsError(presets[index]["name"])
            presets[index] = preset
        else:
            if len(presets) >= MAX_PRESETS:
                raise ValueError(f"The style library holds at most {MAX_PRESETS} styles. Delete one first.")
            presets.append(preset)
        self._commit(presets)
        return preset

    def rename(self, old, new, *, replace=False):
        index = self.find(old)
        if index is None:
            raise KeyError(old)
        new = clean_name(new)
        presets = deepcopy(self.presets)
        other = self.find(new)
        if other is not None and other != index:
            if not replace:
                raise FileExistsError(presets[other]["name"])
            presets[index]["name"] = new
            del presets[other]
        else:
            presets[index]["name"] = new
        self._commit(presets)

    def delete(self, name):
        index = self.find(name)
        if index is None:
            raise KeyError(name)
        presets = deepcopy(self.presets)
        del presets[index]
        self._commit(presets)

    def set_aside(self):
        """Move a damaged library next to itself under a dated name and start an empty one."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.stem}.damaged-{stamp}{self.path.suffix}")
        number = 1
        while target.exists():
            number += 1
            target = self.path.with_name(f"{self.path.stem}.damaged-{stamp}-{number}{self.path.suffix}")
        os.replace(self.path, target)
        self.presets, self.problem = [], None
        return target
