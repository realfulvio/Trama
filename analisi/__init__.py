"""Independent statistical workbench."""
from . import blas_threads

blas_threads.pin()  # One BLAS thread, asked for before the next line loads NumPy: see analisi/blas_threads.py.

from .data import Dataset, formula, load_tables  # noqa: E402
from .stats import (  # noqa: E402
    describe, ellipse, factorial_anova, hierarchical, kmeans, linear, nonlinear,
    survival, t_test,
)
