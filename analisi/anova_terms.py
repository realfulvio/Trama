"""Choice of the terms of a multifactor ANOVA model (0.83).

``Term selection`` is ``Full hierarchy`` (the default, and the only behaviour before 0.83) or
``Selected terms``. Full hierarchy keeps ``Interaction order`` and the historical Patsy fit, so a
recipe saved before 0.83 carries neither new key and gives the same sheets, statistics and figures.

``Model terms`` is a JSON list of terms, each a list of factor names, for example
``[["A dose"], ["B group"], ["A dose", "B group"]]``. The names are literal. They are never
Patsy expressions. The fit has an intercept and the sum-to-zero (deviation) contrast columns of
every selected main effect, and for each interaction the row-wise products of its factors'
columns. Only the selected terms are built. The last level of a factor, in sorted order of its text,
is the reference that carries −1.

Strong hierarchy is enforced and nothing is added silently: a two-way interaction needs both of
its factors, a three-way interaction needs its three factors and its three two-way interactions.
Terms are sorted by order, then by the position of their factors in ``Factors``; the factors of a
term follow ``Factors`` too, so ``B group:A dose`` and ``A dose:B group`` are the same term.

Factors that are chosen but appear in no term stay out of the fit and out of the selection of
complete rows. A row is used when the response and every factor of the model are present.

Type III sums of squares remove only the columns of one term from the fitted design and divide the
increase of the residual sum of squares by the columns removed. With strong hierarchy and sum
coding that is the usual Type III test of the term. Estimated marginal means for comparisons use
the same design: a mean for one level of a compared factor is the average of the design rows over
the levels of the other factors of the model, each combination counted once. Factors outside the
model do not enter that average.
"""
from itertools import combinations
import json
from math import prod
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .field_error import FieldError
from .i18n import tr, translate_message, ui

TERM_SELECTION = "Term selection"
MODEL_TERMS = "Model terms"
FULL = "Full hierarchy"
SELECTED = "Selected terms"
CHOICES = (FULL, SELECTED)
TERM_LIST = "Model term list"  # Dialog kind of the Model terms field: a list of lists of factor names.
SHEET = "Model terms"
FACTORS = "Factors"
COMPARE_FIELD = "Compare marginal means by"
CELLS_FIELD = "Cell comparison factors"
WITHIN_FIELD = "Within factors (simple effects)"
CONTROL_FIELD = "Control level(s), separated by |"
MAX_FACTORS, MAX_ORDER = 8, 3
EFFECT_KINDS = {1: "Main effect", 2: "Two-way interaction", 3: "Three-way interaction"}
_BUDGET = 4_000_000

# English sentences raised by this module. i18n registers translations under "anova.terms.error.".
ERRORS = {
    "empty": "Select at least one model term.",
    "empty_term": "A model term needs at least one factor.",
    "type": "Model terms must be a list of terms, and each term a list of factor names.",
    "unknown": "Model term {term} uses {factor}, which is not among the selected Factors.",
    "repeat": "Model term {term} repeats a factor.",
    "order": "Model term {term} has more than three factors. Interactions go up to order 3.",
    "duplicate": "Model term {term} is listed more than once.",
    "hierarchy": "Model term {term} needs {missing} in the model (strong hierarchy).",
    "factors": "Select from one to eight Factors.",
    "selection": "Choose Full hierarchy or Selected terms.",
    "levels": "Factor {factor} must have between 2 and 128 levels in the rows used by the model.",
    "size": "The selected model is too large or has no residual degrees of freedom.",
    "rank": "The selected model cannot be identified. Check empty cells and redundant terms.",
    "variance": "The fitted model has no measurable residual variance.",
    "absent": "{factor} is not in the model terms, so it cannot be used here.",
    "absent_many": "{factor} are not in the model terms, so they cannot be used here.",
}


# Fields whose errors this module words. The dialog shows the translated sentence after the caption.
ERROR_FIELDS = (TERM_SELECTION, MODEL_TERMS, FACTORS, COMPARE_FIELD, CELLS_FIELD, WITHIN_FIELD)


def format_error(error):
    """Translated sentence for an error of this module, prefixed by its field caption; else None."""
    field = getattr(error, "field", None)
    if field not in ERROR_FIELDS:
        return None
    message = translate_message(str(error), "anova.terms.error.")
    caption = ui(field)
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def label(term):
    """Keep reserved names and literal colons distinguishable in result labels."""
    return ":".join(json.dumps(name, ensure_ascii=False) if name == "Residual" or any(c in name for c in ':"')
                    else name for name in term)


def selected(options):
    """True for ``Selected terms``. An absent key is Full hierarchy; any other text is a field error."""
    mode = options.get(TERM_SELECTION, FULL)
    if mode is None or mode == "":
        return False
    if not isinstance(mode, str) or mode not in CHOICES:
        raise FieldError(TERM_SELECTION, ERRORS["selection"])
    return mode == SELECTED


def selection(options):
    """The canonical terms of a ``Selected terms`` recipe, or None for Full hierarchy."""
    if not selected(options):
        return None
    return canonical_terms(options.get(MODEL_TERMS), options.get(FACTORS))


def check_options(options):
    """Cheap request check for the dialog: mode, list shape, names, duplicates and hierarchy."""
    return selection(options)


def _factor_list(factors):
    if (not isinstance(factors, (list, tuple)) or not 1 <= len(factors) <= MAX_FACTORS
            or any(not isinstance(name, str) for name in factors) or len(set(factors)) != len(factors)):
        raise FieldError(FACTORS, ERRORS["factors"])
    return list(factors)


def canonical_terms(raw, factors):
    """Validate a ``Model terms`` list against ``Factors``; return a tuple of tuples of factor names.

    Raises FieldError on ``Model terms``. The result is ordered by order, then by factor position.
    """
    factors = _factor_list(factors)
    if not isinstance(raw, (list, tuple)):
        raise FieldError(MODEL_TERMS, ERRORS["type"])
    if not raw:
        raise FieldError(MODEL_TERMS, ERRORS["empty"])
    position = {name: index for index, name in enumerate(factors)}
    seen, ordered = set(), []
    for term in raw:
        if not isinstance(term, (list, tuple)) or any(not isinstance(name, str) for name in term):
            raise FieldError(MODEL_TERMS, ERRORS["type"])
        if not term:
            raise FieldError(MODEL_TERMS, ERRORS["empty_term"])
        shown = label(term)
        for name in term:
            if name not in position:
                raise FieldError(MODEL_TERMS, ERRORS["unknown"].format(term=shown, factor=name))
        if len(set(term)) != len(term):
            raise FieldError(MODEL_TERMS, ERRORS["repeat"].format(term=shown))
        if len(term) > MAX_ORDER:
            raise FieldError(MODEL_TERMS, ERRORS["order"].format(term=shown))
        canonical = tuple(sorted(term, key=position.__getitem__))
        if canonical in seen:
            raise FieldError(MODEL_TERMS, ERRORS["duplicate"].format(term=label(canonical)))
        seen.add(canonical)
        ordered.append(canonical)
    ordered.sort(key=lambda term: (len(term), [position[name] for name in term]))
    for term in ordered:
        needed = [part for size in range(1, len(term)) for part in combinations(term, size)]
        missing = [label(part) for part in needed if part not in seen]
        if missing:
            raise FieldError(MODEL_TERMS, ERRORS["hierarchy"].format(term=label(term), missing=", ".join(missing)))
    return tuple(ordered)


def prerequisites(terms, factors):
    """Lower-order terms that the hierarchy needs and ``terms`` lacks, in model order."""
    position = {name: index for index, name in enumerate(factors)}
    have = {tuple(sorted(term, key=position.__getitem__)) for term in terms}
    missing = {part for term in have for size in range(1, len(term))
               for part in combinations(term, size) if part not in have}
    return sorted(missing, key=lambda term: (len(term), [position[name] for name in term]))


def full_terms(factors, order):
    """Every term of the Full hierarchy of the given order, in model order."""
    factors = list(factors)
    return tuple(choice for size in range(1, order + 1) for choice in combinations(factors, size))


def active_factors(factors, terms):
    """The factors that appear in at least one term, in the order of ``Factors``."""
    used = {name for term in terms for name in term}
    return [name for name in factors if name in used]


def summary(response, terms):
    """One readable line for the dialog and the documentation: ``Y = A + B + A:B``."""
    return f"{response} = {' + '.join(label(term) for term in terms)}"


def check_comparison_controls(options, factors, terms):
    """A comparison or within factor outside the model terms names its own control.

    Every offending name is listed, so two missing factors never read like one.
    """
    inside = set(active_factors(factors, terms))
    compare = options.get(CELLS_FIELD) or options.get(COMPARE_FIELD)
    field = CELLS_FIELD if options.get(CELLS_FIELD) else COMPARE_FIELD
    asked = ((field, [compare] if isinstance(compare, str) else list(compare or ())),
             (WITHIN_FIELD, list(options.get(WITHIN_FIELD) or ())))
    for name, wanted in asked:
        absent = [factor for factor in dict.fromkeys(wanted) if factor not in inside]
        if absent:
            message = ERRORS["absent" if len(absent) == 1 else "absent_many"].format(factor=", ".join(absent))
            raise FieldError(name, message)


class TermDesign:
    """Sum-coded design of the selected terms. Built from internal keys, never from formulas.

    ``to_numpy`` gives the matrix of the fit. ``design_info.term_name_slices`` has the same
    ``C(factor0, Sum):C(factor1, Sum)`` names as the Patsy design, so the Type III code is shared.
    ``rows`` builds the design rows of any table of the same internal keys and fitted levels.
    """

    def __init__(self, keys, levels, terms, columns):
        self.keys, self.levels = list(keys), dict(levels)
        self.terms = tuple(tuple(term) for term in terms)
        self.matrix, slices = self._build(columns)
        self.design_info = SimpleNamespace(term_name_slices=slices)

    def to_numpy(self):
        return self.matrix

    def _block(self, key, values):
        levels = self.levels[key]
        codes = pd.Index(levels).get_indexer(np.asarray(values, dtype=object))
        if (codes < 0).any():
            raise ValueError("A factor level is not in the fitted model.")
        onehot = np.zeros((len(codes), len(levels)))
        onehot[np.arange(len(codes)), codes] = 1.0
        return onehot[:, :-1] - onehot[:, -1:]

    def _build(self, columns):
        count = len(next(iter(columns.values())))
        blocks = {key: self._block(key, columns[key]) for key in self.keys}
        parts, slices, start = [np.ones((count, 1))], {"Intercept": slice(0, 1)}, 1
        for term in self.terms:
            block = blocks[term[0]]
            for key in term[1:]:
                block = (block[:, :, None] * blocks[key][:, None, :]).reshape(count, -1)
            parts.append(block)
            slices[":".join(f"C({key}, Sum)" for key in term)] = slice(start, start + block.shape[1])
            start += block.shape[1]
        return np.column_stack(parts), slices

    def rows(self, table):
        """Design rows of a DataFrame with one column per internal key."""
        return self._build({key: table[key].to_numpy() for key in self.keys})[0]


def _fail(key, **values):
    return FieldError(MODEL_TERMS, ERRORS[key].format(**values))


def fit_model(frame, response, factors, terms):
    """One least-squares fit of the selected terms: ``(data, keys, names, design, beta, error, df)``.

    Same shape as the full-hierarchy fit. ``data`` holds the response and the internal factor
    columns of the model's factors only (in the order of ``Factors``), so a row is complete when
    those are present. Problems of the model itself are FieldErrors on ``Model terms``, so the
    dialog can reopen on that field.
    """
    from .stats import complete

    terms = canonical_terms(terms, factors)
    used = active_factors(list(factors), terms)
    data = complete(frame, [response], used)
    keys = [f"factor{index}" for index in range(len(used))]
    data.columns = ["response", *keys]
    for name, key in zip(used, keys):
        data[key] = data[key].astype(str)
        if not 2 <= data[key].nunique() <= 128:
            raise _fail("levels", factor=name)
    levels = {key: sorted(data[key].unique()) for key in keys}
    key_of = dict(zip(used, keys))
    coded = [tuple(key_of[name] for name in term) for term in terms]
    coefficient_count = 1 + sum(prod(len(levels[key]) - 1 for key in term) for term in coded)
    if coefficient_count >= len(data) or coefficient_count * len(data) > _BUDGET:
        raise _fail("size")
    design = TermDesign(keys, levels, coded, {key: data[key].to_numpy() for key in keys})
    y = data["response"].to_numpy()
    x = design.to_numpy()
    beta, rss, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < x.shape[1]:
        raise _fail("rank")
    df = len(y) - rank
    error = float(rss[0])
    total = float(np.sum((y - y.mean())**2))
    if total <= 0 or error <= np.finfo(float).eps * total:
        raise _fail("variance")
    names = [f"C({key}, Sum)" for key in keys]
    return data, keys, names, design, beta, error, df


def terms_table(terms, used, data):
    """The ``Model terms`` sheet: one row per selected term with its order, df and kind of effect.

    ``used`` lists the model's factor names in the order of ``Factors``. ``data`` is the frame of
    the fit, whose factor columns follow that same order.
    """
    counts = {name: data[key].nunique() for name, key in zip(used, data.columns[1:])}
    rows = [{"Term": label(term), "Order": len(term), "df": int(prod(counts[name] - 1 for name in term)),
             "Effect": EFFECT_KINDS[len(term)]} for term in terms]
    return pd.DataFrame(rows).set_index("Term")
