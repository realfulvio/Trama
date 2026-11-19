"""Multicore execution: one pool of worker processes shared by the whole application.

Why processes and not threads
    The engines spend their time in Python code (least-squares residuals, k-means restarts, enumerations), so
    threads would queue on the GIL. Each worker is a separate Python process that imports only ``analisi``
    modules (never Tk) and runs at a lower priority than the window, so the interface stays responsive.

Contract for callers
    ``run_tasks(function, items)`` returns exactly ``[function(item) for item in items]``: same values, same order,
    and the same exception (the one of the first failing item) as the serial loop. It falls back to that serial
    loop when one process is configured, when there are too few items, inside a worker (no nested pools), when
    the pool cannot start or breaks, and item by item when an argument, a result or an exception cannot travel
    between processes. Callers never need a second code path.

    * ``function`` must be a module-level function of an ``analisi`` module, and items and results must pickle.
    * Random numbers: two items must never share a random stream. Either each item carries its own seed or index
      (Monte Carlo replicates), or the caller draws the random inputs in the original order and sends them with
      the item (Gap reference sets). Then the result does not depend on the number of processes.
    * Budgets that limit the work of one request stay the same whatever the number of processes, so a project
      gives the same numbers on every computer.
    * State of this process that the engines read travels with every item (``_context``): today the language
      chosen at startup, because several engines word their notes, labels and errors with ``tr``.
    * Cancellation: pass ``cancel`` (anything with ``is_set()``) and ``with_cancel=True``; the function then
      receives a token with ``is_set()`` that mirrors it across processes. Queued items are dropped and computed
      in the calling thread with the original ``cancel``, so each engine raises its own cancellation error.

Windows portable build
    ``tramastat.py`` calls ``multiprocessing.freeze_support()`` before anything else. Without it every worker of
    the PyInstaller executable would start a new Trama window. The start method is ``spawn`` on every platform,
    so Linux development behaves like the portable build.

Settings
    ``preferences.json`` key ``processes``: ``"auto"`` (default) or a whole number from 1 to 64. The environment
    variable ``TRAMA_PROCESSES`` overrides it (tests, benchmarks). N above 1 starts N worker processes; the
    window's process waits for them and computes queued items itself only while they start. 1 keeps every
    calculation in the window's process, as before. Auto uses the logical processors minus one (one stays
    free for the window), at most 8, because each worker holds its own copy of numpy, pandas, scipy and
    matplotlib and of the ``analisi`` modules.
"""
from __future__ import annotations

import concurrent.futures as cf
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
import json
import multiprocessing
import os
from pathlib import Path
import pickle
import sys
import tempfile
import threading
import traceback

AUTO = "auto"
PREFERENCE_KEY = "processes"
ENVIRONMENT = "TRAMA_PROCESSES"
MAX_AUTO = 8
MAX_PROCESSES = 64
SLOTS = 64
POLL_SECONDS = 0.05
WORKER_ENVIRONMENT = {
    # One BLAS/OpenMP thread per worker: N workers × N BLAS threads would oversubscribe the processor.
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    # Engines draw on matplotlib Figure objects; no worker may ever load a GUI backend.
    "MPLBACKEND": "Agg",
}

_OK, _ERROR, _LOCAL = "ok", "error", "local"


# ----------------------------------------------------------------------------------------------- settings

def logical_processors():
    counter = getattr(os, "process_cpu_count", None)  # Python 3.13: honours the affinity mask
    count = counter() if counter is not None else None
    if not count:
        try:
            count = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            count = os.cpu_count()
    return max(1, int(count or 1))


def auto_processes(processors=None):
    processors = logical_processors() if processors is None else processors
    return max(1, min(processors - 1, MAX_AUTO))


def parse_setting(value):
    """``"auto"`` or a whole number from 1 to MAX_PROCESSES; anything else means ``"auto"``."""
    if isinstance(value, bool):
        return AUTO
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", AUTO):
            return AUTO
        try:
            value = int(text)
        except ValueError:
            return AUTO
    if isinstance(value, int) and 1 <= value <= MAX_PROCESSES:
        return value
    return AUTO


def resolve(setting, processors=None):
    setting = parse_setting(setting)
    return auto_processes(processors) if setting == AUTO else setting


def load_setting(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return AUTO
    return parse_setting(data.get(PREFERENCE_KEY)) if isinstance(data, dict) else AUTO


def save_setting(path, setting):
    """Write the preference atomically, keeping the other settings already in the file."""
    setting = parse_setting(setting)
    path = Path(path)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        current = {}
    data = current if isinstance(current, dict) else {}
    data[PREFERENCE_KEY] = setting
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".preferences-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return setting


_configured = AUTO
_lock = threading.RLock()
_pool = None
_disabled = None  # reason why parallel execution was switched off for this session


def configure(setting):
    """Apply the preference. A running pool of another size is closed and rebuilt on the next request."""
    global _configured
    with _lock:
        _configured = parse_setting(setting)
        if _pool is not None and _pool.size != process_count():
            _shutdown_locked()


def in_worker():
    return _child_flags is not None


def process_count():
    """Processes a request may use, the calling thread included; 1 means serial."""
    if in_worker():
        return 1
    override = os.environ.get(ENVIRONMENT)
    return resolve(override if override is not None else _configured)


def status():
    """Short description for the settings dialog and the logs."""
    count = process_count()
    if _disabled is not None:
        return {"processes": 1, "reason": _disabled}
    return {"processes": count, "reason": None}


# ----------------------------------------------------------------------------------------------- workers

_child_flags = None


class CancelToken:
    """``is_set()`` inside a worker: reads the cancellation flag that the calling thread mirrors."""

    __slots__ = ("slot",)

    def __init__(self, slot):
        self.slot = slot

    def is_set(self):
        flags = _child_flags
        return flags is not None and flags[self.slot] != 0


def _initialize(flags):
    global _child_flags
    _child_flags = flags
    os.environ[ENVIRONMENT] = "1"
    _lower_priority()


def _lower_priority():
    """Workers yield to the window: the interface keeps its speed while every core computes."""
    try:
        if sys.platform == "win32":
            import ctypes
            below_normal = 0x00004000
            kernel = ctypes.windll.kernel32
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), below_normal)
        elif hasattr(os, "nice"):
            os.nice(5)
    except Exception:  # priority is a courtesy, never a reason to fail
        pass


def _ready():
    return os.getpid()


def _same_exception(original, copy):
    return (type(copy) is type(original) and copy.args == original.args
            and getattr(copy, "__dict__", {}) == getattr(original, "__dict__", {}))


def _rebuild_exception(kind, args, state):
    """Recreate an exception without calling ``__init__`` (FieldError takes two arguments but keeps one)."""
    error = kind.__new__(kind)
    error.args = args
    if state:
        error.__dict__.update(state)
    return error


def _package_exception(error):
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    try:
        payload = pickle.dumps(error, protocol=pickle.HIGHEST_PROTOCOL)
        if _same_exception(error, pickle.loads(payload)):
            return _ERROR, ("pickle", payload), detail
    except Exception:
        pass
    try:
        state = dict(getattr(error, "__dict__", {}))
        payload = pickle.dumps((type(error), error.args, state), protocol=pickle.HIGHEST_PROTOCOL)
        copy = _rebuild_exception(*pickle.loads(payload))
        if _same_exception(error, copy) and str(copy) == str(error):
            return _ERROR, ("rebuild", payload), detail
    except Exception:
        pass
    return _LOCAL, f"{type(error).__name__} cannot be sent back", detail


def _context():
    """What a fresh worker would not know: the active language (``analisi.i18n.tr`` in engine output)."""
    from .i18n import active_language
    return {"language": active_language()}


def _apply_context(context):
    from .i18n import set_language
    set_language(context["language"])


def _execute(function, item, slot, with_cancel, context):
    """Runs in a worker. Never raises: the calling thread decides what a failure means."""
    try:
        _apply_context(context)
        value = function(item, CancelToken(slot)) if with_cancel else function(item)
    except Exception as error:
        return _package_exception(error)
    try:
        return _OK, pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL), None
    except Exception as error:
        return _LOCAL, f"result cannot be sent back: {type(error).__name__}: {error}", None


def _unpack_exception(payload):
    how, data = payload
    if how == "pickle":
        return pickle.loads(data)
    return _rebuild_exception(*pickle.loads(data))


# ----------------------------------------------------------------------------------------------- pool

class _Pool:
    def __init__(self, size):
        context = multiprocessing.get_context("spawn")
        self.size = size
        self.flags = context.RawArray("b", SLOTS)
        self.free = list(range(SLOTS - 1, -1, -1))
        self.warm = False
        # Workers inherit the environment when they start; spawn can start one at any later submit, so the
        # settings stay in this process's environment. The running process keeps the BLAS it already loaded.
        os.environ.update(WORKER_ENVIRONMENT)
        self.executor = cf.ProcessPoolExecutor(max_workers=size, mp_context=context, initializer=_initialize,
                                               initargs=(self.flags,))

    def acquire(self):
        with _lock:
            if not self.free:
                return None
            slot = self.free.pop()
            self.flags[slot] = 0
            return slot

    def release(self, slot):
        with _lock:
            self.flags[slot] = 0
            self.free.append(slot)

    def close(self):
        for slot in range(SLOTS):
            self.flags[slot] = 1
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        finally:
            terminate = getattr(self.executor, "terminate_workers", None)  # Python 3.14
            if terminate is not None:
                try:
                    terminate()
                except Exception:
                    pass
            else:
                for process in list((getattr(self.executor, "_processes", None) or {}).values()):
                    try:
                        process.terminate()
                    except Exception:
                        pass


def _get_pool(size):
    global _pool, _disabled
    with _lock:
        if _disabled is not None:
            return None
        if _pool is not None and _pool.size != size:
            _shutdown_locked()
        if _pool is None:
            try:
                _pool = _Pool(size)
            except Exception as error:  # no processes on this system: serial for the whole session
                _disabled = f"{type(error).__name__}: {error}"
                return None
        return _pool


def _shutdown_locked():
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        pool.close()


def shutdown():
    """Close the pool (application exit). Running workers are stopped, not awaited."""
    with _lock:
        _shutdown_locked()


def warm_up():
    """Start the workers in the background so the first parallel request does not pay their start-up."""
    count = process_count()
    if count <= 1:
        return False
    pool = _get_pool(count)
    if pool is None:
        return False
    def warmed(future):
        if not future.cancelled() and future.exception() is None:
            pool.warm = True

    try:
        for _ in range(pool.size):
            pool.executor.submit(_ready).add_done_callback(warmed)
    except Exception:
        return False
    return True


def _discard_broken(pool):
    with _lock:
        if _pool is pool:
            _shutdown_locked()


# ----------------------------------------------------------------------------------------------- requests

@dataclass(frozen=True)
class Outcome:
    value: object = None
    error: BaseException | None = None
    remote: bool = False  # True when a worker computed it (benchmarks and tests)


def _local(function, item, cancel, with_cancel):
    try:
        value = function(item, cancel) if with_cancel else function(item)
    except Exception as error:
        return Outcome(error=error)
    return Outcome(value=value)


def _serial(function, items, *, cancel, with_cancel, progress, outcomes):
    results = []
    for done, item in enumerate(items, 1):
        if outcomes:
            results.append(_local(function, item, cancel, with_cancel))
        else:
            results.append(function(item, cancel) if with_cancel else function(item))
        if progress is not None:
            progress(done, len(items))
    return results


def run_tasks(function, items, *, cancel=None, with_cancel=False, progress=None, outcomes=False,
              min_items=2, stop_queued=True):
    """``[function(item) for item in items]`` on several processes.

    ``outcomes=True`` returns one :class:`Outcome` per item and never raises an item's error. Otherwise the
    values are returned and the error of the first failing item (in item order) is raised, as in the loop.
    ``progress(done, total)`` is called from the calling thread. ``stop_queued=False`` keeps queued items
    running after a cancellation (whole analyses: each one decides whether it can be cancelled).
    """
    items = list(items)
    count = process_count()
    if count <= 1 or len(items) < max(2, min_items):
        return _serial(function, items, cancel=cancel, with_cancel=with_cancel, progress=progress,
                       outcomes=outcomes)
    pool = _get_pool(count)
    slot = pool.acquire() if pool is not None else None
    if slot is None:
        return _serial(function, items, cancel=cancel, with_cancel=with_cancel, progress=progress,
                       outcomes=outcomes)
    try:
        found = _run_parallel(pool, slot, function, items, cancel, with_cancel, progress, outcomes, stop_queued)
    finally:
        pool.release(slot)
    if outcomes:
        return found
    for outcome in found:
        if outcome.error is not None:
            raise outcome.error
    return [outcome.value for outcome in found]


def _run_parallel(pool, slot, function, items, cancel, with_cancel, progress, outcomes, stop_queued):
    total = len(items)
    found = [None] * total
    futures = {}
    context = _context()
    try:
        for index, item in enumerate(items):
            futures[pool.executor.submit(_execute, function, item, slot, with_cancel, context)] = index
    except (BrokenProcessPool, RuntimeError):
        _discard_broken(pool)
    pending = set(futures)
    submitted = set(futures.values())
    local = [index for index in range(total) if index not in submitted]
    done_count = 0
    cancelled = False
    first_error = None

    def report():
        if progress is not None:
            progress(done_count, total)

    def settle(index, outcome):
        nonlocal done_count, first_error
        found[index] = outcome
        done_count += 1
        if outcome.error is not None and (first_error is None or index < first_error):
            first_error = index
        report()

    while pending:
        if cancel is not None and cancel.is_set() and not cancelled:
            cancelled = True
            pool.flags[slot] = 1
            if stop_queued:
                for future in list(pending):
                    if future.cancel():
                        pending.discard(future)
                        local.append(futures[future])
        if not outcomes and first_error is not None:
            # The loop would have stopped at its first error: later items are not needed.
            for future in list(pending):
                if futures[future] > first_error and future.cancel():
                    pending.discard(future)
        if not pool.warm and not cancelled:
            # While the workers start, the calling thread takes queued items from the end of the list,
            # so a first request is never slower than the loop.
            for future in sorted(pending, key=futures.get, reverse=True):
                if future.cancel():
                    pending.discard(future)
                    index = futures[future]
                    settle(index, _local(function, items[index], cancel, with_cancel))
                    break
        if not pending:
            break
        done, _ = cf.wait(pending, timeout=POLL_SECONDS, return_when=cf.FIRST_COMPLETED)
        for future in done:
            pending.discard(future)
            index = futures[future]
            if future.cancelled():
                local.append(index)
                continue
            try:
                kind, payload, _detail = future.result()
            except BrokenProcessPool:
                _discard_broken(pool)
                local.append(index)
                continue
            except Exception:  # the argument could not be sent to the worker
                local.append(index)
                continue
            pool.warm = True
            if kind == _OK:
                try:
                    settle(index, Outcome(value=pickle.loads(payload), remote=True))
                except Exception:
                    local.append(index)
            elif kind == _ERROR:
                try:
                    settle(index, Outcome(error=_unpack_exception(payload), remote=True))
                except Exception:
                    local.append(index)
            else:
                local.append(index)
    for index in sorted(local):
        if found[index] is not None:
            continue
        if not outcomes and first_error is not None and index > first_error:
            continue
        settle(index, _local(function, items[index], cancel, with_cancel))
    if not outcomes and first_error is not None:
        return [outcome if outcome is not None else Outcome() for outcome in found]
    return found
