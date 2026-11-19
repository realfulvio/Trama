"""Recovery copies of projects with unsaved changes, without Qt.

The Qt window (``trama_qt/recovery.py``) asks this store to keep the last confirmed state of every open project
with changes, so that a crash or a power cut loses at most one interval of work. The store only deals with files:
it never imports Qt, never sees a ``Project`` and can run (and be tested) without a display.

Layout of the folder (``<profile>/recovery``, the same profile folder as ``preferences.json``)::

    <key>.json             the reference of a copy: schema, generation, title, source, size, SHA-256, owner, time
    <key>.<generation>.alab the complete project, in the ordinary .alab format
    .tmp-<owner>-<random>   a file still being written (removed when its writer is gone or after TEMP_TTL)
    <key>.lock              held for an instant while a copy changes owner (claim)
    leases/<owner>.lease    one per running Trama window (see ``Leases``)

``<key>`` is 32 lowercase hexadecimal digits that identify one project for as long as it is open; titles and
source paths are only stored inside the reference, never used as file names.

Commit order. A new copy is written in two steps: first the payload ``<key>.<n>.alab`` (written to a temporary
file, flushed to disk and renamed), then the reference ``<key>.json`` (same, atomically replaced in the same
folder). The previous payload is removed only after the new reference is in place. So:

* a crash or an error between the two steps leaves the previous reference and payload intact; the new payload is
  an orphan file that nobody references and is swept after ``TEMP_TTL``;
* a full disk or a read-only folder makes ``write_snapshot`` raise ``OSError`` before anything is replaced: the
  previous copy stays valid and readable, and the caller shows the failure without hiding the last good copy;
* a payload that is missing or whose size or SHA-256 differs from its reference is not recoverable: it is reported
  by ``problems()`` and never offered by ``list_snapshots()``, while the other copies keep working.

Limits (visible in the Recover projects dialog): at most ``MAX_SNAPSHOT_BYTES`` (64 MiB) for one copy, at most
``MAX_COPIES`` (20) other copies when a new project wants its first copy, and at most ``MAX_TOTAL_BYTES``
(300 MiB) for the whole folder. When a limit is reached the new copy is refused with ``RecoveryLimitError`` and
nothing existing is deleted: older copies are never thrown away to make room, the user frees space from the dialog.
"""
from __future__ import annotations

import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
from uuid import uuid4

SCHEMA = 1
KEY_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
OWNER_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
MiB = 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * MiB
MAX_TOTAL_BYTES = 300 * MiB
MAX_COPIES = 20
TEMP_TTL = 3600.0  # Seconds an unreferenced or unfinished file may stay before a sweep removes it.
LOCK_TTL = 30.0  # A claim lock older than this belongs to a writer that died mid-claim.
LEASE_TTL = 90.0  # A window that has not renewed its lease for this long is gone (see Leases).
HEARTBEAT = 20.0  # How often a running window renews its lease.
INTERVALS = (15, 30, 60, 120)  # Seconds between copies offered in the preferences.
DEFAULT_INTERVAL = 30
SETTINGS_KEY = "recovery"
REFERENCE_SUFFIX = ".json"
PAYLOAD_SUFFIX = ".alab"
TEMP_PREFIX = ".tmp-"


class RecoveryLimitError(ValueError):
    """A new copy would exceed one of the documented limits; nothing was written or deleted."""

    def __init__(self, message, *, reason):
        super().__init__(message)
        self.reason = reason  # "snapshot", "copies" or "total"


class RecoveryDamaged(ValueError):
    """A copy exists but its reference or payload is missing, truncated or altered. ``code`` names the case for the
    interface: reference_unreadable, reference_invalid, payload_missing, payload_unreadable, payload_size or
    payload_checksum."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class RecoveryBusy(RuntimeError):
    """Another window is changing the owner of the same copy right now, or already took it."""


def valid_key(key):
    return isinstance(key, str) and KEY_PATTERN.match(key) is not None


def _check_key(key):
    if not valid_key(key):
        raise ValueError("A recovery key is 32 lowercase hexadecimal digits.")


def durable_write(path, data):
    """Write ``data`` to a new file and flush it to the disk before returning."""
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_folder(folder):
    if sys.platform.startswith("win"):
        return  # Windows has no directory handles to flush; NTFS journals the rename itself.
    try:
        handle = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def _unlink(path):
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _digest(path):
    hasher = sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


class RecoveryStore:
    """The recovery copies of one profile folder, as seen by one process.

    ``owner`` is the identity of the running window (``Leases``) written into each reference; ``None`` writes
    copies without an owner. ``write_bytes(path, data)`` creates a file (tests replace it to simulate a full disk or
    a slow disk). ``clock`` gives the wall time stored as "last written". All methods are thread safe within the
    process: the Qt window calls them from one background thread, the dialog from the GUI thread.
    """

    def __init__(self, root, *, owner=None, write_bytes=None, clock=time.time):
        if owner is not None and not OWNER_PATTERN.match(str(owner)):
            raise ValueError("An owner is 32 lowercase hexadecimal digits.")
        self.root = Path(root)
        self.owner = owner
        self._write_bytes = write_bytes or durable_write
        self._clock = clock
        self._lock = threading.RLock()
        self._floor = {}  # key -> highest generation that a save or a discard has covered in this process
        self._closed = set()  # keys discarded entirely: no later write may bring them back

    # -- paths ---------------------------------------------------------------------------------------------
    def _reference(self, key):
        return self.root / f"{key}{REFERENCE_SUFFIX}"

    def _payload(self, key, generation):
        return self.root / f"{key}.{generation}{PAYLOAD_SUFFIX}"

    def _temporary(self):
        return self.root / f"{TEMP_PREFIX}{self.owner or 'none'}-{uuid4().hex}"

    def _payloads(self, key):
        """``{generation: path}`` of every payload file of ``key`` on disk, referenced or not."""
        found = {}
        try:
            entries = list(os.scandir(self.root))
        except FileNotFoundError:
            return found
        prefix = f"{key}."
        for entry in entries:
            name = entry.name
            if name.startswith(prefix) and name.endswith(PAYLOAD_SUFFIX):
                middle = name[len(prefix):-len(PAYLOAD_SUFFIX)]
                if middle.isdigit():
                    found[int(middle)] = Path(entry.path)
        return found

    # -- reading -------------------------------------------------------------------------------------------
    def _read_reference(self, key):
        """The parsed reference of ``key``; ``FileNotFoundError`` if there is none, ``RecoveryDamaged`` if it
        cannot be trusted."""
        path = self._reference(key)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        except (OSError, UnicodeError) as error:
            raise RecoveryDamaged(f"The reference cannot be read: {error}", "reference_unreadable") from error
        try:
            record = json.loads(text)
        except ValueError as error:
            raise RecoveryDamaged("The reference is not valid JSON.", "reference_invalid") from error
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            raise RecoveryDamaged("The reference has an unknown schema.", "reference_invalid")
        generation = record.get("generation")
        checks = (
            record.get("session_key") == key,
            isinstance(generation, int) and not isinstance(generation, bool) and generation > 0,
            record.get("payload") == f"{key}.{generation}{PAYLOAD_SUFFIX}",
            isinstance(record.get("size"), int) and record["size"] >= 0,
            isinstance(record.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is not None,
            isinstance(record.get("title"), str),
            record.get("source") is None or isinstance(record.get("source"), str),
            isinstance(record.get("written"), (int, float)),
            record.get("owner") is None or isinstance(record.get("owner"), str),
        )
        if not all(checks):
            raise RecoveryDamaged("The reference is incomplete.", "reference_invalid")
        return record

    def _verified(self, record):
        """The payload bytes of a reference, checked against its size and SHA-256."""
        path = self.root / record["payload"]
        try:
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise RecoveryDamaged("The project file of this copy is missing.", "payload_missing") from error
        except OSError as error:
            raise RecoveryDamaged(f"The project file of this copy cannot be read: {error}", "payload_unreadable") from error
        if len(data) != record["size"]:
            raise RecoveryDamaged("The project file of this copy has the wrong size.", "payload_size")
        if sha256(data).hexdigest() != record["sha256"]:
            raise RecoveryDamaged("The project file of this copy does not match its checksum.", "payload_checksum")
        return data

    def _check_payload(self, record):
        """Like ``_verified`` without keeping the bytes in memory."""
        path = self.root / record["payload"]
        try:
            size = path.stat().st_size
        except FileNotFoundError as error:
            raise RecoveryDamaged("The project file of this copy is missing.", "payload_missing") from error
        except OSError as error:
            raise RecoveryDamaged(f"The project file of this copy cannot be read: {error}", "payload_unreadable") from error
        if size != record["size"]:
            raise RecoveryDamaged("The project file of this copy has the wrong size.", "payload_size")
        try:
            digest = _digest(path)
        except OSError as error:
            raise RecoveryDamaged(f"The project file of this copy cannot be read: {error}", "payload_unreadable") from error
        if digest != record["sha256"]:
            raise RecoveryDamaged("The project file of this copy does not match its checksum.", "payload_checksum")

    def _keys(self):
        try:
            names = sorted(os.listdir(self.root))
        except FileNotFoundError:
            return []
        return [name[:-len(REFERENCE_SUFFIX)] for name in names
                if name.endswith(REFERENCE_SUFFIX) and valid_key(name[:-len(REFERENCE_SUFFIX)])]

    @staticmethod
    def _public(record):
        return {
            "session_key": record["session_key"],
            "generation": record["generation"],
            "title": record["title"],
            "source": record["source"],
            "sha256": record["sha256"],
            "size": record["size"],
            "written": record["written"],
            "owner": record.get("owner"),
            "source_stamp": record.get("source_stamp"),
        }

    def scan(self):
        """``(snapshots, problems)`` in one pass over the folder: the valid copies (as ``list_snapshots``) and the
        damaged ones (as ``problems``)."""
        snapshots, problems = [], []
        with self._lock:
            for key in self._keys():
                try:
                    record = self._read_reference(key)
                    self._check_payload(record)
                except FileNotFoundError:
                    continue  # Discarded between the listing and the read.
                except RecoveryDamaged as error:
                    problems.append(self._problem(key, str(error), error.code))
                    continue
                snapshots.append(self._public(record))
        snapshots.sort(key=lambda item: (-item["written"], item["title"].casefold(), item["session_key"]))
        return snapshots, problems

    def _problem(self, key, reason, code):
        size, owner, title = 0, None, None
        for path in [self._reference(key), *self._payloads(key).values()]:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        try:
            raw = json.loads(self._reference(key).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                owner = raw.get("owner") if isinstance(raw.get("owner"), str) else None
                title = raw.get("title") if isinstance(raw.get("title"), str) else None
        except (OSError, ValueError, UnicodeError):
            pass
        return {"session_key": key, "reason": reason, "code": code, "size": size, "owner": owner, "title": title}

    def list_snapshots(self):
        """The valid copies, newest first (then by title and key): dicts with ``session_key``, ``generation``,
        ``title``, ``source``, ``sha256``, ``size``, ``written`` (seconds since the epoch, UTC), ``owner`` and
        ``source_stamp``. Damaged copies are left out; ``problems()`` lists them."""
        return self.scan()[0]

    def problems(self):
        """The copies that cannot be recovered: dicts with ``session_key``, ``reason`` (English), ``code`` (see
        ``RecoveryDamaged``), ``size``, ``owner`` and ``title`` (when the reference still tells)."""
        return self.scan()[1]

    def read_snapshot(self, session_key):
        """The verified bytes of the current generation of ``session_key``."""
        _check_key(session_key)
        with self._lock:
            return self._verified(self._read_reference(session_key))

    def record(self, session_key):
        """The reference of ``session_key`` (not verified against its payload); ``FileNotFoundError`` if none."""
        _check_key(session_key)
        with self._lock:
            return self._public(self._read_reference(session_key))

    def usage(self):
        """``{"copies": n, "bytes": total}`` for every copy in the folder, damaged ones included."""
        total, copies = 0, 0
        try:
            entries = list(os.scandir(self.root))
        except FileNotFoundError:
            return {"copies": 0, "bytes": 0}
        for entry in entries:
            if entry.name.endswith(REFERENCE_SUFFIX) and valid_key(entry.name[:-len(REFERENCE_SUFFIX)]):
                copies += 1
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
        return {"copies": copies, "bytes": total}

    # -- writing -------------------------------------------------------------------------------------------
    def write_snapshot(self, session_key, generation, project_bytes, *, title, source=None, source_stamp=None):
        """Commit ``project_bytes`` (a complete .alab) as generation ``generation`` of ``session_key``.

        Raises ``ValueError`` for a malformed call or a generation that is not newer than the stored one (or than
        what a save or a discard already covered), ``RecoveryLimitError`` when a limit would be exceeded, and
        ``OSError`` when the disk refuses; in every case the previous copy is left as it was."""
        _check_key(session_key)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("A generation is a positive whole number.")
        if not isinstance(project_bytes, (bytes, bytearray, memoryview)):
            raise ValueError("A recovery copy is the bytes of a project file.")
        data = bytes(project_bytes)
        if not data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{"):
            raise ValueError("A recovery copy must be a complete .alab project.")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("A recovery copy needs a title.")
        if source is not None and not isinstance(source, str):
            raise ValueError("The source of a recovery copy is a path or None.")
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise RecoveryLimitError(f"The project is larger than {MAX_SNAPSHOT_BYTES // MiB} MiB.", reason="snapshot")
        with self._lock:
            if session_key in self._closed or generation <= self._floor.get(session_key, 0):
                raise ValueError("This copy was already saved or discarded.")
            try:
                current = self._read_reference(session_key)
            except FileNotFoundError:
                current = None
            except RecoveryDamaged:
                current = None  # A damaged copy of the same project is replaced by a good one.
            if current is not None and generation <= current["generation"]:
                raise ValueError("A newer copy of this project is already stored.")
            self._check_limits(session_key, len(data), new=current is None)
            self.root.mkdir(parents=True, exist_ok=True)
            payload = self._payload(session_key, generation)
            self._commit_file(payload, data)
            record = {
                "schema": SCHEMA,
                "session_key": session_key,
                "generation": generation,
                "payload": payload.name,
                "size": len(data),
                "sha256": sha256(data).hexdigest(),
                "title": title,
                "source": source,
                "source_stamp": source_stamp,
                "written": float(self._clock()),
                "owner": self.owner,
            }
            try:
                self._commit_file(self._reference(session_key),
                                  json.dumps(record, ensure_ascii=False, indent=1).encode("utf-8"))
            except BaseException:
                _unlink(payload)  # Never referenced: the previous reference still points at its own payload.
                raise
            _fsync_folder(self.root)
            for older, path in self._payloads(session_key).items():
                if older < generation:
                    _unlink(path)
            return self._public(record)

    def _commit_file(self, target, data):
        temporary = self._temporary()
        try:
            self._write_bytes(temporary, data)
            os.replace(temporary, target)
        except BaseException:
            _unlink(temporary)
            raise

    def _check_limits(self, session_key, size, *, new):
        others, total = 0, 0
        try:
            entries = list(os.scandir(self.root))
        except FileNotFoundError:
            entries = []
        for entry in entries:
            name = entry.name
            if name.startswith(session_key):
                continue  # The copy being replaced: its old payload goes once the new one is committed.
            if name.endswith(REFERENCE_SUFFIX) and valid_key(name[:-len(REFERENCE_SUFFIX)]):
                others += 1
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
        if new and others >= MAX_COPIES:
            raise RecoveryLimitError(f"There are already {MAX_COPIES} recovery copies.", reason="copies")
        if total + size > MAX_TOTAL_BYTES:
            raise RecoveryLimitError(f"Recovery copies would exceed {MAX_TOTAL_BYTES // MiB} MiB.", reason="total")

    def discard(self, session_key, *, through_generation=None):
        """Remove the copies of ``session_key`` up to ``through_generation`` included (all of them when None),
        leaving newer generations alone. Idempotent; later writes of a covered generation are refused."""
        _check_key(session_key)
        if through_generation is not None and (isinstance(through_generation, bool)
                                               or not isinstance(through_generation, int)):
            raise ValueError("A generation is a whole number.")
        with self._lock:
            if through_generation is None:
                self._closed.add(session_key)
                _unlink(self._reference(session_key))
                for path in self._payloads(session_key).values():
                    _unlink(path)
                return
            self._floor[session_key] = max(self._floor.get(session_key, 0), through_generation)
            try:
                current = self._read_reference(session_key)
            except FileNotFoundError:
                current = None
            except RecoveryDamaged:
                current = None
            if current is not None and current["generation"] <= through_generation:
                _unlink(self._reference(session_key))
            elif current is None and self._reference(session_key).exists():
                pass  # A damaged reference of an unknown generation: leave it for the dialog.
            for generation, path in self._payloads(session_key).items():
                if generation <= through_generation:
                    _unlink(path)

    def claim(self, session_key, *, expected_owner):
        """Make this store's owner the owner of ``session_key`` if it still belongs to ``expected_owner``.

        Two windows that offer the same orphan copy cannot both take it: the change happens under a lock file
        created exclusively in the folder, and compares the owner first. Returns the reference."""
        _check_key(session_key)
        with self._lock, self._exclusive(session_key):
            record = self._read_reference(session_key)
            if record.get("owner") != expected_owner:
                raise RecoveryBusy("Another Trama window has taken this copy.")
            record["owner"] = self.owner
            self._commit_file(self._reference(session_key),
                              json.dumps(record, ensure_ascii=False, indent=1).encode("utf-8"))
            return self._public(record)

    def _exclusive(self, session_key):
        store = self

        class Lock:
            def __enter__(self_):
                path = store.root / f"{session_key}.lock"
                for _attempt in range(2):
                    try:
                        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    except FileExistsError:
                        try:
                            age = time.time() - path.stat().st_mtime
                        except OSError:
                            continue
                        if age > LOCK_TTL:
                            _unlink(path)
                            continue
                        raise RecoveryBusy("Another Trama window is taking this copy.") from None
                    os.write(handle, (store.owner or "none").encode("ascii"))
                    os.close(handle)
                    self_.path = path
                    return self_
                raise RecoveryBusy("Another Trama window is taking this copy.")

            def __exit__(self_, *_exc):
                _unlink(self_.path)
                return False

        return Lock()

    # -- housekeeping --------------------------------------------------------------------------------------
    def sweep(self, *, alive=lambda owner: False, now=None):
        """Remove unfinished files: temporary files whose writer is gone (or older than ``TEMP_TTL``), payloads that
        no reference points to (older than ``TEMP_TTL``) and stale claim locks. Valid copies are never touched.
        ``alive(owner)`` tells whether another window is still running. Returns the names removed."""
        now = time.time() if now is None else now
        removed = []
        with self._lock:
            try:
                entries = list(os.scandir(self.root))
            except FileNotFoundError:
                return removed
            referenced = {}
            for key in self._keys():
                try:
                    referenced[key] = self._read_reference(key)["payload"]
                except (FileNotFoundError, RecoveryDamaged):
                    referenced[key] = None
            for entry in entries:
                name = entry.name
                try:
                    age = now - entry.stat().st_mtime
                except OSError:
                    continue
                if name.startswith(TEMP_PREFIX):
                    owner = name[len(TEMP_PREFIX):].split("-", 1)[0]
                    mine = owner == (self.owner or "none")
                    gone = owner != "none" and not mine and not alive(owner)
                    if age > TEMP_TTL or (gone and age > LOCK_TTL):
                        if _unlink(entry.path):
                            removed.append(name)
                elif name.endswith(".lock"):
                    if age > LOCK_TTL and _unlink(entry.path):
                        removed.append(name)
                elif name.endswith(PAYLOAD_SUFFIX):
                    key = name.split(".", 1)[0]
                    # Referenced payloads stay; so do those of a damaged reference (the dialog shows them).
                    unreferenced = key not in referenced or (referenced[key] is not None and referenced[key] != name)
                    if valid_key(key) and unreferenced and age > TEMP_TTL and _unlink(entry.path):
                        removed.append(name)
        return removed


# == leases: which windows are still running ==============================================================
class Leases:
    """One small file per running window under ``<root>/leases``.

    A window's identity is a random 32-digit ``owner`` chosen when it starts, so a new process that happens to get
    the PID of a crashed one is still a different owner. The window renews its lease every ``HEARTBEAT`` seconds;
    an owner is alive while its lease file exists and was renewed less than ``LEASE_TTL`` seconds ago. On the same
    computer the PID in the lease is checked too, so a window that crashed is recognised at once instead of after
    the TTL (when the PID was reused by another program the heartbeat still decides). A window that closes normally
    removes its lease. Leases never involve services, autostart entries or system folders.
    """

    def __init__(self, root, *, clock=time.time, ttl=LEASE_TTL):
        self.folder = Path(root) / "leases"
        self.clock = clock
        self.ttl = ttl
        self.host = socket.gethostname()

    @staticmethod
    def new_owner():
        return uuid4().hex

    def _path(self, owner):
        return self.folder / f"{owner}.lease"

    def hold(self, owner):
        """Create or renew the lease of ``owner``."""
        self.folder.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"owner": owner, "pid": os.getpid(), "host": self.host,
                           "heartbeat": float(self.clock())}).encode("utf-8")
        temporary = self.folder / f"{TEMP_PREFIX}{owner}-{uuid4().hex}"
        try:
            durable_write(temporary, data)
            os.replace(temporary, self._path(owner))
        except BaseException:
            _unlink(temporary)
            raise

    def release(self, owner):
        _unlink(self._path(owner))

    def alive(self, owner):
        if not owner or not OWNER_PATTERN.match(str(owner)):
            return False
        try:
            lease = json.loads(self._path(owner).read_text(encoding="utf-8"))
            heartbeat = float(lease["heartbeat"])
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            return False
        if self.clock() - heartbeat > self.ttl:
            return False
        if lease.get("host") == self.host and isinstance(lease.get("pid"), int):
            if lease["pid"] != os.getpid() and not process_running(lease["pid"]):
                return False
        return True

    def sweep(self):
        """Remove the leases of windows that are gone."""
        try:
            names = os.listdir(self.folder)
        except FileNotFoundError:
            return
        for name in names:
            path = self.folder / name
            if name.endswith(".lease"):
                if not self.alive(name[:-len(".lease")]):
                    _unlink(path)
            elif name.startswith(TEMP_PREFIX):
                try:
                    if self.clock() - path.stat().st_mtime > TEMP_TTL:
                        _unlink(path)
                except OSError:
                    pass


def process_running(pid):
    """Whether a process with ``pid`` exists on this computer. True when it cannot be told."""
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such process.
            try:
                code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        return error.errno != errno.ESRCH
    return True


# == preferences ==========================================================================================
def load_settings(path):
    """``(enabled, interval)`` from preferences.json: on and 30 seconds unless the file says otherwise."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        data = {}
    value = data.get(SETTINGS_KEY) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return True, DEFAULT_INTERVAL
    enabled = value.get("enabled", True) is not False
    interval = value.get("interval", DEFAULT_INTERVAL)
    if interval not in INTERVALS or isinstance(interval, bool):
        interval = DEFAULT_INTERVAL
    return enabled, interval


def save_settings(path, enabled, interval):
    """Write the preference atomically, keeping the other settings already in the file."""
    if interval not in INTERVALS or isinstance(interval, bool):
        raise ValueError(f"Choose one of {', '.join(map(str, INTERVALS))} seconds.")
    path = Path(path)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        current = {}
    data = current if isinstance(current, dict) else {}
    data[SETTINGS_KEY] = {"enabled": bool(enabled), "interval": interval}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".preferences-{uuid4().hex}.tmp"
    try:
        durable_write(temporary, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        os.replace(temporary, path)
    except BaseException:
        _unlink(temporary)
        raise
    return path


def source_stamp(path):
    """What identifies the state of an original file cheaply: ``[size, mtime_ns]``, or None if it cannot be read."""
    if path is None:
        return None
    try:
        status = os.stat(path)
    except OSError:
        return None
    return [status.st_size, status.st_mtime_ns]


def original_state(source, stamp):
    """``"none"`` (never saved), ``"unchanged"``, ``"changed"``, ``"missing"`` or ``"unknown"`` for the original of
    a copy, comparing the file on disk with the stamp taken when the project was opened or last saved."""
    if source is None:
        return "none"
    try:
        status = os.stat(source)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unknown"
    if not isinstance(stamp, list) or len(stamp) != 2:
        return "unknown"
    return "unchanged" if [status.st_size, status.st_mtime_ns] == stamp else "changed"
