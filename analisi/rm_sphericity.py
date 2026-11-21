"""Sphericity corrections for the omnibus tests of Repeated measures ANOVA (0.93, Huynh–Feldt in 0.97).

The choices ``Geisser–Greenhouse``, ``Huynh-Feldt`` and ``Lower bound`` of ``Sphericity correction`` accept one or
two within-subject factors in a complete, balanced design. For one factor ``Geisser–Greenhouse`` is the historical
one-way table. For two factors every effect (A, B and A:B) gets its own epsilon from the covariance, between
subjects, of that effect's contrast scores. Huynh–Feldt and the lower bound start from the same contrast scores:
the lower bound is 1/d for an effect of contrast dimension d, and Huynh–Feldt is the estimate that corrects the
bias of the Greenhouse–Geisser epsilon.

The sums of squares, mean squares, F ratios and error strata are those of the uncorrected analysis
(``inference.repeated_measures_anova``). Only the degrees of freedom of the F test and its p value change.
This module holds what is new: the design check that names a dialog field, the contrast scores, the epsilons,
the ``Sphericity`` sheet and the wording of the errors. It does not import ``inference``.
"""
import re
from itertools import product
from math import prod

import numpy as np
import pandas as pd
from scipy.linalg import helmert

from .field_error import FieldError
from .i18n import translate_message, ui

METHOD = "Repeated measures ANOVA"
FIELD = "Sphericity correction"
NONE, CANONICAL, LEGACY = "None", "Geisser–Greenhouse", "Geisser–Greenhouse (one-way)"
HF, LOWER = "Huynh-Feldt", "Lower bound"
# The legacy value stays readable in saved recipes. The dialog offers it only when a recipe already uses it.
CHOICES = (NONE, CANONICAL, HF, LOWER)
# Tokens of ``inference.repeated_measures_anova(correction=...)``.
GG, GG_ONE_WAY, HUYNH_FELDT, LOWER_BOUND = "gg", "gg-one-way", "hf", "lower-bound"
CORRECTIONS = {NONE: None, CANONICAL: GG, LEGACY: GG_ONE_WAY, HF: HUYNH_FELDT, LOWER: LOWER_BOUND}
# The two estimated choices: they report the epsilon they apply, and the ``Sphericity`` sheet also exists for one
# factor. The name is the one shown in the ``Correction`` column.
ESTIMATED = {HUYNH_FELDT: HF, LOWER_BOUND: LOWER}
STRICT = (GG, HUYNH_FELDT, LOWER_BOUND)
SHEET = "Sphericity"
COLUMNS = ["Term", "Contrast dimension", "GG ε", "F", "F df1", "F df2", "p", "Uncorrected p"]
ESTIMATED_COLUMNS = ["Term", "Correction", "Contrast dimension", "GG ε", "Applied epsilon", "F", "F df1", "F df2",
                     "p", "Uncorrected p", "Note"]
# A Huynh–Feldt denominator closer to zero than this share of n − 1 cannot be told from the singular case.
_SINGULAR = 64 * float(np.finfo(float).eps)
# A raw estimate this close to a limit is rounding, not a limited estimate worth a note.
_LIMIT_TOLERANCE = 1e-12
RESPONSE, FACTORS, SUBJECT = "Response", "Factors", "Subject"
ERROR_FIELDS = (FIELD, RESPONSE, FACTORS, SUBJECT)

# English sentences raised by this module. i18n registers translations under "rm.sphericity.error.".
ERRORS = {
    "choice": "Choose None, Geisser–Greenhouse, Huynh-Feldt or Lower bound.",
    "legacy_two": "The one-way Geisser–Greenhouse choice applies to a single Factor. "
                  "Choose Geisser–Greenhouse to correct two Factors.",
    "factors": "Choose one or two within-subject Factors.",
    "roles": "Column {column} is chosen for more than one role. Response, Factors and Subject need different columns.",
    "empty": "There are no rows with data in the selected columns.",
    "subject_blank": "Rows without a Subject: {count}. Every measurement needs a subject.",
    "factor_empty": "{factor} has no levels: the column is empty in every row.",
    "factor_blank": "Rows without a level of {factor}: {count}. Every measurement needs a level of each Factor.",
    "nonnumeric": "Response must be numeric and finite, but {value} was found for subject {subject} "
                  "(non-numeric or infinite values in all: {count}).",
    "blank": "Response is empty for subject {subject} in {cell} (empty values in all: {count}). Each subject "
             "needs one numeric Response in each of the {cells} combinations of {factors}; nothing is imputed "
             "or excluded pairwise.",
    "levels": "{factor} needs at least two levels, but the data have {count}.",
    "subjects": "At least two subjects are needed, but the data have {count}.",
    "duplicate": "Subject {subject} has {count} measurements for {cell}. Each subject needs exactly one Response "
                 "in each of the {cells} combinations of {factors}.",
    "incomplete": "Subject {subject} has no measurement for {cell} (subjects with missing cells: {count}). "
                  "Each subject needs one Response in each of the {cells} combinations of {factors}. "
                  "Between-subject and mixed designs are not supported.",
    "structure": "Every subject lacks some of the {cells} combinations of {factors}; for example subject {subject} "
                 "has no measurement for {cell}. Each subject needs one Response in each combination, so check "
                 "the Factors for levels that occur only for some subjects. "
                 "Between-subject and mixed designs are not supported.",
    "scale": "Response values are too large to analyse reliably (largest magnitude {value}). Divide the Response "
             "by a constant, for example by changing the units, and run the analysis again.",
    "small": "Differences between the measurements of a subject are too small to analyse reliably (largest "
             "difference {value}). Multiply the Response by a constant, for example by changing the units, "
             "and run the analysis again.",
    "residual": "No measurable subject-by-effect residual variance for \"{term}\". Every subject shows the same "
                "pattern for this effect, so its F ratio has no error term.",
}


def format_error(error):
    """Translated sentence for an error of this module, prefixed by its field caption; else None."""
    field = getattr(error, "field", None)
    if field not in ERROR_FIELDS or not _own_sentence(str(error)):
        return None
    message = translate_message(str(error), "rm.sphericity.error.")
    caption = ui(field)
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def _own_sentence(text):
    """True when ``text`` is one of the sentences of ``ERRORS`` (placeholders filled in)."""
    for template in ERRORS.values():
        pattern = ".+?".join(re.escape(piece) for piece in re.split(r"\{[a-z_]+\}", template))
        if re.fullmatch(pattern, text, flags=re.DOTALL):
            return True
    return False


def correction(options, factor_count):
    """Token for ``repeated_measures_anova`` from the recipe; a field error for an unknown or unusable choice."""
    value = options.get(FIELD, NONE)
    if value not in CORRECTIONS:
        raise FieldError(FIELD, ERRORS["choice"])
    if value == LEGACY and factor_count != 1:
        raise FieldError(FIELD, ERRORS["legacy_two"])
    if value in (CANONICAL, HF, LOWER) and factor_count not in (1, 2):
        raise FieldError(FACTORS, ERRORS["factors"])
    return CORRECTIONS[value]


def choices_for(saved):
    """Choices offered by the dialog: the legacy value joins them only when the opened recipe uses it."""
    return (*CHOICES, LEGACY) if saved.get(FIELD) == LEGACY else CHOICES


def _cell(factors, levels):
    return "; ".join(f"{name} = {level}" for name, level in zip(factors, levels, strict=True))


def check_design(frame, response, factors, subject):
    """Check a complete one- or two-factor within-subject design before the fit; field errors only.

    Every subject needs exactly one numeric, finite Response in every combination of the factor levels. Nothing
    is excluded pairwise or imputed. The array itself is built by the caller, so both sides see one layout.
    """
    factors = list(factors)
    if len(factors) not in (1, 2):
        raise FieldError(FACTORS, ERRORS["factors"])
    roles = [(RESPONSE, response), (SUBJECT, subject), *[(FACTORS, name) for name in factors]]
    seen = set()
    for field, name in roles:
        if name in seen:
            raise FieldError(field, ERRORS["roles"].format(column=name))
        seen.add(name)
    names = [name for _, name in roles]
    rows = frame.loc[:, names].dropna(how="all")
    if rows.empty:
        raise FieldError(RESPONSE, ERRORS["empty"])
    blank = rows[subject].isna()
    if blank.any():
        raise FieldError(SUBJECT, ERRORS["subject_blank"].format(count=int(blank.sum())))
    for name in factors:
        blank = rows[name].isna()
        if blank.all():
            raise FieldError(FACTORS, ERRORS["factor_empty"].format(factor=name))
        if blank.any():
            raise FieldError(FACTORS, ERRORS["factor_blank"].format(factor=name, count=int(blank.sum())))
    try:
        numbers = pd.to_numeric(rows[response], errors="coerce").astype(float)
    except (TypeError, ValueError):
        numbers = pd.Series(np.nan, index=rows.index)
    bad = (rows[response].notna() & ~np.isfinite(numbers)).to_numpy()
    if bad.any():
        first = rows.iloc[int(np.flatnonzero(bad)[0])]
        raise FieldError(RESPONSE, ERRORS["nonnumeric"].format(
            value=repr(first[response]) if isinstance(first[response], str) else str(float(first[response])),
            subject=first[subject], count=int(bad.sum())))
    levels = [rows[name].drop_duplicates().tolist() for name in factors]
    cells = prod(len(group) for group in levels)
    where = {"cells": cells, "factors": " × ".join(factors)}
    missing = numbers.isna().to_numpy()
    if missing.any():
        first = rows.iloc[int(np.flatnonzero(missing)[0])]
        raise FieldError(RESPONSE, ERRORS["blank"].format(
            subject=first[subject], cell=_cell(factors, [first[name] for name in factors]),
            count=int(missing.sum()), **where))
    for name, group in zip(factors, levels, strict=True):
        if len(group) < 2:
            raise FieldError(FACTORS, ERRORS["levels"].format(factor=name, count=len(group)))
    subjects = rows[subject].drop_duplicates().tolist()
    if len(subjects) < 2:
        raise FieldError(SUBJECT, ERRORS["subjects"].format(count=len(subjects)))
    keys = [subject, *factors]
    sizes = rows.groupby(keys, sort=False, observed=True).size()
    repeated = sizes[sizes > 1]
    if len(repeated):
        first = repeated.index[0]
        key = first if isinstance(first, tuple) else (first,)
        raise FieldError(SUBJECT, ERRORS["duplicate"].format(
            subject=key[0], cell=_cell(factors, key[1:]), count=int(repeated.iloc[0]), **where))
    per_subject = sizes.groupby(level=0, sort=False, observed=True).size()
    short = per_subject[per_subject < cells]
    if len(short):
        owner = short.index[0]
        present = set(rows.loc[(rows[subject] == owner).to_numpy(), factors].itertuples(index=False, name=None))
        absent = next(_cell(factors, combo) for combo in product(*levels) if combo not in present)
        if len(short) == len(per_subject):
            raise FieldError(FACTORS, ERRORS["structure"].format(subject=owner, cell=absent, **where))
        raise FieldError(SUBJECT, ERRORS["incomplete"].format(subject=owner, cell=absent, count=len(short), **where))


def check_scale(values):
    """A field error where the squares of the analysis would overflow or vanish.

    Overflow: |x| above half the square root of the largest float divided by the number of cells. Underflow:
    within-subject differences so small that the residual test against ε² of the total could not be told
    from zero. Ordinary data, whatever their units, never reach either limit.
    """
    peak = float(np.abs(values).max())
    limit = 0.5 * float(np.sqrt(np.finfo(float).max / values.size))
    if not np.isfinite(peak) or peak > limit:
        raise FieldError(RESPONSE, ERRORS["scale"].format(value=f"{peak:.3g}"))
    baseline = values.reshape(values.shape[0], -1)[:, 0].reshape((-1,) + (1,) * (values.ndim - 1))
    spread = float(np.abs(values - baseline).max())
    floor = 10 * float(np.sqrt(np.finfo(float).tiny)) / np.finfo(float).eps
    if 0 < spread < floor:
        raise FieldError(RESPONSE, ERRORS["small"].format(value=f"{spread:.3g}"))


def residual_error(term):
    return FieldError(RESPONSE, ERRORS["residual"].format(term=term))


def contrast_scores(within, axes):
    """Scores of every subject on an orthonormal basis of the centred space of one effect.

    ``within`` is the subjects × A × B array. For A the basis is the Helmert contrasts of A crossed with the
    constant direction of B (normalised), and the other way round for B. For A:B it is the Kronecker product of
    the two Helmert bases. Each basis row sums to zero over the cells, so a constant offset of a subject
    never reaches the scores.
    """
    subjects, a, b = within.shape
    if axes == (1,):
        return (within.sum(axis=2) / np.sqrt(b)) @ helmert(a).T
    if axes == (2,):
        return (within.sum(axis=1) / np.sqrt(a)) @ helmert(b).T
    return np.einsum("nij,ki,lj->nkl", within, helmert(a), helmert(b), optimize=True).reshape(subjects, -1)


def epsilon(scores):
    """Greenhouse–Geisser epsilon, tr(S)² / (q tr(S²)), of an n × q block of contrast scores.

    S is the covariance of the scores between subjects. The scores are rescaled by their largest magnitude so
    that no square can overflow (epsilon does not depend on the scale), and the smaller of the two Gram
    matrices (q × q or n × n, with the same nonzero eigenvalues) is used. Epsilon is limited to [1/q, 1];
    with q = 1 it is exactly 1.
    """
    count, q = scores.shape
    if q == 1:
        return 1.0
    centred = scores - scores.mean(axis=0, keepdims=True)
    peak = float(np.abs(centred).max())
    if not np.isfinite(peak) or peak == 0:
        raise residual_error("")
    centred = centred / peak
    gram = centred.T @ centred if q <= count else centred @ centred.T
    trace = float(np.trace(gram))
    return float(np.clip(trace * trace / (q * float(np.square(gram).sum())), 1 / q, 1.0))


def effect_epsilon(within, axes):
    """Contrast dimension and epsilon of the effect on ``axes`` (1-based within-subject axes of ``within``)."""
    scores = contrast_scores(within, axes)
    return scores.shape[1], epsilon(scores)


def huynh_feldt(gg, dimension, subjects):
    """Unlimited Huynh–Feldt estimate, (n d εGG − 2) / [d (n − 1 − d εGG)]; None where the formula has no value.

    It is the form used by the stats package of R (``sphericity`` in ``mlm.R``, where n is the residual
    degrees of freedom n − 1). ``d εGG`` cannot exceed the rank of the contrast scores, which is at most n − 1,
    so the denominator is never negative; it vanishes when n − 1 ≤ d and the scores have equal nonzero
    eigenvalues, for example with two subjects, where the quotient is 0/0. That case, and a denominator lost in
    rounding, have no estimate.
    """
    inner = subjects - 1 - dimension * gg
    if not np.isfinite(inner) or inner <= _SINGULAR * (subjects - 1):
        return None
    return float((subjects * dimension * gg - 2) / (dimension * inner))


def applied_epsilon(token, gg, dimension, subjects):
    """Epsilon that an estimated choice applies to one effect, and the note for the ``Sphericity`` sheet.

    ``token`` is ``HUYNH_FELDT`` or ``LOWER_BOUND``; ``gg`` the Greenhouse–Geisser epsilon of the effect,
    ``dimension`` its contrast dimension d and ``subjects`` the number n of subjects. The result is
    ``(epsilon, note)``. Epsilon is always in [1/d, 1]: the lower bound is 1/d, Huynh–Feldt is limited to that
    interval and the note says when it was. With d = 1 epsilon is exactly 1 and the test is not corrected.
    Where Huynh–Feldt cannot be computed the epsilon is None and the note gives the reason, so that the other
    effects keep their results.
    """
    if dimension == 1:
        return 1.0, "One contrast (d = 1): epsilon is exactly 1, so the F test is not corrected."
    if token == LOWER_BOUND:
        return 1 / dimension, f"Lower bound 1/d with d = {dimension}."
    raw = huynh_feldt(gg, dimension, subjects)
    if raw is None:
        return None, (f"Huynh–Feldt is undefined for this effect: its denominator n − 1 − d εGG is zero "
                      f"(n = {subjects} subjects, d = {dimension}, εGG = {gg:.6g}), so epsilon, the corrected "
                      "degrees of freedom and p are not reported. Geisser–Greenhouse and Lower bound are not "
                      "affected.")
    if raw > 1 + _LIMIT_TOLERANCE:
        return 1.0, f"Huynh–Feldt estimate {raw:.6g} is above 1 and was limited to 1: no correction of the test."
    if raw < 1 / dimension * (1 - _LIMIT_TOLERANCE):
        return 1 / dimension, (f"Huynh–Feldt estimate {raw:.6g} is below 1/d and was limited to 1/d = "
                               f"{1 / dimension:.6g}.")
    return float(np.clip(raw, 1 / dimension, 1.0)), ""


def sphericity_table(rows, *, estimated=False):
    """The ``Sphericity`` sheet from one dict per effect, in the order A, B, A:B.

    ``estimated`` selects the columns of Huynh-Feldt and Lower bound, which also name the correction, the epsilon
    applied and a note.
    """
    return pd.DataFrame(rows, columns=ESTIMATED_COLUMNS if estimated else COLUMNS)
