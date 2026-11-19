"""File → Export multiple figures… without Qt: safe file names and the one-file-per-figure writer.

``plan_filenames`` turns sheet titles into file names that work on Windows, macOS and Linux and do
not collide with each other or with what is already in the folder. ``BatchExport`` writes the
figures one at a time: each file is rendered by the existing exporter into a private staging folder
inside the destination, checked, then published under its planned name with an exclusive create.
Nothing is ever overwritten and nothing is written outside the chosen folder.

The class does not render on its own thread: the Qt dialog calls ``step`` from the event loop, so
the figures (which belong to Qt canvases) are only touched by the GUI thread, one at a time.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

FORMATS = ("png", "svg", "pdf")
MAX_STEM = 96
FALLBACK_STEM = "Figure"
STAGING_PREFIX = ".trama-export-"
# Windows reserves these device names, alone or before any extension ("CON.txt", "LPT9.tmp.pdf").
RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in "123456789¹²³"),
                      *(f"LPT{n}" for n in "123456789¹²³")})
_FORBIDDEN = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]+')

DONE, SKIPPED, ERROR, CANCELLED = "done", "skipped", "error", "cancelled"


def _check_format(fmt):
    if not isinstance(fmt, str) or fmt not in FORMATS:
        raise ValueError(f"Format must be one of {', '.join(FORMATS)}.")
    return fmt


def name_key(name):
    """How two names compare in a folder: case-insensitive and Unicode NFC, as on Windows and macOS."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", str(name)).casefold())


def safe_stem(title):
    """A file name stem for ``title``: forbidden characters → ``_``, no edge spaces or dots, ≤ 96 characters."""
    stem = _FORBIDDEN.sub("_", unicodedata.normalize("NFC", str(title)))
    stem = stem.strip(" .")[:MAX_STEM].rstrip(" .") or FALLBACK_STEM
    if stem.split(".", 1)[0].rstrip(" ").upper() in RESERVED:
        stem = ("_" + stem)[:MAX_STEM].rstrip(" .")
    return stem


def _numbered(stem, number, suffix):
    tail = f" ({number})"
    return f"{stem[:MAX_STEM - len(tail)].rstrip(' .') or FALLBACK_STEM}{tail}{suffix}"


def plan_filenames(titles, format, occupied=()):
    """One distinct file name per title, in order, avoiding ``occupied`` names (files and folders).

    Names compare case-insensitively after NFC normalisation; a clash gets `` (2)``, `` (3)``… before
    the extension. Titles in the project are never changed.
    """
    suffix = "." + _check_format(format)
    taken = {name_key(name) for name in occupied}
    names = []
    for title in titles:
        stem = safe_stem(title)
        name, number = stem + suffix, 2
        while name_key(name) in taken:
            name, number = _numbered(stem, number, suffix), number + 1
        taken.add(name_key(name))
        names.append(name)
    return names


def folder_names(folder):
    """The names already in ``folder`` (files, folders and links), without our own staging folders."""
    with os.scandir(folder) as entries:
        return [entry.name for entry in entries if not entry.name.startswith(STAGING_PREFIX)]


def verify_file(path, fmt):
    """Open the written file with an independent reader; raise ValueError if it is not a valid ``fmt``."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The exporter did not write the file.")
    try:
        if fmt == "png":
            from PIL import Image

            with Image.open(path) as image:
                if image.format != "PNG":
                    raise ValueError(f"The file is {image.format}, not PNG.")
                image.verify()
        elif fmt == "svg":
            from xml.etree import ElementTree

            root = ElementTree.parse(path).getroot()
            if not root.tag.endswith("svg"):
                raise ValueError("The file is not an SVG document.")
        else:
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(str(path))
            try:
                if len(document) != 1:
                    raise ValueError(f"The PDF has {len(document)} pages instead of 1.")
            finally:
                document.close()
    except ValueError:
        raise
    except Exception as error:  # A reader that cannot parse the file: report it as an invalid export.
        raise ValueError(f"The written {fmt.upper()} file cannot be read: {error}") from None


@dataclass
class BatchItem:
    """One figure to write: ``render(path)`` calls the existing exporter for that exact path."""
    label: str
    filename: str
    render: object


@dataclass
class Outcome:
    label: str
    filename: str
    status: str = ""
    reason: str = ""  # "conflict", "folder" or "" for SKIPPED; the error text for ERROR.
    path: Path = None


@dataclass
class BatchExport:
    """Writes ``items`` into ``folder`` one per ``step``; ``outcomes`` keep one entry per item, in order."""
    folder: Path
    format: str
    items: list
    outcomes: list = field(default_factory=list)
    staging: Path = None
    position: int = 0
    stopped: bool = False
    cancel_requested: bool = False

    def __post_init__(self):
        self.folder = Path(self.folder)
        _check_format(self.format)
        self.items = list(self.items)
        self.outcomes = [Outcome(item.label, item.filename) for item in self.items]

    # -- state --------------------------------------------------------------------------------------
    @property
    def finished(self):
        return self.position >= len(self.items)

    def counts(self):
        counts = {DONE: 0, SKIPPED: 0, ERROR: 0, CANCELLED: 0}
        for outcome in self.outcomes:
            if outcome.status:
                counts[outcome.status] += 1
        return counts

    def cancel(self):
        """Stop before the next file; the files already written stay."""
        self.cancel_requested = True

    def _close_rest(self, status, reason=""):
        for outcome in self.outcomes[self.position:]:
            outcome.status, outcome.reason = status, reason
        self.position = len(self.items)
        self.cleanup()

    def _folder_ok(self):
        return (self.folder.is_dir() and os.access(self.folder, os.W_OK | os.X_OK)
                and self.staging is not None and self.staging.is_dir())

    # -- run ----------------------------------------------------------------------------------------
    def start(self):
        """Create the private staging folder; an unwritable destination stops the whole batch."""
        if self.staging is not None or self.finished:
            return
        try:
            if not self.folder.is_dir():
                raise NotADirectoryError(str(self.folder))
            self.staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=self.folder))
        except OSError:
            self.stopped = True
            self._close_rest(SKIPPED, "folder")

    def step(self):
        """Write the next figure. Return True while figures remain."""
        if self.finished:
            return False
        if self.staging is None:
            self.start()
            if self.finished:
                return False
        if self.cancel_requested:
            self._close_rest(CANCELLED)
            return False
        item, outcome = self.items[self.position], self.outcomes[self.position]
        staged = self.staging / f"{self.position:03d}{Path(item.filename).suffix}"
        try:
            item.render(staged)
            verify_file(staged, self.format)
            outcome.status, outcome.reason = self._publish(staged, item.filename)
            if outcome.status == DONE:
                outcome.path = self.folder / item.filename
        except Exception as error:  # Any failure of one figure; the others still get their chance.
            outcome.status, outcome.reason = ERROR, str(error) or type(error).__name__
        finally:
            _remove(staged)
        self.position += 1
        if outcome.status == ERROR and not self._folder_ok():
            self.stopped = True
            self._close_rest(SKIPPED, "folder")
            return False
        if self.finished:
            self.cleanup()
        return not self.finished

    def _publish(self, staged, filename):
        """Move the checked file to its final name without replacing anything that is there now."""
        if name_key(filename) in {name_key(name) for name in folder_names(self.folder)}:
            return SKIPPED, "conflict"
        target = self.folder / filename
        try:
            os.link(staged, target)  # Atomic and never replaces an existing name.
            return DONE, ""
        except FileExistsError:
            return SKIPPED, "conflict"
        except (OSError, NotImplementedError):
            pass  # No hard links on this volume: fall back to an exclusive create.
        try:
            destination = open(target, "xb")
        except FileExistsError:
            return SKIPPED, "conflict"
        try:
            with destination, open(staged, "rb") as source:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
        except BaseException:
            _remove(target)  # Only the partial file this export created.
            raise
        return DONE, ""

    def run(self, progress=None):
        """Write every figure in a loop (scripts and tests); ``progress(done, total)`` after each one."""
        self.start()
        while self.step():
            if progress is not None:
                progress(self.position, len(self.items))
        self.cleanup()
        return self.outcomes

    def cleanup(self):
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
            self.staging = None if not self.staging.exists() else self.staging


def _remove(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
