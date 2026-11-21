"""Shared options for K-means fitting and model selection."""
from numbers import Integral

from .field_error import FieldError
from .stats import complete

CLUSTERING = "K-means clustering"
SELECTION = "K-means model selection"
METHODS = (CLUSTERING, SELECTION)
SCALE = "Column scaling"
STANDARDIZED, CENTERED, UNSCALED = "Standardized", "Centered", "Unscaled"
SCALES = {STANDARDIZED: "standardize", CENTERED: "center", UNSCALED: "none"}
ALGORITHM = "K-means algorithm"
LLOYD, HARTIGAN, MACQUEEN, FORGY_LLOYD = ALGORITHMS = ("Lloyd", "Hartigan–Wong", "MacQueen", "Forgy–Lloyd")
MAX_ITERATIONS = "Hartigan–Wong iteration limit"
MACQUEEN_ITERATIONS = "MacQueen iteration limit"
LLOYD_ITERATIONS = "Lloyd iteration limit"
ITERATION_FIELDS = {HARTIGAN: MAX_ITERATIONS, MACQUEEN: MACQUEEN_ITERATIONS, FORGY_LLOYD: LLOYD_ITERATIONS}
ENGINE_ALGORITHMS = {HARTIGAN: "hartigan-wong", MACQUEEN: "macqueen", FORGY_LLOYD: "forgy-lloyd"}
INITIALIZATION = "K-means initialization"
BEST_OF_TEN, KMEANS_PLUS_PLUS = INITIALIZATIONS = ("Best of 10 starts", "K-means++")
INITIAL_ROWS = "Initial worksheet rows"
DEFAULT_ITERATIONS = 10
WSS_PLOT = "Show WSS plot"
SILHOUETTE_PLOT = "Show silhouette plot"
GAP_PLOT = "Show Gap plot"
PLOTS = {WSS_PLOT: "WSS", SILHOUETTE_PLOT: "Silhouette", GAP_PLOT: "Gap"}
GAP_REFERENCE = "Gap reference geometry"
GAP_VARIABLE_RANGES, GAP_PRINCIPAL_AXES = GAP_GEOMETRIES = ("Variable ranges", "Principal component ranges")


def scale(options):
    choice = options.get(SCALE, STANDARDIZED if options.get("Standardize", False) else UNSCALED)
    if not isinstance(choice, str) or choice not in SCALES:
        raise FieldError(SCALE, "Choose a supported K-means column scaling.")
    return SCALES[choice]


def saved_scaling(options):
    if not options or SCALE in options:
        return options
    return {**options, SCALE: STANDARDIZED if options.get("Standardize", False) else UNSCALED}


def plot_metrics(options):
    metrics = []
    for plot, metric in PLOTS.items():
        value = options.get(plot, False)
        if type(value) is not bool:
            raise FieldError(plot, "Choose whether to show this plot.")
        if value:
            metrics.append(metric)
    return metrics


def fit_options(method, frame, options):
    algorithm = options.get(ALGORITHM, LLOYD)
    if algorithm not in ALGORITHMS:
        raise FieldError(ALGORITHM, "Choose a K-means algorithm.")
    if algorithm == LLOYD:
        return {}

    iteration_field = ITERATION_FIELDS[algorithm]
    iterations = options.get(iteration_field, DEFAULT_ITERATIONS)
    if isinstance(iterations, str):
        try:
            iterations = int(iterations)
        except ValueError:
            iterations = None
    if isinstance(iterations, bool) or not isinstance(iterations, Integral) or not 1 <= iterations <= 1000:
        raise FieldError(iteration_field, "Enter a whole number from 1 to 1000.")
    values = {"algorithm": ENGINE_ALGORITHMS[algorithm], "max_iterations": iterations}
    if algorithm == HARTIGAN:
        initialization = options.get(INITIALIZATION, BEST_OF_TEN)
        if not isinstance(initialization, str) or initialization not in INITIALIZATIONS:
            raise FieldError(INITIALIZATION, "Choose a K-means initialization.")
        if initialization == KMEANS_PLUS_PLUS:
            values["kmeans_plus_plus"] = True
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
