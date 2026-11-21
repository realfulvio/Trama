"""File readers and a restricted evaluator for calculated columns."""
import ast
from collections.abc import Mapping
from copy import copy, deepcopy
import csv
from dataclasses import dataclass, field
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from functools import lru_cache, reduce
from graphlib import CycleError, TopologicalSorter
from io import StringIO
import json
from math import factorial, isfinite
import operator
import re
from secrets import randbits
import tokenize
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .info import InfoSheet, MAX_INFO_SHEETS, info_contexts, validate_info_sheets
from .analysis_chain import AnalysisGraph, MAX_ANALYSIS_NODES, ResultSource, valid_analysis_id
from .analysis_labels import validate_labels
from .distribution_formulas import DISTRIBUTION_FUNCTIONS, argument_count_message
from .formula_special import SPECIAL_FORMULA_FUNCTIONS
from .formula_windows import WINDOW_CLAUSES, WINDOW_FUNCTION, _missing, lower_window_clauses, worksheet_statistic

MAX_ENTRY = 32 * 1024 * 1024
MAX_CELLS = 2_000_000
MAX_COLUMNS = 512
EDITABLE_PRISM_XY = "Prism editable XY"
EDITABLE_PRISM_COLUMNS = "Prism editable columns"
EDITABLE_PRISM_STACKS = "Prism editable PDF stacks"
EDITABLE_PRISM_EMF = "Prism editable EMF XY"
EDITABLE_PRISM_FIXED_VALUES = {EDITABLE_PRISM_COLUMNS, EDITABLE_PRISM_STACKS, EDITABLE_PRISM_EMF}


def _member(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_ENTRY:
        raise ValueError(f"Entry exceeds size limit: {name}")
    return archive.read(info).decode("utf-8-sig")


def _headers(names):
    used = set()
    result = []
    for index, name in enumerate(names, 1):
        base = str(name).strip() if name is not None else ""
        base = base or f"Column {index}"
        candidate, repeat = base, 2
        while candidate in used:
            candidate = f"{base} ({repeat})"
            repeat += 1
        used.add(candidate)
        result.append(candidate)
    return result


def decimal_comma(value):
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d*,\d+(?:[eE][+-]?\d+)?", value.strip()):
        return value.replace(",", ".")
    return value


def _table(headers, rows, kinds=None, *, max_columns=MAX_COLUMNS, decimal_mark="."):
    if not 1 <= len(headers) <= max_columns or len(headers) * len(rows) > MAX_CELLS:
        raise ValueError("Table has an unsupported size.")
    if any(len(row) > len(headers) for row in rows):
        raise ValueError("Table contains rows wider than the column metadata.")
    frame = pd.DataFrame([row + [None] * (len(headers) - len(row)) for row in rows],
                         columns=_headers(headers), dtype=object)
    for index, name in enumerate(frame.columns):
        kind = kinds[index] if kinds else None
        if kind == "mixed":
            continue
        original = frame[name].replace("", np.nan)
        padded_id = kind is None and any(
            isinstance(value, str) and re.fullmatch(r"[+-]?0[0-9]+", value)
            for value in original
        )
        if padded_id or kind in {"text", "categorical", "label", "date", "datetime"}:
            frame[name] = original.astype("string")
            continue
        numbers = original.map(decimal_comma) if decimal_mark == "," else original
        converted = pd.to_numeric(numbers, errors="coerce", dtype_backend="numpy_nullable")
        if converted.notna().sum() == original.notna().sum():
            frame[name] = converted
        else:
            frame[name] = original.astype("string")
    return frame


def delimited_reader(handle, suffix, delimiter=None, *, strict=False):
    if delimiter is not None:
        return csv.reader(handle, delimiter=delimiter, strict=strict)
    first = handle.read(8192)
    handle.seek(0)
    try:
        dialect = csv.Sniffer().sniff(first, delimiters=",;\t")
    except csv.Error:
        dialect = "excel-tab" if suffix == ".tsv" else "excel"
    return csv.reader(handle, dialect, strict=strict)


def load_tables(path, *, restore_prism=False, info_sheets=None):
    path = Path(path)
    if path.suffix.lower() in {".prism", ".prismt", ".pzt", ".pzf", ".pzfx", ".xml"}:
        from .prism_import import load_prism

        return load_prism(path, restore=restore_prism, info_sheets=info_sheets)
    if path.stat().st_size > MAX_ENTRY:
        raise ValueError("Input file exceeds 32 MiB.")
    if path.suffix.lower() == ".xlsx":
        with ZipFile(path) as archive:
            if sum(member.file_size for member in archive.infolist()) > 4 * MAX_ENTRY:
                raise ValueError("Workbook exceeds the decompressed size limit.")
        from openpyxl import load_workbook

        tables = {}
        with path.open("rb") as source:
            workbook = load_workbook(source, read_only=True, data_only=True, keep_links=False)
            try:
                for sheet in workbook.worksheets:
                    if (sheet.max_column or 1) * (sheet.max_row or 1) > MAX_CELLS:
                        raise ValueError(f'Worksheet "{sheet.title}" exceeds the table size limit.')
                    rows = sheet.iter_rows(values_only=True)
                    header = next(rows, ())
                    if not header:
                        continue
                    contents = []
                    width = len(header)
                    for row in rows:
                        width = max(width, len(row))
                        if (len(contents) + 1) * width > MAX_CELLS:
                            raise ValueError(f'Worksheet "{sheet.title}" exceeds the table size limit.')
                        contents.append(list(row))
                    tables[sheet.title] = _table(list(header) + [None] * (width - len(header)), contents)
            finally:
                workbook.close()
        return tables
    if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
        raise ValueError("Choose a CSV, TSV, XLSX or supported Prism project.")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = delimited_reader(handle, path.suffix.lower())
        return {path.stem: _table(next(reader, []), list(reader),
                                  decimal_mark="," if reader.dialect.delimiter == ";" else ".")}


def _remainder(left, right):
    result = np.remainder(left, right)
    return np.where(np.isfinite(left) & np.isfinite(right), result, np.nan)


BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: _remainder}
COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Is: operator.eq, ast.IsNot: operator.ne, ast.Gt: operator.gt,
           ast.Lt: operator.lt, ast.GtE: operator.ge, ast.LtE: operator.le}
def _conditional(condition, yes, no):
    # Object arrays avoid an allocation proportional to text width times row count.
    if any(np.asarray(value).dtype.kind in {"O", "U", "S", "T"} for value in (yes, no)):
        yes, no = np.asarray(yes, dtype=object), np.asarray(no, dtype=object)
    return np.where(condition, yes, no)


def _numeric_present(values):
    return pd.to_numeric(pd.Series(np.atleast_1d(values)), errors="coerce").dropna().to_numpy(dtype=float)


def _average_if(source, criterion, values):
    source, values = np.asarray(source), np.asarray(values)
    if source.ndim != 1 or source.shape != values.shape or np.ndim(criterion) != 0:
        raise ValueError("AVERAGEIF requires two equal-length columns and one criterion.")
    if source.dtype.kind in {"f", "i", "u"} and isinstance(criterion, str):
        match = re.fullmatch(r"(<=|>=|<>|=|<|>)?\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", criterion)
        if not match:
            raise ValueError("AVERAGEIF needs a numeric criterion for a numeric column.")
        operators = {"=": np.equal, "<>": np.not_equal, "<": np.less,
                     ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal}
        mask = np.isfinite(source) & operators[match[1] or "="](source, float(match[2]))
    else:
        mask = source == criterion
    filtered = _numeric_present(values[mask])
    return filtered.mean() if len(filtered) else np.nan


def _aggregate(fn, values):
    numbers = _numeric_present(values)
    return fn(numbers) if len(numbers) else np.nan


def _formula_numbers(value):
    array = np.asarray(value)
    if array.ndim and array.dtype.kind in "OSUT":
        array = pd.to_numeric(array, errors="coerce")
    return np.asarray(array, dtype=float)


def _add_present(left, right):
    return np.where(np.isnan(left), right, np.where(np.isnan(right), left, left + right))


def _aggregate_rows(column_operation, row_operation, values):
    if len(values) == 1:
        return _aggregate(column_operation, values[0])
    numbers = map(_formula_numbers, values)
    result = next(numbers)
    result = np.where(np.isfinite(result), result, np.nan)
    for number in numbers:
        result = row_operation(result, np.where(np.isfinite(number), number, np.nan))
    return result


_FACTORIALS = np.array([float(factorial(n)) for n in range(171)])


def _factorial(values):
    numbers = _formula_numbers(values)
    valid = (numbers >= 0) & (numbers <= 170) & (numbers == np.trunc(numbers))
    index = np.where(valid, numbers, 0).astype(np.intp)
    return np.where(valid, _FACTORIALS[index], np.nan)


def _round_decimal(value, places):
    if not isfinite(value) or not isfinite(places) or places != np.trunc(places):
        return np.nan
    if places < -308:
        return 0.0
    number = Decimal(str(value))
    if places >= -number.as_tuple().exponent:
        return value
    quantum = Decimal((0, (1,), -int(places)))
    return float(number.quantize(quantum))


_round_rows = np.frompyfunc(_round_decimal, 2, 1)


def _round(values, places=None):
    if places is None:
        return np.round(values)
    with localcontext(Context(prec=340, rounding=ROUND_HALF_UP)):
        return np.asarray(_round_rows(_formula_numbers(values), _formula_numbers(places)), dtype=float)


def _numeric_column(values):
    if np.ndim(values) != 1:
        raise ValueError("Use a column or a row-wise expression for CENTER, STANDARDIZE, ZSCORE or RANK.")
    numbers = pd.to_numeric(pd.Series(values), errors="coerce")
    return numbers.where(np.isfinite(numbers))


def _center_column(values, *, standardize=False):
    numbers = _numeric_column(values).to_numpy(dtype=float, na_value=np.nan)
    observed = numbers[np.isfinite(numbers)]
    if not len(observed):
        return numbers
    _, exponent = np.frexp(np.max(np.abs(observed)))
    # Scaling before the mean avoids overflow and does not round away the first offset.
    centered = np.ldexp(numbers, -exponent) - np.ldexp(observed[0], -exponent)
    centered -= np.nanmean(centered)
    if not standardize:
        return np.ldexp(centered, exponent)
    deviation = np.nanstd(centered, ddof=1) if len(observed) > 1 else 0.0
    return centered / deviation if deviation else np.full_like(centered, np.nan)


COLUMN_FORMULA_FUNCTIONS = {
    "CENTER": (1, _center_column),
    "STANDARDIZE": (1, lambda values: _center_column(values, standardize=True)),
    "ZSCORE": (1, lambda values: _center_column(values, standardize=True)),
    "RANK": (1, lambda values: _numeric_column(values).rank(method="average").to_numpy(dtype=float)),
}


def _blank_cell(value):
    return _missing(value) or (isinstance(value, (float, np.floating)) and not isfinite(value))


_check_blank = np.frompyfunc(_blank_cell, 1, 1)
_RAW_FORMULA_ARGUMENTS = {"ISBLANK", "IS_DEFINED", "CONCATENATE"}


def _is_blank(values):
    return np.asarray(_check_blank(values), dtype=bool)


def _concatenated_cell(value):
    if isinstance(value, str):
        return value
    if _blank_cell(value):
        return ""
    if isinstance(value, (bool, np.bool_)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return str(value).removesuffix(".0")
    return str(value)


_text_cell = np.frompyfunc(_concatenated_cell, 1, 1)


def _concatenate(*values):
    return reduce(np.add, (np.asarray(_text_cell(value), dtype=object) for value in values))


ELEMENTWISE_FORMULA_FUNCTIONS = {
    **SPECIAL_FORMULA_FUNCTIONS,
    **DISTRIBUTION_FUNCTIONS,
    "ISBLANK": (1, _is_blank), "IS_DEFINED": (1, lambda values: np.logical_not(_is_blank(values))),
    "CONCATENATE": (range(2, 129), _concatenate),
    "CEIL": (1, np.ceil), "FLOOR": (1, np.floor), "INT": (1, np.trunc), "SGN": (1, np.sign),
    "ROUND": (range(1, 3), _round), "FACT": (1, _factorial),
    "SQR": (1, np.square),
    "ABS": (1, np.abs), "SQRT": (1, np.sqrt), "EXP": (1, np.exp), "LN": (1, np.log),
    "LOG": (1, np.log10), "LOG10": (1, np.log10), "LOG2": (1, np.log2), "POWER": (2, np.power),
    "LOGIT": (1, lambda p: np.log(p) - np.log1p(-p)),
    "SIN": (1, np.sin), "COS": (1, np.cos), "TAN": (1, np.tan),
    "ARCSIN": (1, np.arcsin), "ARCCOS": (1, np.arccos), "ARCTAN": (1, np.arctan),
    "ARCTAN2": (2, np.arctan2), "RAD": (1, np.deg2rad), "DEG": (1, np.rad2deg),
    "SINH": (1, np.sinh), "COSH": (1, np.cosh), "TANH": (1, np.tanh),
    "ARCSINH": (1, np.arcsinh), "ARCCOSH": (1, np.arccosh), "ARCTANH": (1, np.arctanh),
}

FUNCTIONS = {
    **ELEMENTWISE_FORMULA_FUNCTIONS, **COLUMN_FORMULA_FUNCTIONS,
    "MEAN": (1, lambda v: _aggregate(np.mean, v)),
    "AVERAGE": (1, lambda v: _aggregate(np.mean, v)),
    "SUM": (range(1, 129), lambda *v: _aggregate_rows(np.sum, _add_present, v)),
    "MIN": (range(1, 129), lambda *v: _aggregate_rows(np.min, np.fmin, v)),
    "MAX": (range(1, 129), lambda *v: _aggregate_rows(np.max, np.fmax, v)),
    "MEDIAN": (1, lambda v: _aggregate(np.median, v)),
    "COUNT": (1, lambda v: len(_numeric_present(v))),
    "AVERAGEIF": (3, _average_if), "IF": (3, _conditional),
    "AND": (range(2, 129), lambda *conditions: reduce(np.logical_and, conditions)),
    "OR": (range(2, 129), lambda *conditions: reduce(np.logical_or, conditions)),
    "NOT": (1, np.logical_not),
}


SHEET_LOGIC = {"and", "or", "not"}


def _after_operand(token):
    kind, value = token
    return (kind in {tokenize.NUMBER, tokenize.STRING} or (kind, value) == (tokenize.OP, ")")
            or kind == tokenize.NAME and value not in SHEET_LOGIC and value.upper() not in WINDOW_CLAUSES | {"BY"})


def worksheet_logic_tokens(tokens):
    """Lower logical keywords in operator positions, preserving columns and string literals."""
    insignificant = {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.ENDMARKER}
    significant = [(token.type, token.string) for token in tokens if token.type not in insignificant]
    result = []
    previous = (None, "")
    for index, (kind, value) in enumerate(significant):
        following = significant[index + 1] if index + 1 < len(significant) else (None, "")
        if kind == tokenize.NAME and value.lower() in SHEET_LOGIC:
            name = value.lower()
            after_operand = _after_operand(previous)
            if name in {"and", "or"} and after_operand:
                value = name
            elif following == (tokenize.OP, "("):
                value = name.upper()
            elif name == "not" and not after_operand and following[0] in {
                    tokenize.NAME, tokenize.NUMBER, tokenize.STRING}:
                value = name
        previous = (kind, value)
        result.append(previous)
    return result


def _formula_operators(tokens):
    result = []
    previous = (None, "")
    for kind, value in worksheet_logic_tokens(tokens):
        if kind == tokenize.OP and value == "^":
            value = "**"
        elif kind == tokenize.NAME and value.upper() == "MOD" and _after_operand(previous):
            kind, value = tokenize.OP, "%"
        elif kind == tokenize.NAME and value == "is":
            raise ValueError("Use = or <> for a worksheet comparison.")
        previous = (kind, value)
        result.append(previous)
    return result


def _worksheet_comparisons(tokens):
    """Reserve the otherwise unsupported AST identity slots for caseless = and <>."""
    result = []
    for token in tokens:
        if token == (tokenize.OP, "="):
            result.append((tokenize.NAME, "is"))
        elif token == (tokenize.OP, ">") and result and result[-1] == (tokenize.OP, "<"):
            result[-1:] = [(tokenize.NAME, "is"), (tokenize.NAME, "not")]
        else:
            result.append(token)
    return result


RANDOM_FORMULA_CALLS = {"GAUSS", "RND"}
_RANDOM_CALL_TEXT = re.compile(r"\b(?:GAUSS|RND)\s*\(", re.IGNORECASE)
_SEED_PREFIX = re.compile(r"^WITH_SEED\s*\(\s*([0-9]{1,20})\s*,", re.IGNORECASE)


def _formula_tree(expression):
    source = expression.strip().removeprefix("=").strip()
    seed = None
    if match := _SEED_PREFIX.match(source):
        seed = int(match[1])
        if seed >= 2**64 or not source.endswith(")"):
            raise ValueError("Use WITH_SEED with a whole number from 0 through 2^64 − 1 and a formula.")
        source = source[match.end():-1].strip()
    if not source or len(source) > 2048:
        raise ValueError("Enter a formula of up to 2048 characters.")
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
        window = lower_window_clauses(_formula_operators(tokens))
        tree = ast.parse(tokenize.untokenize(_worksheet_comparisons(window)), mode="eval")
    except (SyntaxError, tokenize.TokenError) as error:
        raise ValueError("Invalid formula syntax.") from error
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise ValueError("Formula is too complex.")
    return tree, seed


def formula_column_references(expression):
    """Read worksheet references without evaluating a formula on the table."""
    tree, _ = _formula_tree(expression)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    called_names = {node.func for node in calls}
    references = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node not in called_names}
    for call in calls:
        if (isinstance(call.func, ast.Name) and call.func.id.upper() == "COL" and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
            references.add(call.args[0].value)
    return references


@lru_cache(maxsize=32)
def formula_calculation_order(items):
    """Plan once per set of expressions, independent of rows and display order."""
    names = dict(items).keys()
    dependencies = {name: formula_column_references(expression) & names for name, expression in items}
    seen = set()
    for name, inputs in dependencies.items():
        if not inputs <= seen:
            break
        seen.add(name)
    else:
        return tuple(names)
    try:
        # Register the display order first so ties have a reproducible order on disk.
        graph = TopologicalSorter(dict.fromkeys(names, ()))
        for name, inputs in dependencies.items():
            graph.add(name, *inputs)
        return tuple(graph.static_order())
    except CycleError as error:
        raise ValueError("A calculated column cannot depend on itself, directly or indirectly.") from error


def seeded_formula(expression):
    """Give a stored formula an independent seed once, leaving existing seeds intact."""
    if not _RANDOM_CALL_TEXT.search(expression):
        return expression
    tree, seed = _formula_tree(expression)
    if seed is not None or not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id.upper() in RANDOM_FORMULA_CALLS for node in ast.walk(tree)):
        return expression
    source = expression.strip().removeprefix("=").strip()
    return f"=WITH_SEED({randbits(64)}, {source})"


def _random_values(name, rng, n, first, second):
    first, second = (_formula_numbers(arg) for arg in (first, second))
    finite = np.isfinite(first) & np.isfinite(second)
    if name == "GAUSS":
        return np.where(finite & (second >= 0), first + second * rng.standard_normal(n), np.nan)
    fraction = rng.random(n)
    # Interpolating between endpoints avoids overflow when upper - lower does not fit in float64.
    values = first * (1 - fraction) + second * fraction
    values = np.where(first == second, first, values)
    return np.where(finite & (second >= first), values, np.nan)


def _casefold_text(value):
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, np.ndarray) and value.dtype.kind in {"O", "U"}:
        return np.array([item.casefold() if isinstance(item, str) else item for item in value], dtype=object)
    return value


def formula(frame, expression, *, info=None):
    """Evaluate arithmetic, comparisons and whitelisted functions only."""
    tree, seed = _formula_tree(expression)
    rng = None
    def column(name, *, raw=False):
        if name not in frame:
            raise ValueError(f"Unknown column: {name}")
        data = frame[name]
        if raw:
            return data.to_numpy(dtype=object)
        if pd.api.types.is_numeric_dtype(data):
            return data.to_numpy(dtype=float, na_value=np.nan)
        return data.fillna("").astype(str).to_numpy()

    def info_value(name):
        key = name.strip().casefold()
        if info is None or key not in info:
            raise ValueError(f"Unknown Info constant: {name}")
        value = info[key]
        if value is None:
            raise ValueError(f"Ambiguous Info constant: {name}")
        number = decimal_comma(value.strip())
        if re.fullmatch(r"[+-]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", number):
            parsed = float(number)
            if isfinite(parsed):
                return parsed
        return value

    def evaluate(node, *, raw=False, filter_text=False):
        nonlocal rng
        if isinstance(node, ast.Constant) and type(node.value) in {int, float, str, bool}:
            return float(node.value) if type(node.value) in {int, float} else node.value
        if isinstance(node, ast.Name):
            return column(node.id, raw=raw)
        if isinstance(node, ast.BoolOp) and type(node.op) in {ast.And, ast.Or}:
            operation = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
            return reduce(operation, (evaluate(value, filter_text=filter_text) for value in node.values))
        if isinstance(node, ast.UnaryOp) and type(node.op) in {ast.UAdd, ast.USub, ast.Not}:
            result = evaluate(node.operand, filter_text=filter_text)
            if isinstance(node.op, ast.Not):
                return np.logical_not(result)
            return -result if isinstance(node.op, ast.USub) else +result
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            lhs = evaluate(node.left, filter_text=filter_text)
            rhs = evaluate(node.right, filter_text=filter_text)
            if isinstance(lhs, str) or isinstance(rhs, str):
                raise ValueError("Arithmetic requires numeric operands.")
            return BINARY[type(node.op)](lhs, rhs)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE:
            operation = type(node.ops[0])
            lhs = evaluate(node.left, filter_text=filter_text)
            rhs = evaluate(node.comparators[0], filter_text=filter_text)
            if filter_text or operation in {ast.Is, ast.IsNot}:
                lhs, rhs = _casefold_text(lhs), _casefold_text(rhs)
            return COMPARE[operation](lhs, rhs)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id.upper()
            if name in RANDOM_FORMULA_CALLS:
                if len(node.args) != 2:
                    raise ValueError(argument_count_message(name, range(2, 3)))
                if rng is None:
                    rng = np.random.Generator(np.random.PCG64(seed))
                return _random_values(name, rng, len(frame),
                                      *(evaluate(arg, filter_text=filter_text) for arg in node.args))
            if name == "CASE_INSENSITIVE" and len(node.args) == 1:
                return evaluate(node.args[0], raw=raw, filter_text=True)
            if name in {"COL", "INFO"} and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str):
                    return column(value, raw=raw) if name == "COL" else info_value(value)
            if name == WINDOW_FUNCTION and len(node.args) == 7:
                statistic, values, partition, condition, order, ascending, rows = node.args
                if not isinstance(statistic, ast.Constant) or not isinstance(statistic.value, str):
                    raise ValueError("Unknown worksheet statistic.")
                keys = order.elts if isinstance(order, ast.Tuple) else [order]
                directions = ascending.elts if isinstance(ascending, ast.Tuple) else [ascending]
                if len(keys) != len(directions) or not keys or any(
                        not isinstance(direction, ast.Constant) or type(direction.value) is not bool
                        for direction in directions):
                    raise ValueError("Invalid worksheet sort direction.")
                bounds = None
                if not absent(rows):
                    if not isinstance(rows, ast.Tuple) or len(rows.elts) != 2 or any(
                            not isinstance(node, ast.Constant) or (
                                node.value is not None and (type(node.value) is not int or not 0 <= node.value <= 9_999_999))
                            for node in rows.elts):
                        raise ValueError("Invalid worksheet row bounds.")
                    bounds = tuple(node.value for node in rows.elts)
                group = None if absent(partition) else evaluate(partition, raw=True, filter_text=filter_text)
                mask = None if absent(condition) else evaluate(condition, filter_text=True)
                sort_keys = [(evaluate(key, raw=True, filter_text=filter_text), direction.value)
                             for key, direction in zip(keys, directions, strict=True) if not absent(key)]
                return worksheet_statistic(statistic.value, evaluate(values, raw=True, filter_text=filter_text),
                                           group, mask, len(frame),
                                           sort_keys=sort_keys, bounds=bounds)
            if name in FUNCTIONS:
                arity, function = FUNCTIONS[name]
                supported = len(node.args) == arity if isinstance(arity, int) else len(node.args) in arity
                if supported:
                    return function(*(evaluate(arg, raw=name in _RAW_FORMULA_ARGUMENTS, filter_text=filter_text)
                                      for arg in node.args))
                if isinstance(arity, range):
                    raise ValueError(argument_count_message(name, arity))
        raise ValueError("Unsupported expression in calculated column.")

    def absent(node):
        return isinstance(node, ast.Constant) and node.value is None

    try:
        with np.errstate(all="ignore"):
            value = evaluate(tree.body)
            if np.iscomplexobj(value):
                raise ValueError("Complex values are not supported in calculated columns.")
            result = pd.Series(value, index=frame.index)
    except (TypeError, ZeroDivisionError, OverflowError, ArithmeticError) as error:
        raise ValueError("Invalid operation in calculated column.") from error
    if pd.api.types.is_numeric_dtype(result):
        result = result.replace([np.inf, -np.inf], np.nan)
    return result


def info_references(expression):
    """Return the constant names used by an already validated formula."""
    tree, _ = _formula_tree(expression)
    return {
        node.args[0].value.strip().casefold()
        for node in ast.walk(tree)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id.upper() == "INFO" and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))
    }


@dataclass
class Dataset:
    raw: pd.DataFrame
    formulas: dict[str, str] = field(default_factory=dict)
    analyses: list[tuple[str, dict]] = field(default_factory=list)
    excluded: set[tuple[int, int]] = field(default_factory=set)
    table_format: str = "multivariable"
    graph_styles: dict[int, dict] = field(default_factory=dict)
    info: Mapping[str, str | None] = field(default_factory=dict)
    analysis_ids: dict[int, str] = field(default_factory=dict)
    analysis_sources: dict[int, ResultSource] = field(default_factory=dict)
    # Literal sheet names per analysis slot. Display only: they never reach the statistical engine.
    analysis_labels: dict[int, str] = field(default_factory=dict)

    @property
    def locked_columns(self):
        if self.table_format == EDITABLE_PRISM_STACKS:
            return (0,)
        if self.table_format == EDITABLE_PRISM_COLUMNS:
            return tuple(index for index, name in enumerate(self.raw.columns) if name == "Group")
        if self.table_format == EDITABLE_PRISM_EMF:
            return tuple(index for index, name in enumerate(self.raw.columns) if name == "Series")
        return (2, 3) if self.table_format == EDITABLE_PRISM_XY else ()

    def __post_init__(self):
        self.excluded.update(tuple(value) for value in self.raw.attrs.get("excluded", []))
        self.table_format = self.raw.attrs.get("table_format", self.table_format)
        if not self.analyses:
            self.analyses = list(self.raw.attrs.get("prism_recipes", []))
            if self.analyses and not self.graph_styles:
                self.graph_styles = deepcopy(self.raw.attrs.get("prism_graph_styles", {}))
            if self.analyses and not self.analysis_ids and not self.analysis_sources:
                self.analysis_ids = dict(self.raw.attrs.get("prism_analysis_ids", {}))
                self.analysis_sources = dict(self.raw.attrs.get("prism_analysis_sources", {}))
        imported = self.raw.attrs.get("prism_formulas", {})
        imported = {name: recipe for name, recipe in imported.items() if name in self.raw}
        if imported and not self.formulas:
            kept = [column for column, name in enumerate(self.raw) if name not in imported]
            indices = {original: new for new, original in enumerate(kept)}
            self.excluded = {(row, indices[col]) for row, col in self.excluded if col in indices}
            self.raw = self.raw.iloc[:, kept].copy()
            self.raw.attrs.pop("prism_formulas")
            self.raw.attrs.pop("excluded", None)
            self.formulas = imported

    def frame(self, mask_excluded=False):
        computed = self.raw.copy()
        computed.attrs["table_format"] = self.table_format
        masked_columns = {column for _, column in self.excluded} if mask_excluded or self.formulas else set()
        for column in masked_columns:
            original = computed.iloc[:, column]
            if pd.api.types.is_integer_dtype(original):
                computed.isetitem(column, original.convert_dtypes())
        if masked_columns:
            for row, column in self.excluded:
                computed.iat[row, column] = pd.NA
        order = formula_calculation_order(tuple(self.formulas.items()))
        for name in order:
            computed[name] = formula(computed, self.formulas[name], info=self.info)
        if order != tuple(self.formulas):
            computed = computed.loc[:, [*self.raw.columns, *self.formulas]]
        if not mask_excluded:
            for column in masked_columns:
                computed.isetitem(column, self.raw.iloc[:, column])
        return computed

    def set_formula(self, name, expression):
        if not name.strip() or name in self.raw:
            raise ValueError("Choose a new column name.")
        candidate = copy(self)
        candidate.formulas = {**self.formulas, name: seeded_formula(expression)}
        candidate.frame()
        self.formulas = candidate.formulas


def _encode_cell(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isinf(value):
        return {"$number": "Infinity" if value > 0 else "-Infinity"}
    return value


def _decode_cell(value):
    if not isinstance(value, dict):
        return value
    if value == {"$number": "Infinity"}:
        return float("inf")
    if value == {"$number": "-Infinity"}:
        return float("-inf")
    raise ValueError("Invalid numeric marker in project table.")


def _project_column_kind(column):
    if pd.api.types.is_numeric_dtype(column):
        return "numeric"
    if pd.api.types.infer_dtype(column.to_numpy(dtype=object), skipna=True) in {"mixed", "mixed-integer"}:
        return "mixed"
    return "text"


def _worksheet_roles(frame):
    if "worksheet_roles" in frame.attrs:
        return frame.attrs["worksheet_roles"]
    if "prism_x" not in frame.attrs:
        return None
    columns = frame.attrs.get("prism_columns", {})
    x = [name for name in columns.get(frame.attrs["prism_x"], ()) if name in frame]
    groups = [[name for name in columns.get(uid, ()) if name in frame] for uid in frame.attrs.get("prism_y", ())]
    return {"x": x, "y": [group for group in groups if group]}


def _validated_worksheet_roles(roles, columns):
    if (not isinstance(roles, dict) or set(roles) != {"x", "y"}
            or not isinstance(roles["x"], list) or not isinstance(roles["y"], list)
            or any(not isinstance(group, list) or not group for group in roles["y"])):
        raise ValueError("Invalid saved worksheet roles.")
    names = [*roles["x"], *(name for group in roles["y"] for name in group)]
    if (any(not isinstance(name, str) or name not in columns for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("Invalid saved worksheet column references.")
    return roles


class ProjectTables(dict):
    """Keep Info sheets attached for callers using the original table-only API."""

    def __init__(self, info_sheets):
        super().__init__()
        self.info_sheets = tuple(info_sheets)


def validate_analysis_links(tables):
    """Validate the entire saved dependency graph before applying or writing it."""
    nodes, dependencies = [], {}
    linked = any(dataset.analysis_sources for dataset in tables.values())
    if linked:
        from .pairwise_graph import read_section
    total = 0
    for data in tables.values():
        total += len(data.analyses)
        for mapping in (data.analysis_ids, data.analysis_sources):
            if not isinstance(mapping, dict) or any(type(slot) is not int or
                    not 0 <= slot < len(data.analyses) for slot in mapping):
                raise ValueError("Invalid saved analysis identity or source slot.")
        if set(data.analysis_sources) - set(data.analysis_ids):
            raise ValueError("A linked analysis is missing its persistent identity.")
        for slot, identifier in data.analysis_ids.items():
            valid_analysis_id(identifier)
            nodes.append((identifier, data.analysis_sources.get(slot)))
            if linked:
                settings, _ = read_section(data.analyses[slot][1])
                if settings and settings['slot'] < len(data.analyses):
                    if settings['slot'] not in data.analysis_ids:
                        raise ValueError('A linked comparison source is missing its persistent identity.')
                    dependencies[identifier] = [data.analysis_ids[settings['slot']]]
    if total > MAX_ANALYSIS_NODES:
        raise ValueError("The project exceeds the analysis node budget.")
    return AnalysisGraph(nodes, dependencies=dependencies)


def _analysis_slots(value, count):
    if not isinstance(value, dict):
        raise ValueError("Invalid saved analysis metadata.")
    result = {}
    for slot, record in value.items():
        if (not isinstance(slot, str) or not slot.isdecimal() or str(int(slot)) != slot
                or not 0 <= int(slot) < count):
            raise ValueError("Invalid saved analysis metadata slot.")
        result[int(slot)] = record
    return result


def project_document(tables, *, layouts=(), info_sheets=None):
    """The JSON document of a .alab project, validated as ``save_project`` writes it. Pure: reads its arguments only,
    so a detached copy of a project can be serialised away from the GUI thread (Qt recovery copies)."""
    from dataclasses import asdict

    if len(tables) > 256:
        raise ValueError("A project supports up to 256 data tables.")
    if len(layouts) > 128:
        raise ValueError("A project supports up to 128 layouts.")
    if info_sheets is None:
        info_sheets = getattr(tables, "info_sheets", ())
    validate_analysis_links(tables)
    for dataset in tables.values():
        validate_labels(dataset.analysis_labels, len(dataset.analyses))
    linked = any(dataset.analysis_sources or len(dataset.analyses) > 256 for dataset in tables.values())
    data = {"version": 3 if linked else 2, "tables": [], "layouts": [asdict(layout) for layout in layouts]}
    if info_sheets:
        validate_info_sheets(info_sheets, tables)
        records = []
        for sheet in info_sheets:
            record = asdict(sheet)
            if not sheet.note_styles:
                del record["note_styles"]
            records.append(record)
        data["info_sheets"] = records
    contexts = info_contexts(info_sheets)
    for title, dataset in tables.items():
        raw = dataset.raw
        if not 1 <= len(raw.columns) <= MAX_CELLS or raw.size > MAX_CELLS:
            raise ValueError("A project table exceeds the size limit.")
        constants = contexts.get(title, contexts[None])
        for expression in dataset.formulas.values():
            if missing := sorted(name for name in info_references(expression) if constants.get(name) is None):
                raise ValueError(f"Missing or ambiguous Info constant for {title}: {', '.join(missing)}.")
        order = formula_calculation_order(tuple(dataset.formulas.items()))
        record = {
            "title": title,
            "columns": list(raw.columns),
            "kinds": [_project_column_kind(raw[name]) for name in raw],
            "rows": [[_encode_cell(value) for value in row] for row in raw.itertuples(index=False, name=None)],
            "formulas": [(name, dataset.formulas[name]) for name in order],
            "analyses": dataset.analyses,
            "excluded": sorted(dataset.excluded),
            "table_format": dataset.table_format,
            "graph_styles": dataset.graph_styles,
        }
        if order != tuple(dataset.formulas):
            record["formula_order"] = list(dataset.formulas)
        if dataset.analysis_ids:
            record["analysis_ids"] = dataset.analysis_ids
        if dataset.analysis_sources:
            record["analysis_sources"] = {slot: asdict(source) for slot, source in dataset.analysis_sources.items()}
        if dataset.analysis_labels:
            record["analysis_labels"] = dict(sorted(dataset.analysis_labels.items()))
        roles = _worksheet_roles(raw)
        if roles is not None:
            record["worksheet_roles"] = _validated_worksheet_roles(roles, raw.columns)
        data["tables"].append(record)
    return data


def project_bytes(tables, *, layouts=(), info_sheets=None):
    """The bytes ``save_project`` writes for these tables, without touching the disk."""
    data = json.dumps(project_document(tables, layouts=layouts, info_sheets=info_sheets), ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_ENTRY:
        raise ValueError("The project exceeds the 32 MiB limit.")
    return data


def save_project(path, tables, *, layouts=(), info_sheets=None):
    import os
    from tempfile import NamedTemporaryFile

    path = Path(path)
    data = project_document(tables, layouts=layouts, info_sheets=info_sheets)
    tmp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            tmp = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if tmp.stat().st_size > MAX_ENTRY:
            raise ValueError("The project exceeds the 32 MiB limit.")
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def load_workspace(path, *, include_info=False):
    from .layout_geometry import AUTO_PAPER, WHITE
    from .presentation import Layout, validated_style

    path = Path(path)
    if path.stat().st_size > MAX_ENTRY:
        raise ValueError("Project file exceeds 32 MiB.")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj["version"] not in (1, 2, 3) or len(obj["tables"]) > 256:
        raise ValueError("Unsupported project version or size.")
    stored_info = obj.get("info_sheets", [])
    if (not isinstance(stored_info, list) or len(stored_info) > MAX_INFO_SHEETS
            or any(not isinstance(record, dict) or "uid" not in record for record in stored_info)):
        raise ValueError("Invalid Info sheet list.")
    try:
        sheets = [InfoSheet(**record) for record in stored_info]
    except TypeError as error:
        raise ValueError("Invalid saved Info sheet.") from error
    contexts = info_contexts(sheets)
    result = ProjectTables(sheets)
    for table in obj["tables"]:
        rows = [[_decode_cell(value) for value in row] for row in table["rows"]]
        data = Dataset(_table(table["columns"], rows, table["kinds"], max_columns=MAX_CELLS),
                       info=contexts.get(table["title"], contexts[None]))
        for row, col in table.get("excluded", []):
            if type(row) is not int or type(col) is not int or not (0 <= row < len(data.raw) and 0 <= col < len(data.raw.columns)):
                raise ValueError("Invalid excluded cell position.")
            data.excluded.add((row, col))
        data.table_format = table.get("table_format", "multivariable")
        if "worksheet_roles" in table:
            data.raw.attrs["worksheet_roles"] = _validated_worksheet_roles(table["worksheet_roles"], data.raw.columns)
        for name, expression in table["formulas"]:
            data.set_formula(name, expression)
        if "formula_order" in table:
            order = table["formula_order"]
            if (not isinstance(order, list) or len(order) != len(data.formulas)
                    or not all(isinstance(name, str) for name in order) or set(order) != data.formulas.keys()):
                raise ValueError("Invalid saved formula column order.")
            data.formulas = {name: data.formulas[name] for name in order}
        entries = table.get("analyses", [])
        limit = MAX_ANALYSIS_NODES if obj["version"] == 3 else 256
        if len(entries) > limit or any(not isinstance(method, str) or not isinstance(options, dict)
                                    for method, options in entries):
            raise ValueError("Invalid saved analysis settings.")
        data.analyses = [(method, options) for method, options in entries]
        data.analysis_ids = _analysis_slots(table.get("analysis_ids", {}), len(entries))
        sources = _analysis_slots(table.get("analysis_sources", {}), len(entries))
        if sources and obj["version"] != 3:
            raise ValueError("Linked analyses require project format version 3.")
        data.analysis_labels = validate_labels(_analysis_slots(table.get("analysis_labels", {}), len(entries)),
                                               len(entries)) if "analysis_labels" in table else {}
        try:
            data.analysis_sources = {slot: ResultSource(**source) for slot, source in sources.items()}
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid saved result-input reference.") from error
        for index, style in table.get("graph_styles", {}).items():
            if not index.isdecimal() or not 0 <= int(index) < len(data.analyses):
                raise ValueError("Graph style references an unknown analysis.")
            data.graph_styles[int(index)] = validated_style(style)
        if table["title"] in result:
            raise ValueError("Duplicate data table title.")
        result[table["title"]] = data
    validate_analysis_links(result)
    stored_layouts = obj.get("layouts", [])
    if len(stored_layouts) > 128:
        raise ValueError("A project supports up to 128 layouts.")
    layouts = []
    for record in stored_layouts:
        panels = [tuple(ref) for ref in record["panels"]]
        layout = Layout(record["name"], record["columns"], panels,
                        record.get("paper", AUTO_PAPER), record.get("background", WHITE))
        if any(title not in result or index >= len(result[title].analyses) for title, index in panels):
            raise ValueError("Layout references an unknown analysis.")
        layouts.append(layout)
    validate_info_sheets(sheets, result)
    return (result, layouts, sheets) if include_info else (result, layouts)


def load_project(path):
    return load_workspace(path)[0]
