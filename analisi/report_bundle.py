"""Reproducible analysis report: one ZIP that a person without Trama can read offline.

Public layout of a report (``schema_version`` 1)::

    index.html          UTF-8 page: title, Trama version, UTC time, summary and sections (no JS, no URLs)
    manifest.json       format, schema_version, project_title, metadata, sections and files
    tables/001.csv      one member per section, numbered in the order the user chose, starting at 1
    figures/002.svg
    project.alab        optional complete copy of the project (it includes the original data)

``export_bundle`` validates everything before it writes, writes a temporary ZIP in the destination
folder, verifies it with ``verify_bundle`` and only then replaces the destination. ``verify_bundle``
reads a report without extracting it and returns the verified manifest, or raises ``ValueError``.

Reproducibility: with the same arguments (``metadata`` included) the ZIP is byte for byte the same.
Every member has the fixed time stamp 1980-01-01 00:00:00, the same permissions and the same
compression, and members are written in path order. The time of the report is the documented
``metadata["created_utc"]``, never the clock of the ZIP entries.

This module never imports Qt: the Qt window prepares the payloads (CSV and SVG bytes) and calls it.
"""
import csv
from hashlib import sha256
import html
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from xml.etree import ElementTree
import zipfile

FORMAT = "trama-analysis-report"
SCHEMA_VERSION = 1
MAX_SECTIONS = 100
MAX_TOTAL_BYTES = 256 * 1024 * 1024  # Uncompressed members, manifest and index included.
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_TITLE, MAX_LABEL, MAX_NOTE, MAX_METHOD = 300, 300, 20_000, 300
PREVIEW_ROWS = 25
# ``method`` of a layout section: a layout is a page of graphs, not an analysis.
LAYOUT_METHOD = "Layout"
KINDS = {"table": ("tables", ".csv"), "figure": ("figures", ".svg")}
METADATA_KEYS = ("trama_version", "created_utc", "language")
LANGUAGES = ("en", "it")
INDEX, MANIFEST, PROJECT = "index.html", "manifest.json", "project.alab"
SECTION_KEYS = ("label", "kind", "method", "options", "payload")
MANIFEST_KEYS = ("format", "schema_version", "project_title", "metadata", "sections", "files")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SHA = re.compile(r"[0-9a-f]{64}")
_SVG = "{http://www.w3.org/2000/svg}svg"
_STAMP = (1980, 1, 1, 0, 0, 0)
_CHUNK = 1024 * 1024


class ReportCancelled(Exception):
    """The user cancelled the report: the destination was not touched."""


# == validation ==================================================================================
def _text(value, name, limit, *, empty=False):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    if not empty and not value.strip():
        raise ValueError(f"{name} cannot be empty.")
    if len(value) > limit:
        raise ValueError(f"{name} is longer than {limit} characters.")
    if "\x00" in value:
        raise ValueError(f"{name} contains a NUL character.")
    return value


def _plain(value, where, depth=0):
    """Only JSON data: text, finite numbers, booleans, None, lists and objects with text keys."""
    if depth > 32:
        raise ValueError(f"{where} is nested too deeply.")
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where} contains a number that is not finite.")
        return
    if isinstance(value, list):
        for item in value:
            _plain(item, where, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{where} has a key that is not text.")
            _plain(item, where, depth + 1)
        return
    raise ValueError(f"{where} contains a value of type {type(value).__name__}, which is not JSON data.")


def check_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) != set(METADATA_KEYS):
        raise ValueError("Report metadata must have exactly trama_version, created_utc and language.")
    _text(metadata["trama_version"], "trama_version", 64)
    if not isinstance(metadata["created_utc"], str) or not _UTC.fullmatch(metadata["created_utc"]):
        raise ValueError("created_utc must look like 2026-11-19T12:00:00Z.")
    if metadata["language"] not in LANGUAGES:
        raise ValueError("The report language must be en or it.")
    return {key: metadata[key] for key in METADATA_KEYS}


def section_path(position, kind):
    """``tables/001.csv``: the number is the position of the section (from 1), never its title."""
    folder, suffix = KINDS[kind]
    return f"{folder}/{position:03d}{suffix}"


def _check_svg(payload, where):
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError(f"{where} is not a valid SVG document ({error}).") from None
    if root.tag != _SVG:
        raise ValueError(f"{where} is not an SVG document.")
    if any(str(element.tag).rsplit("}", 1)[-1].lower() in {"script", "foreignobject"} for element in root.iter()):
        raise ValueError(f"{where} contains a script or foreign content.")


def _check_sections(sections):
    if not isinstance(sections, (list, tuple)):
        raise ValueError("Sections must be a list.")
    if not sections:
        raise ValueError("Select at least one section for the report.")
    if len(sections) > MAX_SECTIONS:
        raise ValueError(f"A report holds at most {MAX_SECTIONS} sections.")
    total = 0
    for position, section in enumerate(sections, 1):
        where = f"Section {position}"
        if not isinstance(section, dict) or not set(SECTION_KEYS) <= set(section):
            raise ValueError(f"{where} needs label, kind, method, options and payload.")
        payload = section["payload"]
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError(f"{where}: the payload must be bytes.")
        total += len(payload)  # Checked against the budget before any other work.
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"The report would exceed {MAX_TOTAL_BYTES // (1024 * 1024)} MiB.")
    clean = []
    for position, section in enumerate(sections, 1):
        where = f"Section {position}"
        label = _text(section["label"], f"{where} label", MAX_LABEL)
        kind = section["kind"]
        if kind not in KINDS:
            raise ValueError(f"{where}: kind must be table or figure.")
        method = _text(section["method"], f"{where} method", MAX_METHOD)
        options = section["options"]
        if not isinstance(options, dict):
            raise ValueError(f"{where}: options must be an object.")
        _plain(options, f"{where} options")
        payload = bytes(section["payload"])
        if kind == "table":
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"{where}: the CSV is not UTF-8.") from None
        else:
            _check_svg(payload, where)
        clean.append({"label": label, "kind": kind, "method": method,
                      "options": json.loads(json.dumps(options, allow_nan=False)),
                      "file": section_path(position, kind), "payload": payload})
    return clean, total


# == index.html ==================================================================================
_TEXT = {
    "en": {"report": "Analysis report", "version": "Trama version", "created": "Created (UTC)",
           "note": "Note", "contents": "Contents", "table": "Table", "figure": "Figure", "method": "Method",
           "options": "Options", "csv": "Full table (CSV)", "svg": "Open the figure (SVG)",
           "preview": "Preview of the first {rows} rows.", "empty": "The table is empty.",
           "project": "Project copy", "project_text": "project.alab is a complete copy of the Trama project, "
           "including the original data, Info sheets and internal references.",
           "files": "Files and SHA-256 checksums are listed in manifest.json.", "none": "none"},
    "it": {"report": "Report di analisi", "version": "Versione di Trama", "created": "Creato (UTC)",
           "note": "Nota", "contents": "Sommario", "table": "Tabella", "figure": "Figura", "method": "Metodo",
           "options": "Opzioni", "csv": "Tabella completa (CSV)", "svg": "Apri la figura (SVG)",
           "preview": "Anteprima delle prime {rows} righe.", "empty": "La tabella è vuota.",
           "project": "Copia del progetto", "project_text": "project.alab è una copia completa del progetto "
           "Trama, con i dati originali, i fogli Info e i riferimenti interni.",
           "files": "File e checksum SHA-256 sono elencati in manifest.json.", "none": "nessuna"},
}
_STYLE = """
:root{color-scheme:light dark;--fg:#173451;--muted:#5b6b7c;--line:#d5dde6;--bg:#fff;--head:#eef3f8}
@media (prefers-color-scheme:dark){:root{--fg:#e6edf4;--muted:#a7b4c2;--line:#3a4654;--bg:#141a21;--head:#1e2732}}
body{margin:0 auto;max-width:1100px;padding:24px 16px;font:15px/1.5 system-ui,"Segoe UI",sans-serif;
color:var(--fg);background:var(--bg)}
h1{font-size:1.6em;margin:0 0 4px}h2{font-size:1.2em;margin:32px 0 4px;border-top:1px solid var(--line);
padding-top:16px}.meta{color:var(--muted);margin:0}.note{white-space:pre-wrap;border-left:3px solid var(--line);
padding:4px 12px}table{border-collapse:collapse;margin:8px 0;font-variant-numeric:tabular-nums;display:block;
overflow-x:auto}th,td{border:1px solid var(--line);padding:3px 8px;text-align:left;white-space:pre-wrap}
th{background:var(--head)}img{max-width:100%;height:auto;background:#fff;border:1px solid var(--line)}
code{white-space:pre-wrap;word-break:break-word}dl{margin:4px 0}dt{font-weight:600}dd{margin:0 0 4px 16px}
"""


def _e(value):
    return html.escape(str(value), quote=True)


def _preview(payload):
    """Up to ``PREVIEW_ROWS`` data rows (after the header) and whether the CSV has more."""
    text = payload.decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    rows, more = [], False
    for row in csv.reader(io.StringIO(text, newline="")):
        if len(rows) > PREVIEW_ROWS:
            more = True
            break
        rows.append(row)
    return rows, more


def render_index(project_title, sections, metadata, note, has_project):
    words = _TEXT[metadata["language"]]
    out = ["<!DOCTYPE html>", f'<html lang="{metadata["language"]}">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{_e(project_title)}</title>", f"<style>{_STYLE}</style>", "</head>", "<body>",
           f'<p class="meta">{_e(words["report"])}</p>', f"<h1>{_e(project_title)}</h1>",
           f'<p class="meta">{_e(words["version"])}: {_e(metadata["trama_version"])} · '
           f'{_e(words["created"])}: {_e(metadata["created_utc"])}</p>']
    if note:
        out.append(f'<h2>{_e(words["note"])}</h2><p class="note">{_e(note)}</p>')
    out.append(f'<h2>{_e(words["contents"])}</h2><ol>')
    for position, section in enumerate(sections, 1):
        out.append(f'<li><a href="#s{position:03d}">{_e(section["label"])}</a> '
                   f'<span class="meta">({_e(words[section["kind"]])})</span></li>')
    out.append("</ol>")
    for position, section in enumerate(sections, 1):
        out.append(f'<section id="s{position:03d}"><h2>{position}. {_e(section["label"])}</h2>')
        out.append(f'<p class="meta">{_e(words[section["kind"]])} · {_e(words["method"])}: '
                   f'{_e(section["method"])}</p>')
        options = section["options"]
        if options:
            out.append(f'<details><summary>{_e(words["options"])}</summary><dl>')
            for key, value in options.items():
                shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                out.append(f"<dt>{_e(key)}</dt><dd><code>{_e(shown)}</code></dd>")
            out.append("</dl></details>")
        if section["kind"] == "table":
            rows, more = _preview(section["payload"])
            if not rows:
                out.append(f'<p>{_e(words["empty"])}</p>')
            else:
                header, *body = rows
                out.append("<table><thead><tr>" + "".join(f"<th>{_e(cell)}</th>" for cell in header)
                           + "</tr></thead><tbody>")
                for row in body[:PREVIEW_ROWS]:
                    out.append("<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>")
                out.append("</tbody></table>")
                if more:
                    out.append(f'<p class="meta">{_e(words["preview"].format(rows=PREVIEW_ROWS))}</p>')
            out.append(f'<p><a href="{_e(section["file"])}">{_e(words["csv"])}</a></p>')
        else:
            out.append(f'<p><a href="{_e(section["file"])}"><img src="{_e(section["file"])}" '
                       f'alt="{_e(section["label"])}"></a></p>')
            out.append(f'<p><a href="{_e(section["file"])}">{_e(words["svg"])}</a></p>')
        out.append("</section>")
    if has_project:
        out.append(f'<h2>{_e(words["project"])}</h2><p>{_e(words["project_text"])} '
                   f'<a href="{PROJECT}">{PROJECT}</a></p>')
    out.append(f'<p class="meta">{_e(words["files"])}</p>')
    out += ["</body>", "</html>", ""]
    return "\n".join(out).encode("utf-8")


# == writing =====================================================================================
def _dumps(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _info(name):
    info = zipfile.ZipInfo(name, date_time=_STAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def _check(cancel):
    if cancel is not None and cancel():
        raise ReportCancelled("The report was cancelled.")


def build_members(project_title, sections, *, metadata, project_bytes=None, note=""):
    """Validate the request and return ``(members, manifest)``: ``members`` maps path → bytes."""
    _text(project_title, "The report title", MAX_TITLE)
    metadata = check_metadata(metadata)
    _text(note, "The note", MAX_NOTE, empty=True)
    if project_bytes is not None and not isinstance(project_bytes, (bytes, bytearray)):
        raise ValueError("The project copy must be bytes.")
    clean, total = _check_sections(sections)
    total += len(project_bytes or b"")
    if total > MAX_TOTAL_BYTES:
        raise ValueError(f"The report would exceed {MAX_TOTAL_BYTES // (1024 * 1024)} MiB.")
    members = {section["file"]: section["payload"] for section in clean}
    members[INDEX] = render_index(project_title, clean, metadata, note, project_bytes is not None)
    if project_bytes is not None:
        members[PROJECT] = bytes(project_bytes)
    files = [{"path": path, "size": len(content), "sha256": sha256(content).hexdigest()}
             for path, content in sorted(members.items())]
    manifest = {"format": FORMAT, "schema_version": SCHEMA_VERSION, "project_title": project_title,
                "metadata": metadata,
                "sections": [{key: section[key] for key in ("label", "kind", "method", "options", "file")}
                             for section in clean],
                "files": files}
    members[MANIFEST] = _dumps(manifest)
    if sum(len(content) for content in members.values()) > MAX_TOTAL_BYTES:
        raise ValueError(f"The report would exceed {MAX_TOTAL_BYTES // (1024 * 1024)} MiB.")
    return members, json.loads(members[MANIFEST])


def export_bundle(target, project_title, sections, *, metadata, project_bytes=None, note="", cancel=None):
    """Write the report ZIP to ``target`` and return its verified manifest.

    ``sections`` are dicts with ``label``, ``kind`` (``table``/``figure``), ``method``, ``options`` and
    ``payload`` (UTF-8 CSV or SVG bytes). ``cancel()`` returning True raises ``ReportCancelled``; it is
    asked before anything is written, between members and right before the destination is replaced.
    On any error or cancellation the previous file at ``target`` keeps its bytes and no temporary file
    is left behind.
    """
    target = Path(target)
    if target.suffix.lower() != ".zip":
        raise ValueError("The report file name must end with .zip.")
    _check(cancel)
    members, manifest = build_members(project_title, sections, metadata=metadata,
                                      project_bytes=project_bytes, note=note)
    _check(cancel)
    handle, name = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".zip.part", dir=target.parent)
    temp = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            with zipfile.ZipFile(stream, "w") as bundle:
                for path in sorted(members):
                    _check(cancel)
                    bundle.writestr(_info(path), members[path])
            stream.flush()
            os.fsync(stream.fileno())
        if verify_bundle(temp) != manifest:
            raise ValueError("The written report does not match its manifest.")
        _check(cancel)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return manifest


# == verification ================================================================================
def _safe_name(name):
    if not name or "\\" in name or name.startswith("/") or ":" in name or name.endswith("/"):
        return False
    parts = PurePosixPath(name).parts
    return all(part not in {"", ".", ".."} for part in parts) and "/".join(parts) == name


def _no_constants(token):
    raise ValueError(f"manifest.json contains {token}, which is not JSON data.")


def _read(bundle, info, limit):
    digest, size = sha256(), 0
    with bundle.open(info) as stream:
        while chunk := stream.read(_CHUNK):
            size += len(chunk)
            if size > limit:
                raise ValueError(f"{info.filename} is larger than declared.")
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_bundle(path):
    """Return the verified manifest of the report at ``path``; raise ``ValueError`` if anything is wrong."""
    try:
        with zipfile.ZipFile(path) as bundle:
            return _verify(bundle)
    except zipfile.BadZipFile as error:
        raise ValueError(f"The report is not a valid ZIP file ({error}).") from None
    except (zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        raise ValueError(f"The report cannot be read ({error}).") from None


def _verify(bundle):
    infos = bundle.infolist()
    if len(infos) > MAX_SECTIONS + 3:
        raise ValueError("The report has more members than a report can hold.")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("The report has duplicate members.")
    for info in infos:
        if not _safe_name(info.filename) or info.is_dir():
            raise ValueError(f"The report has an unsafe member name: {info.filename!r}.")
        if info.flag_bits & 0x1:
            raise ValueError("The report has encrypted members.")
    if sum(info.file_size for info in infos) > MAX_TOTAL_BYTES:
        raise ValueError("The report declares more data than the report budget.")
    by_name = {info.filename: info for info in infos}
    if MANIFEST not in by_name:
        raise ValueError("The report has no manifest.json.")
    if by_name[MANIFEST].file_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest.json is too large.")
    try:
        manifest = json.loads(bundle.read(MANIFEST).decode("utf-8"), parse_constant=_no_constants)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"manifest.json is not valid UTF-8 JSON ({error}).") from None
    if not isinstance(manifest, dict) or set(manifest) != set(MANIFEST_KEYS):
        raise ValueError("manifest.json does not have the fields of a Trama report.")
    if manifest["format"] != FORMAT:
        raise ValueError("This is not a Trama analysis report.")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Unknown report schema version: {manifest['schema_version']!r}.")
    _text(manifest["project_title"], "project_title", MAX_TITLE)
    check_metadata(manifest["metadata"])
    sections = manifest["sections"]
    if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS:
        raise ValueError("The report must have 1 to 100 sections.")
    expected = {INDEX}
    for position, section in enumerate(sections, 1):
        if not isinstance(section, dict) or set(section) != {"label", "kind", "method", "options", "file"}:
            raise ValueError(f"Section {position} does not have the fields of a report section.")
        _text(section["label"], f"Section {position} label", MAX_LABEL)
        _text(section["method"], f"Section {position} method", MAX_METHOD)
        if section["kind"] not in KINDS:
            raise ValueError(f"Section {position} has an unknown kind.")
        if not isinstance(section["options"], dict):
            raise ValueError(f"Section {position} options must be an object.")
        if section["file"] != section_path(position, section["kind"]):
            raise ValueError(f"Section {position} points to an unexpected file.")
        expected.add(section["file"])
    files = manifest["files"]
    if not isinstance(files, list):
        raise ValueError("manifest.json files must be a list.")
    paths = []
    for record in files:
        if (not isinstance(record, dict) or set(record) != {"path", "size", "sha256"}
                or not isinstance(record["path"], str) or type(record["size"]) is not int or record["size"] < 0
                or not isinstance(record["sha256"], str) or not _SHA.fullmatch(record["sha256"])):
            raise ValueError("manifest.json has an invalid file record.")
        paths.append(record["path"])
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("manifest.json files must be unique and sorted by path.")
    listed = set(paths)
    if not expected <= listed or listed - expected - {PROJECT}:
        raise ValueError("manifest.json lists files that do not match the sections.")
    if set(by_name) != listed | {MANIFEST}:
        unexpected = sorted(set(by_name) - listed - {MANIFEST})
        missing = sorted(listed - set(by_name))
        raise ValueError(f"The report members do not match the manifest (unexpected: {unexpected}, "
                         f"missing: {missing}).")
    for record in files:
        info = by_name[record["path"]]
        if info.file_size != record["size"]:
            raise ValueError(f"{record['path']} does not have the size listed in the manifest.")
        size, digest = _read(bundle, info, record["size"])
        if size != record["size"] or digest != record["sha256"]:
            raise ValueError(f"{record['path']} was modified: its checksum does not match the manifest.")
    return manifest
