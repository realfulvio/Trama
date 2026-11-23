"""References that the worksheet formula editor can insert."""
from dataclasses import dataclass
from inspect import signature
from unicodedata import combining, normalize

from pandas.api.types import is_bool_dtype, is_numeric_dtype

from .data import FUNCTIONS, RANDOM_FORMULA_CALLS
from .distribution_formulas import DISTRIBUTION_FUNCTIONS
from .formula_windows import CONDITIONAL_CALLS, WINDOW_CALLS
from .grid_headings import column_label
from .i18n import tr


@dataclass(frozen=True)
class FormulaReference:
    name: str
    text: str
    detail: str
    letter: str = ""
    open_arguments: bool = False

    @property
    def label(self):
        return f"{self.letter} · {self.name}" if self.letter else self.name


def variable_references(dataset):
    results = []
    for index, name in enumerate(dataset.columns):
        if name in dataset.formulas:
            kind = "calculated"
        else:
            dtype = dataset.raw[name].dtype
            kind = "logical" if is_bool_dtype(dtype) else "numeric" if is_numeric_dtype(dtype) else "text"
        results.append(FormulaReference(name, f"COL({name!r})", tr(f"worksheet.formula.kind.{kind}"),
                                        column_label(index)))
    return results


_ARGUMENTS = {
    "ARCTAN2": "y, x", "POWER": "x, exponent", "ROUND": "x, digits",
    "IF": "condition, if_true, if_false", "AVERAGEIF": "column, criterion, values",
    "AND": "condition1, condition2, …", "OR": "condition1, condition2, …", "NOT": "condition",
    "SUM": "value1, value2, …", "MIN": "value1, value2, …", "MAX": "value1, value2, …",
    "CONCATENATE": "text1, text2, …", "COL": "name", "INFO": "name",
    "RND": "lower, upper", "GAUSS": "mean, sd", "BETA": "a, b", "IBETA": "a, b, x",
    "IGAMMA": "shape, x", "IGAMMAC": "shape, x", "HYPGEOMETRICM": "a, b, x",
    "HYPGEOMETRICU": "a, b, x", "HYPGEOMETRICF": "a, b, c, x",
    **dict.fromkeys(("BESSELJ", "BESSELY", "BESSELI", "BESSELK"), "order, x"),
    **dict.fromkeys(CONDITIONAL_CALLS, "value, condition"),
}


def function_references():
    arities = (dict.fromkeys(WINDOW_CALLS | {"COL", "INFO"}, 1)
               | dict.fromkeys(RANDOM_FORMULA_CALLS | CONDITIONAL_CALLS.keys(), 2)
               | {name: arity for name, (arity, _) in FUNCTIONS.items()})
    results = []
    for name in sorted(arities):
        arity = arities[name]
        if name in DISTRIBUTION_FUNCTIONS:
            arguments = ", ".join(signature(DISTRIBUTION_FUNCTIONS[name][1]).parameters)
        else:
            arguments = _ARGUMENTS.get(name, "x")
        detail = f"{name}({arguments})"
        if isinstance(arity, range) and len(arity) > 1:
            detail += " · " + tr("worksheet.formula.arity", minimum=arity.start, maximum=arity.stop - 1)
        if name in WINDOW_CALLS or name in CONDITIONAL_CALLS:
            detail += "\n" + tr("worksheet.formula.window_hint")
        results.append(FormulaReference(name, f"{name}()", detail, open_arguments=True))
    return results


def _fold(text):
    return "".join(char for char in normalize("NFKD", text.casefold()) if not combining(char))


def matching_references(entries, query, *, exclude=None):
    """Search literal column names and letters, showing an exact letter first."""
    needle = _fold(query.strip())
    matched = [entry for entry in entries if entry.name != exclude
               and (needle in _fold(entry.name) or (entry.letter and needle in entry.letter.casefold()))]
    if needle:
        matched.sort(key=lambda entry: entry.letter.casefold() != needle)
    return matched
