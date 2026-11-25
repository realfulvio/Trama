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
from .category_order import CATEGORY_ORDER_VERSION, WORKSHEET_ORDERS, keep_source_columns, validated_orders
from .variable_types import VARIABLE_TYPES, validated_types
from .distribution_formulas import DISTRIBUTION_FUNCTIONS, argument_count_message
from .formula_special import SPECIAL_FORMULA_FUNCTIONS
from .formula_windows import WINDOW_CLAUSES, WINDOW_FUNCTION, _missing, lower_window_clauses, worksheet_statistic
from .grid_headings import column_label
from .worksheet_appearance import background_records, paint_cells, read_backgrounds
from .worksheet_number_format import (assign_formats, column_records, position_records, read_column_formats,
                                      read_position_formats)
from .legacy_project_metadata import LEGACY_METADATA_VERSION, saved_analysis, saved_name, uses_import_metadata

MAX_ENTRY = 32 * 1024 * 1024
MAX_CELLS = 2_000_000
MAX_COLUMNS = 512
EDITABLE_LEGACY_XY = "Imported editable XY"
EDITABLE_LEGACY_COLUMNS = "Imported editable columns"
EDITABLE_LEGACY_STACKS = "Imported editable PDF stacks"
EDITABLE_LEGACY_EMF = "Imported editable EMF XY"
EDITABLE_LEGACY_FIXED_VALUES = {EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_STACKS, EDITABLE_LEGACY_EMF}


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


def load_tables(path, *, restore_legacy=False, info_sheets=None, initial_sheet=None):
    path = Path(path)
    if path.suffix.lower() in {".prism", ".prismt", ".pzt", ".pzf", ".pzfx", ".xml"}:
        from .legacy_import import load_legacy

        return load_legacy(path, restore=restore_legacy, info_sheets=info_sheets, initial_sheet=initial_sheet)
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
        raise ValueError("Choose a CSV, TSV, XLSX or supported legacy project.")
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


def _bind_worksheet_letters(expression, columns):
    """Resolve worksheet letters once, alongside the existing name-based syntax."""
    names = set(columns)
    aliases = {column_label(index): name for index, name in enumerate(columns)}
    source = expression.strip().removeprefix("=").strip()
    try:
        tokens = worksheet_logic_tokens(tokenize.generate_tokens(StringIO(source).readline))
    except (SyntaxError, tokenize.TokenError) as error:
        raise ValueError("Invalid formula syntax.") from error
    result = []
    previous = (None, "")
    for index, (kind, value) in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        letter = value.upper()
        if (kind == tokenize.NAME and value not in names and letter in aliases
                and following != (tokenize.OP, "(") and value not in SHEET_LOGIC
                and not (letter == "BY" and previous[1].upper() == "ORDER")
                and not (letter == "MOD" and _after_operand(previous))):
            result.extend([(tokenize.NAME, "COL"), (tokenize.OP, "("),
                           (tokenize.STRING, repr(aliases[letter])), (tokenize.OP, ")")])
        else:
            result.append((kind, value))
        previous = (kind, value)
    return "=" + tokenize.untokenize(result).strip() if result != tokens else expression


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


def formula_column_references(expression, *, worksheet_columns=None):
    """Read worksheet references without evaluating a formula on the table."""
    if worksheet_columns is not None:
        expression = _bind_worksheet_letters(expression, worksheet_columns)
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
    column_order: tuple[str, ...] | None = None

    cell_backgrounds: dict[tuple[int, str], str] = field(default_factory=dict)
    result_backgrounds: dict[int, dict[str, dict[tuple[int, int], str]]] = field(default_factory=dict)
    # Display-only number formats: per column name on the data, per analysis slot, result sheet and column
    # position on the results. Replaced, never mutated, so undo snapshots and recovery copies can share them.
    number_formats: dict[str, dict] = field(default_factory=dict)
    result_number_formats: dict[int, dict[str, dict[int, dict]]] = field(default_factory=dict)

    @property
    def displayed_backgrounds(self):
        positions = {name: index for index, name in enumerate(self.columns)}
        return {(row, positions[name]): color for (row, name), color in self.cell_backgrounds.items()}

    def set_background(self, box, color):
        columns = self.columns
        self.cell_backgrounds = paint_cells(self.cell_backgrounds, box, (len(self.raw), len(columns)), color, columns)

    @property
    def displayed_number_formats(self):
        """Worksheet position → format, for the grids."""
        if not self.number_formats:
            return {}
        positions = {name: index for index, name in enumerate(self.columns)}
        return {positions[name]: spec for name, spec in self.number_formats.items() if name in positions}

    def set_number_format(self, names, spec):
        """Show the named columns with ``spec``; ``None`` or Automatic restores the usual display."""
        columns = set(self.columns)
        if any(name not in columns for name in names):
            raise ValueError("A number format references an unknown column.")
        self.number_formats = assign_formats(self.number_formats, names, spec)

    def set_result_number_format(self, slot, name, positions, spec):
        sheets = self.result_number_formats.get(slot, {})
        current = sheets.get(name, {})
        changed = assign_formats(current, positions, spec)
        if changed is current:
            return
        sheets = {**sheets, name: changed} if changed else {key: value for key, value in sheets.items() if key != name}
        self.result_number_formats = ({**self.result_number_formats, slot: sheets} if sheets else
                                      {key: value for key, value in self.result_number_formats.items()
                                       if key != slot})

    def set_result_background(self, slot, name, box, shape, color):
        sheets = self.result_backgrounds.get(slot, {})
        current = sheets.get(name, {})
        changed = paint_cells(current, box, shape, color)
        if changed is current:
            return
        sheets = {**sheets, name: changed} if changed else {key: value for key, value in sheets.items() if key != name}
        self.result_backgrounds = ({**self.result_backgrounds, slot: sheets} if sheets else
                                   {key: value for key, value in self.result_backgrounds.items() if key != slot})

    @property
    def columns(self):
        return self.column_order if self.column_order is not None else (*self.raw.columns, *self.formulas)

    @property
    def source_indices(self):
        """For each worksheet column, its raw index or None for a formula."""
        if self.column_order is None:
            return (*range(len(self.raw.columns)), *(None for _ in self.formulas))
        indices = {name: index for index, name in enumerate(self.raw.columns)}
        return tuple(indices.get(name) for name in self.column_order)

    def source_span(self, left, stop):
        indices = self.source_indices[left:stop]
        if indices and len(indices) == stop - left and None not in indices:
            return indices[0], indices[-1] + 1
        return None

    @property
    def worksheet_excluded(self):
        if not self.excluded or self.column_order is None:
            return self.excluded
        indices = {source: column for column, source in enumerate(self.source_indices)}
        return {(row, indices[source]) for row, source in self.excluded}

    @property
    def locked_columns(self):
        if self.table_format == EDITABLE_LEGACY_STACKS:
            return (0,)
        if self.table_format == EDITABLE_LEGACY_COLUMNS:
            return tuple(index for index, name in enumerate(self.raw.columns) if name == "Group")
        if self.table_format == EDITABLE_LEGACY_EMF:
            return tuple(index for index, name in enumerate(self.raw.columns) if name == "Series")
        return (2, 3) if self.table_format == EDITABLE_LEGACY_XY else ()

    def __post_init__(self):
        self.excluded.update(tuple(value) for value in self.raw.attrs.get("excluded", []))
        self.table_format = self.raw.attrs.get("table_format", self.table_format)
        if not self.analyses:
            self.analyses = list(self.raw.attrs.get("legacy_recipes", []))
            if self.analyses and not self.graph_styles:
                self.graph_styles = deepcopy(self.raw.attrs.get("legacy_graph_styles", {}))
            if self.analyses and not self.analysis_ids and not self.analysis_sources:
                self.analysis_ids = dict(self.raw.attrs.get("legacy_analysis_ids", {}))
                self.analysis_sources = dict(self.raw.attrs.get("legacy_analysis_sources", {}))
        imported = self.raw.attrs.get("legacy_formulas", {})
        imported = {name: recipe for name, recipe in imported.items() if name in self.raw}
        if imported and not self.formulas:
            imported_order = tuple(self.raw.columns)
            kept = [column for column, name in enumerate(self.raw) if name not in imported]
            indices = {original: new for new, original in enumerate(kept)}
            self.excluded = {(row, indices[col]) for row, col in self.excluded if col in indices}
            self.raw = self.raw.iloc[:, kept].copy()
            keep_source_columns(self.raw)
            self.raw.attrs.pop("legacy_formulas")
            self.raw.attrs.pop("excluded", None)
            self.formulas = imported
            if imported_order != (*self.raw.columns, *self.formulas):
                self.column_order = imported_order

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
        if not mask_excluded:
            for column in masked_columns:
                computed.isetitem(column, self.raw.iloc[:, column])
        if self.column_order is not None or order != tuple(self.formulas):
            computed = computed.loc[:, list(self.columns)]
        return computed

    def set_formula(self, name, expression):
        if not name.strip() or name in self.raw:
            raise ValueError("Choose a new column name.")
        candidate = copy(self)
        candidate.formulas = {**self.formulas, name: seeded_formula(expression)}
        if self.column_order is not None and name not in self.formulas:
            candidate.column_order = (*self.column_order, name)
        candidate.frame()
        self.formulas, self.column_order = candidate.formulas, candidate.column_order

    def can_enter_formula(self, column):
        return self.table_format == "multivariable" and 0 <= column < len(self.columns)

    def column_has_values(self, column):
        source = self.source_indices[column]
        return source is not None and self.raw.iloc[:, source].notna().any()

    def set_worksheet_formula(self, column, expression, *, replace_values=False):
        """Create or edit a calculated variable at the selected worksheet position."""
        if not self.can_enter_formula(column):
            raise ValueError("Select a variable in a multiple-variables table.")
        order = self.columns
        name, source = order[column], self.source_indices[column]
        expression = _bind_worksheet_letters(expression, order)
        if source is None:
            self.set_formula(name, expression)
            return
        if len(self.raw.columns) == 1:
            raise ValueError("Keep at least one source column in a worksheet with formulas.")
        if not replace_values and self.column_has_values(column):
            raise ValueError("Confirm replacement of the existing values before creating a formula.")

        candidate = copy(self)
        candidate.raw = self.raw.drop(columns=name)
        keep_source_columns(candidate.raw)
        if "worksheet_roles" in candidate.raw.attrs:
            roles = candidate.raw.attrs["worksheet_roles"]
            groups = [[member for member in group if member != name] for group in roles["y"]]
            candidate.raw.attrs["worksheet_roles"] = {
                "x": [member for member in roles["x"] if member != name],
                "y": [group for group in groups if group],
            }
        candidate.excluded = {(row, index - (index > source)) for row, index in self.excluded if index != source}
        candidate.column_order = None
        candidate.set_formula(name, expression)
        candidate.formulas = {column_name: candidate.formulas[column_name] for column_name in order
                              if column_name in candidate.formulas}
        candidate.column_order = order if order != candidate.columns else None

        self.raw, self.excluded = candidate.raw, candidate.excluded
        self.formulas, self.column_order = candidate.formulas, candidate.column_order

    def can_freeze_worksheet_formula(self, column):
        return self.can_enter_formula(column) and self.columns[column] in self.formulas

    def freeze_worksheet_formula(self, column):
        """Replace a calculated column with its current values at the same position."""
        if not self.can_freeze_worksheet_formula(column):
            raise ValueError("Select a calculated column.")
        order = self.columns
        name = order[column]
        width = len(self.raw.columns) + 1
        if width > MAX_CELLS or len(self.raw) * width > MAX_CELLS:
            raise ValueError("A project table exceeds the size limit.")

        values = self.frame()[name]
        position = sum(index is not None for index in self.source_indices[:column])
        raw = self.raw.copy()
        raw.insert(position, name, values)
        formulas = {key: expression for key, expression in self.formulas.items() if key != name}
        excluded = {(row, index + (index >= position)) for row, index in self.excluded}
        self.raw, self.formulas, self.excluded = raw, formulas, excluded
        self.column_order = order if order != (*raw.columns, *formulas) else None


def _validated_column_order(order, source_columns, formulas):
    if (not isinstance(order, list) or not all(isinstance(name, str) for name in order)
            or [name for name in order if name not in formulas] != list(source_columns)
            or [name for name in order if name in formulas] != list(formulas)):
        raise ValueError("Invalid saved worksheet column order.")
    return tuple(order)


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
    if "legacy_x" not in frame.attrs:
        return None
    columns = frame.attrs.get("legacy_columns", {})
    x = [name for name in columns.get(frame.attrs["legacy_x"], ()) if name in frame]
    groups = [[name for name in columns.get(uid, ()) if name in frame] for uid in frame.attrs.get("legacy_y", ())]
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
        if uses_import_metadata(dataset.table_format, dataset.analyses):
            data["version"] = max(data["version"], LEGACY_METADATA_VERSION)
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
        if dataset.cell_backgrounds:
            record["cell_backgrounds"] = background_records(dataset.cell_backgrounds)
        if dataset.result_backgrounds:
            record["result_backgrounds"] = {
                slot: {name: background_records(colors) for name, colors in sorted(sheets.items())}
                for slot, sheets in sorted(dataset.result_backgrounds.items())
            }
        if formats := column_records(dataset.number_formats, dataset.columns):
            record["number_formats"] = formats
        if dataset.result_number_formats:
            record["result_number_formats"] = {
                slot: {name: position_records(formats) for name, formats in sorted(sheets.items())}
                for slot, sheets in sorted(dataset.result_number_formats.items())
            }
        if order != tuple(dataset.formulas):
            record["formula_order"] = list(dataset.formulas)
        if dataset.column_order is not None:
            record["column_order"] = list(dataset.column_order)
        if dataset.analysis_ids:
            record["analysis_ids"] = dataset.analysis_ids
        if dataset.analysis_sources:
            record["analysis_sources"] = {slot: asdict(source) for slot, source in dataset.analysis_sources.items()}
        if dataset.analysis_labels:
            record["analysis_labels"] = dict(sorted(dataset.analysis_labels.items()))
        if orders := raw.attrs.get(WORKSHEET_ORDERS):
            record[WORKSHEET_ORDERS] = validated_orders(orders, raw.columns)
            data["version"] = CATEGORY_ORDER_VERSION
        if types := raw.attrs.get(VARIABLE_TYPES):
            record[VARIABLE_TYPES] = validated_types(types, raw.columns)
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
    version = obj["version"]
    if version not in (1, 2, 3, LEGACY_METADATA_VERSION, CATEGORY_ORDER_VERSION) or len(obj["tables"]) > 256:
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
        table_format = table.get("table_format", "multivariable")
        if not isinstance(table_format, str):
            raise ValueError("Invalid saved table format.")
        data.table_format = saved_name(table_format)
        if VARIABLE_TYPES in table:
            data.raw.attrs[VARIABLE_TYPES] = validated_types(table[VARIABLE_TYPES], data.raw.columns)
        if "worksheet_roles" in table:
            data.raw.attrs["worksheet_roles"] = _validated_worksheet_roles(table["worksheet_roles"], data.raw.columns)
        if WORKSHEET_ORDERS in table:
            if version < CATEGORY_ORDER_VERSION:
                raise ValueError("Worksheet category orders require project format version 5 or later.")
            data.raw.attrs[WORKSHEET_ORDERS] = validated_orders(table[WORKSHEET_ORDERS], data.raw.columns)
        for name, expression in table["formulas"]:
            data.set_formula(name, expression)
        if "formula_order" in table:
            order = table["formula_order"]
            if (not isinstance(order, list) or len(order) != len(data.formulas)
                    or not all(isinstance(name, str) for name in order) or set(order) != data.formulas.keys()):
                raise ValueError("Invalid saved formula column order.")
            data.formulas = {name: data.formulas[name] for name in order}
        if "column_order" in table:
            data.column_order = _validated_column_order(table["column_order"], data.raw.columns, data.formulas)
        if "cell_backgrounds" in table:
            data.cell_backgrounds = read_backgrounds(table["cell_backgrounds"], len(data.raw), set(data.columns))
        if "number_formats" in table:
            data.number_formats = read_column_formats(table["number_formats"], set(data.columns))
        entries = table.get("analyses", [])
        limit = MAX_ANALYSIS_NODES if version >= 3 else 256
        if len(entries) > limit or any(not isinstance(method, str) or not isinstance(options, dict)
                                    for method, options in entries):
            raise ValueError("Invalid saved analysis settings.")
        data.analyses = [saved_analysis(method, options) for method, options in entries]
        for slot, colored in _analysis_slots(table.get("result_backgrounds", {}), len(entries)).items():
            if not isinstance(colored, dict):
                raise ValueError("Invalid saved result backgrounds.")
            data.result_backgrounds[slot] = {
                name: read_backgrounds(colors, MAX_CELLS, range(MAX_CELLS)) for name, colors in colored.items()
            }
        for slot, formatted in _analysis_slots(table.get("result_number_formats", {}), len(entries)).items():
            if not isinstance(formatted, dict):
                raise ValueError("Invalid saved result number formats.")
            read = {name: read_position_formats(formats, MAX_CELLS) for name, formats in formatted.items()}
            if read := {name: formats for name, formats in read.items() if formats}:
                data.result_number_formats[slot] = read
        data.analysis_ids = _analysis_slots(table.get("analysis_ids", {}), len(entries))
        sources = _analysis_slots(table.get("analysis_sources", {}), len(entries))
        if sources and version < 3:
            raise ValueError("Linked analyses require project format version 3 or later.")
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
