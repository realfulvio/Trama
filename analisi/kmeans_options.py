"""Shared options for K-means fitting and model selection."""
from numbers import Integral

from .field_error import FieldError
from .stats import complete

CLUSTERING = "K-means clustering"
SELECTION = "K-means model selection"
METHODS = (CLUSTERING, SELECTION)
ALGORITHM = "K-means algorithm"
LLOYD, HARTIGAN = ALGORITHMS = ("Lloyd", "Hartigan–Wong")
MAX_ITERATIONS = "Hartigan–Wong iteration limit"
INITIAL_ROWS = "Initial worksheet rows"
DEFAULT_ITERATIONS = 10


def fit_options(method, frame, options):
    algorithm = options.get(ALGORITHM, LLOYD)
    if algorithm not in ALGORITHMS:
        raise FieldError(ALGORITHM, "Choose a K-means algorithm.")
    if algorithm == LLOYD:
        return {}

    iterations = options.get(MAX_ITERATIONS, DEFAULT_ITERATIONS)
    if isinstance(iterations, str):
        try:
            iterations = int(iterations)
        except ValueError:
            iterations = None
    if isinstance(iterations, bool) or not isinstance(iterations, Integral) or not 1 <= iterations <= 1000:
        raise FieldError(MAX_ITERATIONS, "Enter a whole number from 1 to 1000.")
    values = {"algorithm": "hartigan-wong", "max_iterations": iterations}
    initial = options.get(INITIAL_ROWS, "")
    if method == SELECTION or initial is None or isinstance(initial, str) and not initial.strip():
        return values

    try:
        rows = [int(part) for part in initial.split(",")] if isinstance(initial, str) else None
    except ValueError:
        rows = None
    count = options.get("Clusters")
    if rows is None or len(rows) != count or len(set(rows)) != len(rows):
        raise FieldError(INITIAL_ROWS, "Enter one distinct worksheet row per cluster, separated by commas.")
    if any(not 1 <= row <= len(frame) for row in rows):
        raise FieldError(INITIAL_ROWS, "Each initial worksheet row must exist and have all selected values.")
    columns = options.get("Variables") or ()
    data = complete(frame.reset_index(drop=True), columns)
    positions = data.index.get_indexer([row - 1 for row in rows])
    if (positions < 0).any():
        raise FieldError(INITIAL_ROWS, "Each initial worksheet row must exist and have all selected values.")
    if len(data.iloc[positions].drop_duplicates()) != count:
        raise FieldError(INITIAL_ROWS, "Initial observations must specify distinct centers.")
    return {**values, "initial_rows": positions}
