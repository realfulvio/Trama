"""Type of the sums of squares of a multifactor ANOVA: Type I, Type II or Type III.

``Sums of squares`` is ``Type III`` (the default, and the only behaviour before this option),
``Type I`` or ``Type II``. A recipe without the key is Type III. Any other value is a FieldError on
``Sums of squares``. The choice applies to Full hierarchy and to Selected terms.

All three types read the one sum-coded design that the analysis fits once: the Patsy design of the
Full hierarchy or the ``TermDesign`` of Selected terms. A reduced model is that design with some
term blocks left out. It is never rebuilt from a formula, so the coding of an interaction, and the
hypothesis it tests, are the same in every type. The residual sum of squares, residual df and mean
square error that divide every F are those of the full fit, for every type.

* **Type I** (sequential). The terms enter in the model order: intercept, then by number of factors,
  then by the position of their factors in ``Factors``. The sum of squares of a term is the drop of the
  residual sum of squares when it is added to the intercept and the terms before it. Changing the order
  of ``Factors`` can change the result of an unbalanced design. With the centered response, the sums of
  squares of the terms and the residual sum of squares add up to the centered total.
* **Type II**. For a term T the smaller model M0 has the intercept and every other term that does not
  contain T as a proper subset of its factors, so ``A`` in ``A + B + C + A:B`` is tested after ``B`` and
  ``C``, and ``C`` after ``A``, ``B`` and ``A:B``. M1 is M0 with T. The sum of squares is RSS(M0) minus
  RSS(M1), and the df is the rank of M1 minus the rank of M0. It tests T without the interactions that
  contain it (the marginality principle).
* **Type III** keeps the historical code of ``stats._anova_type_iii``.

Both new types use a QR factorization of the reduced design with the centered response as an extra
last column. The entries of its last column are the coordinates of the response along the orthogonal
directions, so a block sum of squares is a sum of squares of coordinates, with no subtraction of two
large residual sums. Type I uses one factorization. Type II uses one per term, with the terms to
test placed last. Subsets of the columns of a full-rank design are full rank, so the df of a term is
its number of columns, checked here against the diagonal of the factorization.

A term is identified by the tuple of the positions of its factors in the model, never by a string, so
factor names that contain ``:``, ``|`` or spaces cannot be confused with the separators of the model.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .i18n import translate_message, ui

KEY = "Sums of squares"
TYPE_I, TYPE_II, TYPE_III = "Type I", "Type II", "Type III"
CHOICES = (TYPE_III, TYPE_I, TYPE_II)  # the first one is the default shown in the dialog
SHEETS = {TYPE_I: "ANOVA (type I)", TYPE_II: "ANOVA (type II)", TYPE_III: "ANOVA (type III)"}

# English sentences raised by this module. i18n registers translations under "anova.ss.error.".
ERRORS = {
    "kind": "Choose Type I, Type II or Type III sums of squares.",
    "numeric": "The sums of squares could not be computed reliably for this model. "
               "Check the scale of the response and the model terms.",
}
# A sum of squares must match the residual sums of the same fit within this fraction of the centered total,
# plus the rounding noise of the uncentered response (a large offset costs digits before any fit starts).
_TOLERANCE = 1e-7
_ROUNDING = 32 * np.finfo(float).eps


def format_error(error):
    """Translated sentence for an error of this module, prefixed by its field caption; else None."""
    if getattr(error, "field", None) != KEY:
        return None
    message = translate_message(str(error), "anova.ss.error.")
    caption = ui(KEY)
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def sums_of_squares(options):
    """The canonical type of a recipe. An absent key is Type III; any other unknown value is a field error."""
    value = options.get(KEY, TYPE_III)
    if value is None or (isinstance(value, str) and value == ""):
        return TYPE_III
    if not isinstance(value, str) or value not in CHOICES:
        raise FieldError(KEY, ERRORS["kind"])
    return value


def _fail():
    return FieldError(KEY, ERRORS["numeric"])


def design_terms(design, keys):
    """The terms of a fitted design as ``(positions, columns)``, in model order, without the intercept.

    ``positions`` are the indices of the term's factors in ``keys`` (the internal ``factor0``, ``factor1``
    names of the fit), ascending. ``columns`` are the column indices of its block in the design matrix.
    Both the Patsy design and ``TermDesign`` name a block ``C(factor0, Sum):C(factor1, Sum)``.
    """
    index = {f"C({key}, Sum)": position for position, key in enumerate(keys)}
    found = []
    for name, bounds in design.design_info.term_name_slices.items():
        if name == "Intercept":
            continue
        positions = tuple(sorted(index[part] for part in name.split(":")))
        found.append((positions, np.arange(bounds.start, bounds.stop)))
    found.sort(key=lambda item: (len(item[0]), item[0]))
    return found


def _coordinates(x, centered, columns):
    """Orthogonal coordinates of the response along the columns, in the order given, and the residual norm.

    ``R[:p, p]`` of the factorization of ``[X | y]`` holds the coordinates of ``y`` along the successive
    orthogonalized columns of X. A column that adds nothing to those before it would show as a near-zero
    diagonal entry, which a full-rank design cannot have.
    """
    columns = np.asarray(columns)
    p = len(columns)
    r = np.linalg.qr(np.column_stack([x[:, columns], centered]), mode="r")
    diagonal = np.abs(np.diag(r)[:p])
    if p and diagonal.min() <= np.finfo(float).eps * max(len(centered), p) * diagonal.max():
        raise _fail()
    return r[:p, p], float(r[p, p]**2)


def _type_one(x, centered, intercept, terms, total, error, tolerance):
    """One factorization with the terms in model order: the coordinates of each block give its sum of squares."""
    order = np.concatenate([intercept, *(columns for _, columns in terms)])
    coordinates, residual = _coordinates(x, centered, order)
    sums, start = [], len(intercept)
    for _, columns in terms:
        sums.append(float(np.sum(coordinates[start:start + len(columns)]**2)))
        start += len(columns)
    # The centered response is orthogonal to the intercept, so the terms and the residual rebuild the total.
    if abs(sum(sums) + residual - total) > tolerance or abs(residual - error) > tolerance:
        raise _fail()
    return sums


def _type_two(x, centered, intercept, terms, total, error, tolerance):
    """For each term T: the other terms that do not contain T go first, T last. T's block gives its sum of squares."""
    sums = []
    for positions, columns in terms:
        inside = set(positions)
        before = [other for other, _ in terms if other != positions and not inside < set(other)]
        smaller = [cols for other, cols in terms if other in before]
        order = np.concatenate([intercept, *smaller, columns])
        coordinates, residual = _coordinates(x, centered, order)
        sums.append(float(np.sum(coordinates[len(order) - len(columns):]**2)))
        # M1 is nested in the full model, so its residual sum of squares cannot be below the full model's.
        if residual < error - tolerance:
            raise _fail()
    return sums


def anova_table(kind, data, factors, design, error, df, *, term_label=":".join):
    """Table and summary of a Type I or Type II ANOVA from the full fit, in the shape of ``_anova_type_iii``.

    Type III stays in ``stats._anova_type_iii``; any other ``kind`` is a field error on ``Sums of squares``.

    ``factors`` names the factors of the fit in the order of the internal columns of ``data``.
    ``term_label`` makes the label of a term from its factor names.
    """
    if kind not in (TYPE_I, TYPE_II):
        raise FieldError(KEY, ERRORS["kind"])
    x, y = design.to_numpy(), data["response"].to_numpy()
    centered = y - y.mean()
    total = np.sum(centered**2)
    keys = list(data.columns[1:])
    blocks = design_terms(design, keys)
    bounds = design.design_info.term_name_slices["Intercept"]
    intercept = np.arange(bounds.start, bounds.stop)
    tolerance = _TOLERANCE * float(total) + _ROUNDING * float(y @ y)
    sums = (_type_one if kind == TYPE_I else _type_two)(x, centered, intercept, blocks, float(total), error, tolerance)
    rows = []
    for (positions, columns), ss in zip(blocks, sums):
        numerator_df = len(columns)
        ms = ss / numerator_df
        statistic = ms / (error / df)
        rows.append({"Term": term_label(factors[position] for position in positions),
                     "SS": ss, "df": numerator_df, "MS": ms, "F": statistic,
                     "p": stats.f.sf(statistic, numerator_df, df), "Eta²": ss / total,
                     "Partial eta²": ss / (ss + error)})
    rows.append({"Term": "Residual", "SS": error, "df": df, "MS": error / df})
    table = pd.DataFrame(rows).set_index("Term")
    return table, {"N": len(y), "df": df, "SST": float(total), "SSE": error}
