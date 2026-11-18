"""Component retention for principal component analysis.

The fit and the eigenvector signs stay in :func:`analisi.exploration.pca`. A component is
alive when its eigenvalue is strictly above the leading eigenvalue times 1e-10, the same
relative rule as the biplot, with no absolute floor.

Parallel analysis is a project convention, not a reproduction of another product's generator.
Replicates are drawn in order from ``Generator(PCG64(seed)).standard_normal((N, P))``. Each
replicate is centered. Standardized data are then scaled by the replicate's own sample
standard deviation; centered data are scaled by the observed sample standard deviation.
A living component passes when its eigenvalue is strictly above the requested percentile.
Retained components are the prefix of that comparison, through the first failure.
"""
import numpy as np
import pandas as pd

from .exploration import pca
from .field_error import FieldError
from .stats import complete

SELECTION = "Selection"
ALL = "All"
FIXED = "Fixed number"
THRESHOLD = "Eigenvalue threshold"
CUMULATIVE = "Cumulative variance"
PARALLEL = "Parallel analysis"
CHOICES = (ALL, FIXED, THRESHOLD, CUMULATIVE, PARALLEL)

RETAINED = "Retained components"
EIGENVALUE = "Eigenvalue threshold"
CUMULATIVE_TARGET = "Cumulative variance (%)"
SIMULATIONS = "Parallel simulations"
SEED = "Parallel seed"
PERCENTILE = "Parallel percentile (%)"
SAVE = "Save parallel simulations"
FIELDS = (RETAINED, EIGENVALUE, CUMULATIVE_TARGET, SIMULATIONS, SEED, PERCENTILE, SAVE)
OPTION_NAMES = frozenset((SELECTION, *FIELDS))

SELECTION_SHEET = "PCA selection"
SETTINGS_SHEET = "PCA selection settings"
SCORES_SHEET = "Selected scores"
LOADINGS_SHEET = "Selected loadings"
PARALLEL_SHEET = "Parallel eigenvalues"
REFERENCE_GID = "trama-pca-parallel-reference"

OPTIONS = {
    SELECTION: CHOICES,
    RETAINED: 2,
    EIGENVALUE: 1.0,
    CUMULATIVE_TARGET: 80.0,
    SIMULATIONS: 1000,
    SEED: 42,
    PERCENTILE: 95.0,
    SAVE: False,
}
TABS = {"Selection": (SELECTION, *FIELDS)}
LABEL_KEYS = {
    SELECTION: "pca.select.selection",
    RETAINED: "pca.select.retained",
    EIGENVALUE: "pca.select.threshold",
    CUMULATIVE_TARGET: "pca.select.cumulative",
    SIMULATIONS: "pca.select.simulations",
    SEED: "pca.select.seed",
    PERCENTILE: "pca.select.percentile",
    SAVE: "pca.select.save",
}
CHOICE_KEYS = {
    ALL: "pca.select.choice.all",
    FIXED: "pca.select.choice.fixed",
    THRESHOLD: "pca.select.choice.threshold",
    CUMULATIVE: "pca.select.choice.cumulative",
    PARALLEL: "pca.select.choice.parallel",
}

_ACTIVE = {
    ALL: (),
    FIXED: (RETAINED,),
    THRESHOLD: (EIGENVALUE,),
    CUMULATIVE: (CUMULATIVE_TARGET,),
    PARALLEL: (SIMULATIONS, SEED, PERCENTILE, SAVE),
}
_NOTES = {
    FIXED: "The first living components are retained, up to the requested count.",
    THRESHOLD: "Living components with an eigenvalue strictly above the threshold are retained.",
    CUMULATIVE: ("The shortest prefix of living components that reaches the cumulative target is retained. "
                 "A target of 100% retains the rank and does not add a numerically empty component."),
    PARALLEL: ("A living component passes when its eigenvalue is strictly above the parallel percentile. "
               "Retained components are the prefix through the first failure. "
               "Replicates use Generator(PCG64(seed)).standard_normal in order."),
}
_SCALE = 1e-10
MIN_SIMULATIONS, MAX_SIMULATIONS = 10, 10_000
MAX_SEED = 2**32 - 1
MAX_VARIABLES = 64
BUDGET = 6_000_000


class Retention:
    """Extra sheets and, for a scree plot, the null percentile curve."""

    def __init__(self, tables=None, quantile=None, percentile=None):
        self.tables = {} if tables is None else tables
        self.quantile = quantile
        self.percentile = percentile


def visible_fields(selection):
    """Fields that belong on screen for one criterion. Unknown criteria show the choice only."""
    active = set(_ACTIVE.get(selection, ()))
    return {field: field in active for field in FIELDS}


def criterion(options):
    """The canonical criterion, or None when the recipe has no selection key."""
    if SELECTION not in options:
        return None
    value = options[SELECTION]
    if value not in CHOICES:
        raise FieldError(SELECTION, f"{SELECTION} must be one of: {', '.join(CHOICES)}.")
    return value


def simulates(options):
    """True when the analysis draws parallel replicates. Invalid criteria raise FieldError."""
    return criterion(options) == PARALLEL


def percentile_label(percentile):
    """Literal series name. The percentile is part of the label so the legend states it."""
    return f"{percentile:g}th percentile"


def check(frame, options):
    """Validate the active criterion without drawing replicates.

    Hidden criteria are ignored, including values that would be invalid if that criterion
    were selected. Parallel limits are decided before any replicate is allocated.
    """
    rule = criterion(options)
    if rule is None or rule == ALL:
        return
    _validate(options, rule)
    parts, eigenvectors, scores = pca(frame, list(options["Variables"]), options["Standardize"])
    _limits(rule, options, parts, eigenvectors, scores)


def assess(frame, options, parts, eigenvectors, scores):
    """Build the selection sheets from a fit that has already been validated or is legacy."""
    rule = criterion(options)
    if rule is None or rule == ALL:
        return Retention()
    _validate(options, rule)
    _limits(rule, options, parts, eigenvectors, scores)
    eigenvalues = parts["Eigenvalue"].to_numpy(dtype=float)
    variance = parts["Variance (%)"].to_numpy(dtype=float)
    cumulative = parts["Cumulative (%)"].to_numpy(dtype=float)
    names = list(parts.index)
    alive = _alive(eigenvalues)
    rank = int(alive.sum())
    n, p = len(scores), len(eigenvectors)
    mean = quantile = random = None
    simulations = seed = percentile = None
    if rule == FIXED:
        count = _whole(options.get(RETAINED, OPTIONS[RETAINED]), RETAINED)
        passed = np.zeros(len(names), dtype=bool)
        passed[:count] = True
    elif rule == THRESHOLD:
        cutoff = _real(options.get(EIGENVALUE, OPTIONS[EIGENVALUE]), EIGENVALUE)
        passed = alive & (eigenvalues > cutoff)
    elif rule == CUMULATIVE:
        target = _real(options.get(CUMULATIVE_TARGET, OPTIONS[CUMULATIVE_TARGET]), CUMULATIVE_TARGET)
        count = 0 if rank == 0 else min(rank, int(np.searchsorted(cumulative + 1e-10, target)) + 1)
        passed = np.zeros(len(names), dtype=bool)
        passed[:count] = True
    else:
        simulations = _whole(options.get(SIMULATIONS, OPTIONS[SIMULATIONS]), SIMULATIONS)
        seed = _whole(options.get(SEED, OPTIONS[SEED]), SEED)
        percentile = _real(options.get(PERCENTILE, OPTIONS[PERCENTILE]), PERCENTILE)
        random = _replicates(frame, options, n, p, len(names), simulations, seed)
        mean = random.mean(axis=0)
        quantile = np.quantile(random, percentile / 100, axis=0, method="linear")
        passed = alive & (eigenvalues > quantile)
    retained = _prefix(passed) if rule == PARALLEL else passed
    count = int(retained.sum())
    selection = pd.DataFrame({
        "PC": np.arange(1, len(names) + 1),
        "Eigenvalue": eigenvalues,
        "Variance (%)": variance,
        "Cumulative (%)": cumulative,
        "Alive": alive,
        "Rule pass": passed,
        "Retained": retained,
        "Random mean": np.full(len(names), np.nan) if mean is None else mean,
        "Random percentile": np.full(len(names), np.nan) if quantile is None else quantile,
    })
    kept = [name for name, flag in zip(names, retained) if flag]
    selected_scores = pd.DataFrame({"Source row": scores.index.to_numpy()})
    for name in kept:
        selected_scores[name] = scores[name].to_numpy()
    loadings = _loading_matrix(scores, eigenvectors, eigenvalues)
    selected_loadings = pd.DataFrame({"Variable": list(eigenvectors.index)})
    positions = list(eigenvectors.columns)
    for name in kept:
        selected_loadings[name] = loadings[:, positions.index(name)]
    settings = pd.DataFrame([{
        "Criterion": rule,
        "Count": count,
        "N": n,
        "P": p,
        "Rank": rank,
        "Standardize": bool(options["Standardize"]),
        "Simulations": np.nan if simulations is None else simulations,
        "Seed": np.nan if seed is None else seed,
        "Percentile": np.nan if percentile is None else percentile,
        "Rule": _NOTES[rule],
    }])
    tables = {
        SELECTION_SHEET: selection,
        SETTINGS_SHEET: settings,
        SCORES_SHEET: selected_scores,
        LOADINGS_SHEET: selected_loadings,
    }
    save = _flag(options.get(SAVE, OPTIONS[SAVE])) if rule == PARALLEL else False
    if save and random is not None:
        replicates = pd.DataFrame(random, columns=names)
        replicates.insert(0, "Simulation", np.arange(1, len(random) + 1))
        tables[PARALLEL_SHEET] = replicates
    return Retention(tables, quantile, percentile)


def _validate(options, rule):
    if rule == FIXED:
        _whole(options.get(RETAINED, OPTIONS[RETAINED]), RETAINED)
    elif rule == THRESHOLD:
        value = _real(options.get(EIGENVALUE, OPTIONS[EIGENVALUE]), EIGENVALUE)
        if value < 0:
            raise FieldError(EIGENVALUE, f"{EIGENVALUE} must be finite and greater than or equal to 0.")
    elif rule == CUMULATIVE:
        value = _real(options.get(CUMULATIVE_TARGET, OPTIONS[CUMULATIVE_TARGET]), CUMULATIVE_TARGET)
        if not 0 < value <= 100:
            raise FieldError(CUMULATIVE_TARGET, f"{CUMULATIVE_TARGET} must be finite and greater than 0 up to 100.")
    else:
        count = _whole(options.get(SIMULATIONS, OPTIONS[SIMULATIONS]), SIMULATIONS)
        if not MIN_SIMULATIONS <= count <= MAX_SIMULATIONS:
            raise FieldError(SIMULATIONS,
                             f"{SIMULATIONS} must be a whole number from {MIN_SIMULATIONS} to {MAX_SIMULATIONS}.")
        seed = _whole(options.get(SEED, OPTIONS[SEED]), SEED)
        if not 0 <= seed <= MAX_SEED:
            raise FieldError(SEED, f"{SEED} must be a whole number from 0 to {MAX_SEED}.")
        percentile = _real(options.get(PERCENTILE, OPTIONS[PERCENTILE]), PERCENTILE)
        if not 0 < percentile < 100:
            raise FieldError(PERCENTILE, f"{PERCENTILE} must be finite and strictly between 0 and 100.")
        _flag(options.get(SAVE, OPTIONS[SAVE]))


def _limits(rule, options, parts, eigenvectors, scores):
    eigenvalues = parts["Eigenvalue"].to_numpy(dtype=float)
    rank = int(_alive(eigenvalues).sum())
    if rule == FIXED:
        count = _whole(options.get(RETAINED, OPTIONS[RETAINED]), RETAINED)
        if not 1 <= count <= rank:
            raise FieldError(RETAINED,
                             f"{RETAINED} must be a whole number from 1 to {rank}, the number of living components.")
    elif rule == PARALLEL:
        count = _whole(options.get(SIMULATIONS, OPTIONS[SIMULATIONS]), SIMULATIONS)
        n, p = len(scores), len(eigenvectors)
        if p > MAX_VARIABLES:
            raise FieldError("Variables",
                             f"Variables is limited to {MAX_VARIABLES} columns for parallel analysis.")
        planned = n * p * count
        if planned > BUDGET:
            raise FieldError(SIMULATIONS,
                             f"{SIMULATIONS} would simulate {planned:,} values, above the limit of {BUDGET:,}.")


def _alive(eigenvalues):
    values = np.asarray(eigenvalues, dtype=float)
    if not len(values):
        return np.zeros(0, dtype=bool)
    return values > float(np.max(values)) * _SCALE


def living(eigenvalues):
    """Flags of the components with a numerically positive eigenvalue, the rule used by every retention criterion."""
    return _alive(eigenvalues)


def _prefix(passed):
    retained = np.zeros(len(passed), dtype=bool)
    for index, ok in enumerate(passed):
        if not ok:
            break
        retained[index] = True
    return retained


def _replicates(frame, options, n, p, m, simulations, seed):
    """One N×P draw at a time. Only the m eigenvalues of each replicate are kept."""
    variables = list(options["Variables"])
    data = complete(frame, variables)
    if len(data) != n:
        raise ValueError("PCA row filter did not match the score rows.")
    observed = data.to_numpy(dtype=float)
    scale = observed.std(axis=0, ddof=1)
    standardize = bool(options["Standardize"])
    generator = np.random.Generator(np.random.PCG64(seed))
    found = np.empty((simulations, m), dtype=float)
    for index in range(simulations):
        draw = generator.standard_normal((n, p))
        draw -= draw.mean(axis=0)
        if standardize:
            draw /= draw.std(axis=0, ddof=1)
        else:
            draw *= scale
        values = np.linalg.eigvalsh(draw.T @ draw / (n - 1))[::-1][:m]
        found[index] = np.maximum(values, 0.0)
    return found


def _loading_matrix(scores, eigenvectors, eigenvalues):
    """Loadings of the existing PCA view, including zeros on numerically empty components."""
    from .pca_graphs import _coordinates

    loadings, _rows, _variables = _coordinates(scores, eigenvectors, eigenvalues)
    return loadings


def _whole(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(field, f"{field} must be a whole number.")
    number = float(value)
    if not np.isfinite(number) or not number.is_integer():
        raise FieldError(field, f"{field} must be a whole number.")
    return int(number)


def _real(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(field, f"{field} must be a finite number.")
    number = float(value)
    if not np.isfinite(number):
        raise FieldError(field, f"{field} must be a finite number.")
    return number


def _flag(value):
    if not isinstance(value, bool):
        raise FieldError(SAVE, f"{SAVE} must be yes or no.")
    return value
