"""Ordinal logistic regression with proportional odds (cumulative logit).

The model is logit P(Y <= j | x) = theta_j - x'beta with strictly increasing thresholds theta_1 < ... < theta_(J-1).
The thresholds replace the intercept, so the design has no explicit or implicit constant, and exp(beta) is the odds
ratio of being *above* any threshold; the same beta applies at every threshold. Categorical predictors use the same
dummy coding and reference level as Multiple regression (the first level in sorted text order).

Reading the worksheet
- A row is used when the response and every predictor are filled in. A blank response or predictor drops the row;
  a filled value that cannot be used (text in a numeric predictor, an infinite number) is an error on its field.
- The categories are the distinct response values of the used rows. Numbers and text are both accepted and each category
  keeps the label it prints with (3.0 prints as 3). Two different values that print alike are an error on Response.
- ``Category order`` lists those labels from the lowest to the highest category and must match the used categories.

Estimation uses statsmodels ``OrderedModel`` with the logit link on standardized predictors (a rescaling that leaves the
likelihood unchanged and is undone before reporting). The Wald statistics use the beta block of the inverse observed
information and the normal quantile. Probabilities are differences of cumulative logistic probabilities evaluated
without cancellation in either tail.

Out of scope: confidence intervals of the profile probabilities, the test of the proportional-odds assumption, the
nominal (multinomial) model and penalized fits.
"""
from dataclasses import dataclass
from numbers import Real
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit
from statsmodels.miscmodels.ordinal_model import OrderedModel
from statsmodels.tools.sm_exceptions import ConvergenceWarning, HessianInversionWarning

from .cox_outputs import PROFILE_LIST
from .field_error import FieldError
from .ordinal_logit_catalog import EN
from .reporting import Result, _plot

ORDINAL_LOGIT = "Ordinal logistic regression"
RESPONSE, PREDICTORS, CATEGORICAL, ORDER = "Response", "Predictors", "Categorical predictors", "Category order"
LEVEL, PROFILES, GRAPH = "Confidence level (%)", "Profiles", "Show graph"
NAME, VALUES = "Name", "Values"

# Dialog kind of the one field that is not a plain control ("Multiple" and "Multiple (optional)" are workbench kinds).
CATEGORY_ORDER = "Category order list"
OPTIONS = {RESPONSE: None, PREDICTORS: "Multiple", CATEGORICAL: "Multiple (optional)", ORDER: CATEGORY_ORDER,
           LEVEL: 95.0, PROFILES: PROFILE_LIST, GRAPH: False}
DEFAULT_LEVEL = 95.0
# The dialog places Category order with the data and gives the profiles their own page.
PROFILE_TAB = "Profiles"
PROFILE_FIELDS = (PROFILES, GRAPH)

MIN_LEVELS, MAX_LEVELS = 3, 12
MAX_PREDICTORS, MAX_PROFILES = 8, 12
MAX_ROWS, MAX_COEFFICIENTS = 40_000, 24
MAX_ITERATIONS, GRADIENT_TOLERANCE = 250, 1e-8
# On the standardized scale a coefficient this large moves the logit by this many units per standard deviation of the
# predictor: the data are separated in practice. Thresholds closer than MIN_GAP are the same threshold.
MAX_STANDARDIZED_BETA, MIN_GAP = 30.0, 1e-6

COEFFICIENTS, THRESHOLDS, MODEL_FIT = "Coefficients", "Thresholds", "Model fit"
FITTED, REFERENCES, PROFILE_TABLE = "Fitted probabilities", "Reference levels", "Profile probabilities"
FIGURE_TITLE = "Predicted category probabilities"
PROFILE_GID = "ordinal-logit-profile-{profile}-category-{category}"


def _message(key, **values):
    return EN["ord.error." + key].format(**values)


def _fail(field, key, **values):
    raise FieldError(field, _message(key, **values))


def _finite_real(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if np.isfinite(number) else None


def _names(labels, limit=5):
    shown = [f'"{label}"' for label in labels[:limit]]
    return ", ".join(shown) + (", …" if len(labels) > limit else "")


# ----- reading the worksheet -------------------------------------------------------------------------------------------

def _filled(series):
    """Cells with a value: neither missing nor blank text."""
    mask = series.notna().to_numpy(dtype=bool, copy=True)
    if not pd.api.types.is_numeric_dtype(series.dtype):
        blank = np.array([isinstance(value, str) and not value.strip() for value in series.to_numpy(dtype=object)],
                         dtype=bool)
        mask &= ~blank
    return mask


def label_of(value):
    """The label a category prints with: text as typed, whole numbers without a decimal point."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    number = float(value)
    return str(int(number)) if number.is_integer() and abs(number) < 1e15 else repr(number)


def _is_number(value):
    return not isinstance(value, (bool, np.bool_)) and isinstance(value, (Real, np.number))


def _sort_key(item):
    """Numbers ascending, then text by case-insensitive order: the proposal for Category order."""
    value, label = item
    return (0, float(value), "") if _is_number(value) else (1, 0.0, label.casefold() + "\0" + label)


@dataclass
class Categories:
    labels: list      # in the order of the response in the used rows, before ordering
    codes: np.ndarray  # one index into labels per used row
    default_order: list


def _response_categories(column, name, used, rows):
    """Distinct categories of the used rows with their labels; raises on unusable values or clashing labels."""
    raw = column.to_numpy(dtype=object)
    for index in np.flatnonzero(_filled(column)):
        value = raw[index]
        if not (isinstance(value, str) or _is_number(value)):
            _fail(RESPONSE, "response_value", name=name, row=int(index) + 1)
        if not isinstance(value, str) and not np.isfinite(float(value)):
            _fail(RESPONSE, "response_infinite", name=name, row=int(index) + 1)
    codes, uniques = pd.factorize(raw[used], sort=False)
    if len(uniques) > MAX_LEVELS:
        _fail(RESPONSE, "levels_many", limit=MAX_LEVELS)
    uniques = list(uniques)
    labels = [label_of(value) for value in uniques]
    if len(set(labels)) != len(labels):
        clash = next(label for label in labels if labels.count(label) > 1)
        _fail(RESPONSE, "label_clash", label=clash)
    if len(labels) < MIN_LEVELS:
        _fail(RESPONSE, "levels_few", minimum=MIN_LEVELS, count=len(labels))
    ordered = [label for _, label in sorted(zip(uniques, labels), key=_sort_key)]
    return Categories(labels, np.asarray(codes, dtype=np.int64), ordered)


def proposed_order(frame, response, predictors):
    """Categories of the response in the rows where the response and every predictor are filled, lowest first.

    The dialog shows this list before Run Analysis. It does no validation: an unusable column gives an empty list.
    """
    try:
        if response not in frame or not frame.columns.is_unique or any(name not in frame for name in predictors):
            return []
        used = _filled(frame[response])
        for name in predictors:
            used &= _filled(frame[name])
        return _response_categories(frame[response], response, used, len(frame)).default_order if used.any() else []
    except (FieldError, ValueError, TypeError):
        return []


def _numeric_predictor(column, name, used):
    values = pd.to_numeric(column, errors="coerce")
    if np.iscomplexobj(values.to_numpy()):
        _fail(PREDICTORS, "predictor_numeric", name=name, row=1, value="a complex number")
    numbers = values.to_numpy(dtype=float, na_value=np.nan)
    filled = _filled(column)
    bad = filled & ~np.isfinite(numbers)
    if bad.any():
        row = int(np.flatnonzero(bad)[0])
        _fail(PREDICTORS, "predictor_numeric", name=name, row=row + 1, value=repr(column.iloc[row]))
    return numbers


@dataclass
class Prepared:
    """The worksheet and the recipe read and checked; everything the fit and the sheets need, with no fit yet."""
    response: str
    labels: list            # category labels, lowest to highest
    codes: np.ndarray       # per used row, index into labels
    source: np.ndarray      # 1-based physical row of each used row
    terms: list             # coefficient names
    design: np.ndarray      # used rows x terms
    references: dict        # categorical predictor -> reference level
    total_rows: int
    level: float
    profile_names: list
    profile_designs: np.ndarray
    profile_notes: list
    show_graph: bool

    @property
    def parameters(self):
        return len(self.terms) + len(self.labels) - 1


def _read_selection(frame, options):
    response = options.get(RESPONSE)
    if not isinstance(response, str) or not response:
        _fail(RESPONSE, "response_choose")
    if not frame.columns.is_unique:
        _fail(RESPONSE, "unique")
    if response not in frame.columns:
        _fail(RESPONSE, "response_exists", name=response)
    predictors = options.get(PREDICTORS)
    if not isinstance(predictors, (list, tuple)):
        if predictors is None:
            _fail(PREDICTORS, "predictors_count", limit=MAX_PREDICTORS, count=0)
        _fail(PREDICTORS, "predictors_list")
    predictors = list(predictors)
    if not 1 <= len(predictors) <= MAX_PREDICTORS:
        _fail(PREDICTORS, "predictors_count", limit=MAX_PREDICTORS, count=len(predictors))
    for position, name in enumerate(predictors):
        if not isinstance(name, str) or name not in frame.columns:
            _fail(PREDICTORS, "predictors_exists", name=name)
        if name == response:
            _fail(PREDICTORS, "predictors_response", name=name)
        if name in predictors[:position]:
            _fail(PREDICTORS, "predictors_repeat", name=name)
    categorical = options.get(CATEGORICAL)
    if categorical is None:
        categorical = []
    if not isinstance(categorical, (list, tuple)):
        _fail(CATEGORICAL, "categorical_list")
    for name in categorical:
        if name not in predictors:
            _fail(CATEGORICAL, "categorical_subset", name=name)
    return response, predictors, list(dict.fromkeys(categorical))


def _read_level(options):
    value = options.get(LEVEL, DEFAULT_LEVEL)
    level = _finite_real(value)
    if level is None or not 0 < level < 100:
        _fail(LEVEL, "level")
    return level


def _read_profiles(options):
    """Profile records with their shape checked; the predictors and categories are checked against the data later."""
    profiles = options.get(PROFILES)
    if profiles is None:
        return []
    if not isinstance(profiles, (list, tuple)):
        _fail(PROFILES, "profiles_list")
    if len(profiles) > MAX_PROFILES:
        _fail(PROFILES, "profiles_many", limit=MAX_PROFILES, count=len(profiles))
    names = []
    for position, profile in enumerate(profiles, 1):
        if not isinstance(profile, dict) or not isinstance(profile.get(VALUES), dict):
            _fail(PROFILES, "profile_shape", position=position)
        name = profile.get(NAME)
        if not isinstance(name, str) or not name.strip():
            _fail(PROFILES, "profile_name", position=position)
        if name in names:
            _fail(PROFILES, "profile_repeat", name=name)
        names.append(name)
    return list(profiles)


def _read_graph(options, profiles):
    value = options.get(GRAPH, False)
    if not isinstance(value, (bool, np.bool_)):
        _fail(GRAPH, "graph_flag")
    if value and not profiles:
        _fail(PROFILES, "graph_profiles")
    return bool(value)


def _order(options, observed):
    """The declared order of the used categories; the recipe may list numbers or text, compared by printed label."""
    given = options.get(ORDER)
    if given is None or (isinstance(given, (list, tuple)) and not len(given)):
        return list(observed)
    if not isinstance(given, (list, tuple)):
        _fail(ORDER, "order_list")
    declared = []
    for item in given:
        if not (isinstance(item, str) or _is_number(item)):
            _fail(ORDER, "order_list")
        label = label_of(item)
        if label in declared:
            _fail(ORDER, "order_duplicate", name=label)
        declared.append(label)
    missing = [label for label in observed if label not in declared]
    extra = [label for label in declared if label not in observed]
    if missing:
        _fail(ORDER, "order_missing", names=_names(missing))
    if extra:
        _fail(ORDER, "order_extra", names=_names(extra))
    return declared


def _design(frame, predictors, categorical, used):
    """Design matrix of the used rows with the coding of Multiple regression and no intercept."""
    plan, count = [], 0
    for name in predictors:
        if name in categorical:
            levels = sorted(frame[name][used].astype(str).unique())
            if len(levels) < 2:
                _fail(PREDICTORS, "category_levels", name=name)
            plan.append((name, levels))
            count += len(levels) - 1
        else:
            plan.append((name, None))
            count += 1
    if count > MAX_COEFFICIENTS:
        _fail(PREDICTORS, "coefficients", count=count, limit=MAX_COEFFICIENTS)
    terms, columns, references = [], [], {}
    for name, levels in plan:
        if levels is None:
            terms.append(name)
            columns.append(_numeric_predictor(frame[name], name, used)[used])
            continue
        text = frame[name][used].astype(str)
        references[name] = levels[0]
        for level in levels[1:]:
            terms.append(f"{name} [{level}]")
            columns.append((text == level).to_numpy(dtype=float))
    for term in terms:
        if terms.count(term) > 1:
            _fail(PREDICTORS, "term_repeat", name=term)
    return terms, np.column_stack(columns), references, {name: levels for name, levels in plan if levels}


def _check_identified(design, rows, level_count):
    """Reject a constant, an implicit constant or collinear columns, and too few rows for the parameters."""
    spread = np.ptp(design, axis=0)
    if (spread == 0).any():
        _fail(PREDICTORS, "constant")
    standardized = (design - design.mean(axis=0)) / design.std(axis=0)
    rank = np.linalg.matrix_rank(standardized)
    if rank < design.shape[1]:
        # A combination of the columns that is constant leaves the centered matrix rank deficient too; tell the two
        # situations apart by asking whether the raw columns are collinear without the constant.
        if np.linalg.matrix_rank(design) == design.shape[1]:
            _fail(PREDICTORS, "constant")
        _fail(PREDICTORS, "rank")
    parameters = design.shape[1] + level_count - 1
    if rows <= parameters:
        _fail(PREDICTORS, "too_few", count=rows, parameters=parameters)


def _profile_rows(profiles, predictors, categorical, levels_by_predictor, design, terms):
    """Design rows of the profiles, with a note where a continuous value is outside the observed range."""
    low, high = design.min(axis=0), design.max(axis=0)
    column = {term: index for index, term in enumerate(terms)}
    rows, notes = [], []
    for profile in profiles:
        profile_name, values = profile[NAME], profile[VALUES]
        unknown = [name for name in values if name not in predictors]
        if unknown:
            _fail(PROFILES, "profile_unknown", profile=profile_name, name=unknown[0])
        row, outside = np.zeros(len(terms)), []
        for name in predictors:
            if name not in values:
                _fail(PROFILES, "profile_missing", profile=profile_name, name=name)
            value = values[name]
            if name in categorical:
                shown = value if isinstance(value, str) else label_of(value) if _is_number(value) else str(value)
                levels = levels_by_predictor[name]
                text = value if isinstance(value, str) and value in levels else shown
                if text not in levels:
                    _fail(PROFILES, "profile_category", profile=profile_name, value=shown, name=name)
                if text != levels[0]:
                    row[column[f"{name} [{text}]"]] = 1.0
                continue
            number = _finite_real(value)
            if number is None:
                _fail(PROFILES, "profile_number", profile=profile_name, name=name)
            index = column[name]
            row[index] = number
            if not low[index] <= number <= high[index]:
                outside.append(f"{name} = {label_of(number)} is outside the observed range "
                               f"{label_of(float(low[index]))} to {label_of(float(high[index]))}")
        rows.append(row)
        notes.append(("Extrapolation: " + "; ".join(outside) + ".") if outside else "")
    return np.array(rows, dtype=float).reshape(len(profiles), len(terms)), notes


def check_dialog_options(frame, options, observed):
    """Check the recipe before dialog acceptance. Matrix construction and fitting stay on the worker."""
    _read_selection(frame, options)
    _read_level(options)
    _read_graph(options, _read_profiles(options))
    if observed:
        _order(options, observed)


def check_options(frame, options):
    """Every value, role and budget that can be checked without fitting; raises FieldError on the field to correct."""
    response, predictors, categorical = _read_selection(frame, options)
    level = _read_level(options)
    profiles = _read_profiles(options)
    show_graph = _read_graph(options, profiles)
    used = _filled(frame[response])
    for name in predictors:
        used &= _filled(frame[name])
    # A filled predictor value that cannot be used is an error even in a row that is dropped for another reason.
    for name in predictors:
        if name not in categorical:
            _numeric_predictor(frame[name], name, used)
    rows = int(used.sum())
    if rows == 0:
        _fail(RESPONSE, "no_rows")
    if rows > MAX_ROWS:
        _fail(RESPONSE, "rows", limit=f"{MAX_ROWS:,}", count=f"{rows:,}")
    categories = _response_categories(frame[response], response, used, len(frame))
    labels = _order(options, categories.default_order)
    remap = np.array([labels.index(label) for label in categories.labels], dtype=np.int64)
    codes = remap[categories.codes]
    terms, design, references, levels = _design(frame, predictors, categorical, used)
    _check_identified(design, rows, len(labels))
    profile_designs, notes = _profile_rows(profiles, predictors, set(categorical), levels, design, terms)
    return Prepared(response=response, labels=labels, codes=codes, source=np.flatnonzero(used) + 1, terms=terms,
                    design=design, references=references, total_rows=len(frame), level=level,
                    profile_names=[profile[NAME] for profile in profiles], profile_designs=profile_designs,
                    profile_notes=notes, show_graph=show_graph)


# ----- estimation ------------------------------------------------------------------------------------------------------

@dataclass
class Fit:
    beta: np.ndarray        # original scale
    se: np.ndarray
    thresholds: np.ndarray  # original scale, strictly increasing
    loglike: float
    iterations: int
    mean: np.ndarray        # of the design columns
    scale: np.ndarray
    # The probabilities are evaluated on the standardized scale the fit was made on.
    beta_z: np.ndarray
    thresholds_z: np.ndarray


def category_probabilities(eta, thresholds):
    """P(Y = j) for every category, from the linear predictor eta = x'beta and the J - 1 thresholds.

    Each probability is a difference of cumulative logistic probabilities. Between two thresholds a and b the difference
    equals sinh((b - a)/2) / (2 cosh(a/2) cosh(b/2)), which is evaluated in logarithms so a tail probability keeps its
    relative accuracy and never turns negative. The outer categories are single logistic tails.
    """
    eta = np.asarray(eta, dtype=float).reshape(-1, 1)
    cut = np.asarray(thresholds, dtype=float).reshape(1, -1) - eta
    out = np.empty((eta.shape[0], cut.shape[1] + 1))
    out[:, 0] = expit(cut[:, 0])
    out[:, -1] = expit(-cut[:, -1])
    if cut.shape[1] > 1:
        lower, upper = cut[:, :-1], cut[:, 1:]
        gap = upper - lower
        half_log = lambda x: np.abs(x) / 2 + np.log1p(np.exp(-np.abs(x)))
        with np.errstate(divide="ignore", under="ignore"):
            out[:, 1:-1] = np.exp(gap / 2 + np.log(-np.expm1(-gap)) - half_log(lower) - half_log(upper))
    return out


def _estimate(prepared):
    """Fit OrderedModel on the standardized design; raises on non-convergence or an unusable solution."""
    design = prepared.design
    mean, scale = design.mean(axis=0), design.std(axis=0)
    standardized = (design - mean) / scale
    model = OrderedModel(prepared.codes, standardized, distr="logit")
    count = [0]

    def tick(_):
        count[0] += 1

    with warnings.catch_warnings(record=True) as caught, np.errstate(all="ignore"):
        warnings.simplefilter("always")
        try:
            result = model.fit(method="bfgs", maxiter=MAX_ITERATIONS, gtol=GRADIENT_TOLERANCE, disp=False,
                               callback=tick)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError, OverflowError) as error:
            raise FieldError(PREDICTORS, _message("separation")) from error
    params = np.asarray(result.params, dtype=float)
    if not np.isfinite(params).all():
        _fail(PREDICTORS, "separation")
    if not result.mle_retvals.get("converged", False):
        _fail(PREDICTORS, "converge")
    inversion_failed = any(issubclass(item.category, HessianInversionWarning) for item in caught)
    try:
        covariance = np.asarray(result.cov_params(), dtype=float)
    except (ValueError, np.linalg.LinAlgError):
        inversion_failed = True
    if inversion_failed or not np.isfinite(covariance).all():
        _fail(PREDICTORS, "covariance")
    k = standardized.shape[1]
    beta_z = params[:k]
    thresholds_z = np.asarray(model.transform_threshold_params(params), dtype=float)[1:-1]
    if not np.isfinite(thresholds_z).all() or np.abs(beta_z).max() > MAX_STANDARDIZED_BETA:
        _fail(PREDICTORS, "separation")
    if np.diff(thresholds_z).min() < MIN_GAP:
        _fail(PREDICTORS, "thresholds")
    block = covariance[:k, :k]
    try:
        np.linalg.cholesky(covariance)
    except np.linalg.LinAlgError:
        _fail(PREDICTORS, "covariance")
    variance = np.diag(block)
    if not (variance > 0).all():
        _fail(PREDICTORS, "covariance")
    beta = beta_z / scale
    with np.errstate(over="ignore"):
        shift = float(np.sum(beta_z * mean / scale))
    thresholds = thresholds_z + shift
    se = np.sqrt(variance) / scale
    if not (np.isfinite(beta).all() and np.isfinite(se).all() and np.isfinite(thresholds).all()
            and np.isfinite(float(result.llf))):
        _fail(PREDICTORS, "range")
    return Fit(beta=beta, se=se, thresholds=thresholds, loglike=float(result.llf), iterations=count[0],
               mean=mean, scale=scale, beta_z=beta_z, thresholds_z=thresholds_z)


def fit_model(prepared):
    """The estimation step alone, so a style change or a different view never repeats it."""
    return _estimate(prepared)


def linear_predictor(fit, design):
    """x'beta on the standardized scale: the quantity the thresholds are compared with."""
    return ((np.asarray(design, dtype=float) - fit.mean) / fit.scale) @ fit.beta_z


def probabilities(fit, design):
    return category_probabilities(linear_predictor(fit, design), fit.thresholds_z)


# ----- sheets and figure -----------------------------------------------------------------------------------------------

def _first_best(table):
    """Index of the largest probability in each row; a tie keeps the lowest category."""
    best = table.max(axis=1, keepdims=True)
    return np.argmax(table >= best * (1 - 1e-12), axis=1)


def coefficient_table(prepared, fit):
    z = stats.norm.ppf(0.5 + prepared.level / 200)
    with np.errstate(over="raise"):
        try:
            odds = np.exp(np.array([fit.beta, fit.beta - z * fit.se, fit.beta + z * fit.se]))
        except FloatingPointError:
            _fail(PREDICTORS, "range")
    statistic = fit.beta / fit.se
    table = pd.DataFrame({"Estimate": fit.beta, "SE": fit.se, "p": 2 * stats.norm.sf(np.abs(statistic)),
                          "Odds ratio": odds[0], "OR lower": odds[1], "OR upper": odds[2]},
                         index=pd.Index(prepared.terms, name="Term"))
    return table


def threshold_table(prepared, fit):
    labels = prepared.labels
    return pd.DataFrame({"Lower category": labels[:-1], "Upper category": labels[1:], "Estimate": fit.thresholds},
                        index=pd.RangeIndex(1, len(labels), name="Threshold"))


def model_fit_table(prepared, fit):
    rows = len(prepared.codes)
    return pd.DataFrame({"N": [rows], "Incomplete rows": [prepared.total_rows - rows],
                         "Log likelihood": [fit.loglike], "AIC": [-2 * fit.loglike + 2 * prepared.parameters],
                         "Confidence level (%)": [prepared.level]}, index=pd.Index(["Model"], name="Model"))


def fitted_table(prepared, fit, table):
    labels = np.array(prepared.labels, dtype=object)
    frame = pd.DataFrame({"Source row": prepared.source, "Observed": labels[prepared.codes],
                          "Predicted": labels[_first_best(table)]})
    for index, label in enumerate(prepared.labels):
        frame[f"P({label})"] = table[:, index]
    frame.index = pd.RangeIndex(1, len(frame) + 1, name="Row")
    return frame


def profile_table(prepared, table):
    frame = pd.DataFrame({"Profile": prepared.profile_names})
    for index, label in enumerate(prepared.labels):
        frame[f"P({label})"] = table[:, index]
    if any(prepared.profile_notes):
        frame["Note"] = prepared.profile_notes
    return frame


def palette(count):
    """One sequential blue per category, lightest for the lowest: the same colors for the same position."""
    light, dark = np.array([0xD9, 0xE8, 0xF3]) / 255, np.array([0x0E, 0x3F, 0x66]) / 255
    ramp = [light + (dark - light) * (index / max(count - 1, 1)) for index in range(count)]
    return ["#%02x%02x%02x" % tuple(int(round(channel * 255)) for channel in color) for color in ramp]


def figure(prepared, table):
    """Stacked bars, one per profile: every stack starts at 0 and reaches 1, categories in the declared order."""
    chart, axes = _plot(FIGURE_TITLE, "Profile", "Probability")
    positions = np.arange(len(prepared.profile_names))
    base = np.zeros(len(positions))
    colors = palette(len(prepared.labels))
    for category, label in enumerate(prepared.labels):
        bars = axes.bar(positions, table[:, category], bottom=base, width=0.62, color=colors[category],
                        edgecolor="white", linewidth=0.8, label=label)
        for profile, bar in enumerate(bars):
            bar.set_gid(PROFILE_GID.format(profile=profile + 1, category=category + 1))
        base = base + table[:, category]
    axes.set_xticks(positions, labels=prepared.profile_names)
    axes.set_xlim(-0.6, len(positions) - 0.4)
    axes.set_ylim(0, 1)
    axes.yaxis.grid(True, color="#d6dde3", linewidth=0.7)
    axes.set_axisbelow(True)
    legend = axes.legend(title=prepared.response, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    # Names of profiles, categories and columns are literal text: a dollar sign never starts a formula.
    for text in (axes.title, axes.xaxis.label, axes.yaxis.label, legend.get_title(), *legend.get_texts(),
                 *axes.get_xticklabels()):
        text.set_parse_math(False)
    if max((len(name) for name in prepared.profile_names), default=0) * len(positions) > 60:
        axes.tick_params(axis="x", labelrotation=30)
        for text in axes.get_xticklabels():
            text.set_ha("right")
    return chart


def build_result(prepared, fit):
    tables = {COEFFICIENTS: coefficient_table(prepared, fit), THRESHOLDS: threshold_table(prepared, fit),
              MODEL_FIT: model_fit_table(prepared, fit)}
    fitted = probabilities(fit, prepared.design)
    tables[FITTED] = fitted_table(prepared, fit, fitted)
    if prepared.references:
        tables[REFERENCES] = pd.DataFrame.from_dict(prepared.references, orient="index", columns=["Reference"])
    chart = None
    if len(prepared.profile_names):
        profile = probabilities(fit, prepared.profile_designs)
        tables[PROFILE_TABLE] = profile_table(prepared, profile)
        if prepared.show_graph:
            chart = figure(prepared, profile)
    return Result(tables, chart)


def ordinal_logit(frame, options):
    """The analysis: read and check the recipe, fit once, write the sheets and the optional figure."""
    prepared = check_options(frame, options)
    return build_result(prepared, fit_model(prepared))
