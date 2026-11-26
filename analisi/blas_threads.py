"""One BLAS thread in every Trama process, asked for before NumPy loads.

Why
    NumPy and SciPy bring OpenBLAS, which starts one thread per logical processor and splits long sums among
    them. The split changes the rounding, so the last digits of a result depended on the number of processors
    of the computer, and on one computer on where it was calculated: the window's process used every thread,
    a calculation worker one (``analisi.parallel``). On 100 000 rows a correlation calculated from its dialog
    read 0.2858660982003516, and 0.2858660982003517 after a linked recalculation. Trama shows every stored
    digit, so the difference was on screen.

    The threads bought nothing. Measured on the analyses that reach BLAS (correlation matrices, regressions,
    PCA, mixed models, Cox on up to 1 000 000 rows), one thread was never slower on Windows and up to twice as
    fast on Linux. The cores are used by the process pool instead, which keeps the numbers of the serial loop.

How
    OpenBLAS reads its thread count once, when the library is loaded. ``analisi/__init__`` calls :func:`pin`
    before importing anything that imports NumPy, and every Trama process (window, worker, test, script) imports
    ``analisi`` first. ``BEFORE_NUMPY`` tells whether that held: False means a host imported NumPy on its own
    before ``analisi``, and its BLAS keeps the threads it started with.

    A value inherited from the computer (``OPENBLAS_NUM_THREADS`` set system-wide) is replaced: it would bring
    the dependence back. ``TRAMA_BLAS_THREADS`` is the one override, for benchmarks; with it the digits are
    again those of that thread count.

What it does not cover
    OpenBLAS also chooses its kernels from the processor (AVX2, AVX-512, ...), which moves the last digits
    between different processors with any number of threads. Nothing here changes that.
"""
import os
import sys

VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
             "NUMEXPR_NUM_THREADS")
OVERRIDE = "TRAMA_BLAS_THREADS"
BEFORE_NUMPY = None  # set by pin(): True when NumPy had not been imported yet


def threads():
    """The thread count to ask for: 1, or the whole number of ``TRAMA_BLAS_THREADS`` (1 to 256)."""
    text = os.environ.get(OVERRIDE, "").strip()
    return text if text.isascii() and text.isdigit() and 1 <= int(text) <= 256 else "1"


def pin():
    """Ask every BLAS/OpenMP runtime for :func:`threads` threads. Returns ``BEFORE_NUMPY``."""
    global BEFORE_NUMPY
    BEFORE_NUMPY = "numpy" not in sys.modules
    count = threads()
    for name in VARIABLES:
        os.environ[name] = count
    return BEFORE_NUMPY
