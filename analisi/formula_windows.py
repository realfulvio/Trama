"""Normalize and evaluate whole-partition worksheet statistics."""
from numbers import Real
import tokenize

import numpy as np
import pandas as pd
from pandas.api.indexers import BaseIndexer

from .formula_row_statistics import ROW_STATISTICS, row_statistic

_SUMMARY_STATISTICS = {"MEAN", "SUM", "MIN", "MAX", "STDEV", "STDERR", "COUNT", "COUNTA"}
WINDOW_CALLS = _SUMMARY_STATISTICS | ROW_STATISTICS
CONDITIONAL_CALLS = {f"{name}IF": name for name in _SUMMARY_STATISTICS}
_CLAUSE_ORDER = ("OVER", "WHERE", "ORDER", "ROWS")
WINDOW_CLAUSES = set(_CLAUSE_ORDER)
WINDOW_KEYWORDS = WINDOW_CLAUSES | {"ASC", "DESC", "PRECEDING", "FOLLOWING", "UNBOUNDED"}
WINDOW_FUNCTION = "_WINDOW_STATISTIC"
_COMMA = (tokenize.OP, ",")
_OPEN = (tokenize.OP, "(")
_CLOSE = (tokenize.OP, ")")
_NONE = [(tokenize.NAME, "None")]


def _word(token):
    return token[1].upper() if isinstance(token, tuple) and token[0] == tokenize.NAME else ""


def _groups(tokens):
    """Represent balanced parentheses as nested token lists."""
    stack = [[]]
    for token in tokens:
        if token == _OPEN:
            child = []
            stack[-1].append(child)
            stack.append(child)
            if len(stack) > 128:
                raise ValueError("Formula is too complex.")
        elif token == _CLOSE:
            if len(stack) == 1:
                raise ValueError("Invalid formula parentheses.")
            stack.pop()
        else:
            stack[-1].append(token)
    if len(stack) != 1:
        raise ValueError("Invalid formula parentheses.")
    return stack[0]


def _clause_expression(nodes):
    if not nodes:
        raise ValueError("Enter an expression after OVER or WHERE.")
    result = []
    for kind, value in _lower(nodes):
        if (kind, value) == (tokenize.OP, ">") and result and result[-1] == (tokenize.OP, "<"):
            result[-1] = (tokenize.OP, "!=")
        else:
            result.append((kind, "==" if kind == tokenize.OP and value == "=" else value))
    return result


def _statistic_arguments(nodes, conditional):
    commas = [index for index, item in enumerate(nodes) if item == _COMMA]
    if conditional:
        if len(commas) != 1 or commas[0] in (0, len(nodes) - 1):
            raise ValueError("Enter one value expression and one condition for a conditional statistic.")
        split = commas[0]
        return _lower(nodes[:split]), _clause_expression(nodes[split + 1:])
    if not nodes or commas:
        raise ValueError("Use OVER or WHERE after a worksheet statistic with one argument.")
    return _lower(nodes), _NONE


def _clauses(nodes):
    starts = []
    for index, node in enumerate(nodes):
        name = _word(node)
        # ORDER starts a clause at the beginning or as part of ORDER BY.
        # Otherwise it can be an ordinary column in a value expression.
        if name == "ORDER" and index and (index + 1 == len(nodes) or _word(nodes[index + 1]) != "BY"):
            continue
        if name in WINDOW_CLAUSES:
            starts.append((index, name))
    if not starts:
        return {}
    order = [_CLAUSE_ORDER.index(name) for _, name in starts]
    if order != sorted(set(order)):
        raise ValueError("Use OVER, WHERE, ORDER BY and ROWS once each, in that order.")
    ends = [index for index, _ in starts[1:]] + [len(nodes)]
    return {name: nodes[index + 1:end] for (index, name), end in zip(starts, ends)}


def _sort_expressions(nodes):
    message = "Enter ORDER BY followed by a sort expression."
    if not nodes or _word(nodes[0]) != "BY":
        raise ValueError(message)
    expressions, directions = [], []
    start = 1
    separators = [index for index, node in enumerate(nodes) if node == _COMMA]
    for end in [*separators, len(nodes)]:
        item = nodes[start:end]
        direction = _word(item[-1]) if item else ""
        expression = item[:-1] if direction in {"ASC", "DESC"} else item
        if not expression:
            raise ValueError(message)
        expressions.append(_clause_expression(expression))
        directions.append([_literal(direction != "DESC")])
        start = end + 1
    if len(expressions) == 1:
        return expressions[0], directions[0]
    return _tuple_tokens(expressions), _tuple_tokens(directions)


def _tuple_tokens(items):
    tokens = [_OPEN]
    for item in items:
        tokens.extend([*item, _COMMA])
    return [*tokens, _CLOSE]


def _row_bounds(nodes):
    if len(nodes) not in {2, 4}:
        raise ValueError("Use a nonnegative integer or UNBOUNDED before PRECEDING or FOLLOWING.")
    before, after = 0, 0
    directions = [_word(node) for node in nodes[1::2]]
    if directions not in (["PRECEDING"], ["FOLLOWING"], ["PRECEDING", "FOLLOWING"]):
        raise ValueError("Use PRECEDING first and FOLLOWING second when specifying both row bounds.")
    for node, direction in zip(nodes[::2], directions):
        if _word(node) == "UNBOUNDED":
            count = None
        elif isinstance(node, tuple) and node[0] == tokenize.NUMBER and node[1].isdecimal() and len(node[1]) <= 7:
            count = int(node[1])
        else:
            raise ValueError("Use a nonnegative integer or UNBOUNDED for a row bound.")
        if direction == "PRECEDING":
            before = count
        else:
            after = count
    return before, after


def _literal(value):
    return (tokenize.NUMBER if type(value) is int else tokenize.NAME, repr(value))


def _lower(nodes, *, in_arguments=False):
    result = []
    index = 0
    while index < len(nodes):
        node = nodes[index]
        index += 1
        if not isinstance(node, list):
            result.append(node)
            continue
        clause = _word(nodes[index]) if index < len(nodes) else ""
        name = _word(result[-1]) if result else ""
        conditional = name in CONDITIONAL_CALLS
        if clause not in WINDOW_CLAUSES and not conditional:
            in_call = bool(name) and result[-1][1] not in {"and", "or", "not"}
            result.extend([_OPEN, *_lower(node, in_arguments=in_call), _CLOSE])
            continue
        statistic = CONDITIONAL_CALLS.get(name, name)
        if statistic not in WINDOW_CALLS:
            raise ValueError("Use OVER or WHERE after a worksheet statistic with one argument.")
        values, inline_filter = _statistic_arguments(node, conditional)
        result.pop()
        clauses = {}
        if clause in WINDOW_CLAUSES:
            end = index
            sort_list = False
            while end < len(nodes):
                token = nodes[end]
                # Inside a call a comma still separates arguments. Parenthesize
                # a window expression with its own sort list before combining it.
                if token == _COMMA and (in_arguments or not sort_list):
                    break
                word = _word(token)
                if word == "ORDER" and end + 1 < len(nodes) and _word(nodes[end + 1]) == "BY":
                    sort_list = True
                elif word == "ROWS":
                    sort_list = False
                end += 1
            clauses = _clauses(nodes[index:end])
            index = end
        partition = _clause_expression(clauses["OVER"]) if "OVER" in clauses else _NONE
        condition = _clause_expression(clauses["WHERE"]) if "WHERE" in clauses else _NONE
        sort, ascending = _sort_expressions(clauses["ORDER"]) if "ORDER" in clauses else (_NONE, [_literal(True)])
        bounds = _NONE
        if "ROWS" in clauses:
            before, after = _row_bounds(clauses["ROWS"])
            bounds = [_OPEN, _literal(before), _COMMA, _literal(after), _CLOSE]
        if conditional:
            if condition is _NONE:
                condition = inline_filter
            else:
                condition = [(tokenize.NAME, "AND"), _OPEN, *inline_filter, _COMMA, *condition, _CLOSE]
        result.extend([(tokenize.NAME, WINDOW_FUNCTION), _OPEN,
                       (tokenize.STRING, repr(statistic)), _COMMA, *values, _COMMA,
                       *partition, _COMMA, *condition, _COMMA, *sort, _COMMA,
                       *ascending, _COMMA, *bounds, _CLOSE])
    return result


def lower_window_clauses(tokens):
    """Translate postfix clauses into the private call recognized by the AST evaluator."""
    significant = [item for item in tokens if item[0] not in
                   {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.ENDMARKER}]
    if not any((previous == _CLOSE and _word(current) in WINDOW_CLAUSES)
               or (_word(previous) in CONDITIONAL_CALLS and current == _OPEN)
               for previous, current in zip(significant, significant[1:])):
        return tokens
    return _lower(_groups(significant))


def _aligned(value, size):
    array = np.asarray(value, dtype=object)
    if array.ndim == 0:
        return np.broadcast_to(array, (size,))
    if array.shape != (size,):
        raise ValueError("A worksheet statistic requires one value per row.")
    return array


def _missing(value):
    return bool(pd.isna(value)) or isinstance(value, str) and not value.strip()


class _RowWindow(BaseIndexer):
    def __init__(self, before, after):
        super().__init__()
        self.before, self.after = before, after

    def get_window_bounds(self, num_values=0, min_periods=None, center=None, closed=None, step=None):
        position = np.arange(num_values, dtype=np.int64)
        start = np.maximum(0, position - self.before) if self.before is not None else np.zeros_like(position)
        stop = np.minimum(num_values, position + self.after + 1) if self.after is not None else np.full_like(position, num_values)
        return start, stop


def _moving_statistic(numeric, labels, selected, ordering, bounds, name, operation):
    result = np.full(len(numeric), np.nan)
    groups = pd.Series(np.flatnonzero(selected)).groupby(np.asarray(labels)[selected], sort=False, dropna=True)
    for _, group in groups:
        rows = group.to_numpy()
        try:
            # Stable sorts from the least to the most significant key retain the
            # original worksheet order whenever the complete set of keys ties.
            for values, ascending in reversed(ordering):
                sorted_key = pd.Series(values[rows], index=rows).sort_values(ascending=ascending, kind="stable")
                rows = sorted_key.index.to_numpy()
        except TypeError as error:
            raise ValueError("ORDER BY needs comparable values within each group.") from error
        window = _RowWindow(*bounds)
        if name in ROW_STATISTICS:
            values = numeric[rows]
            result[rows] = row_statistic(name, values, values, window)
            continue
        minimum = 0 if operation in {"sum", "count"} else 1
        rolling = pd.Series(numeric[rows]).rolling(window, min_periods=minimum)
        result[rows] = (rolling.std() / np.sqrt(rolling.count()) if name == "STDERR" else getattr(rolling, operation)())
    return result


def worksheet_statistic(name, values, partition, condition, size, *, sort_keys=(), bounds=None):
    if name not in WINDOW_CALLS:
        raise ValueError("Unknown worksheet statistic.")
    values = _aligned(values, size)
    if name in ROW_STATISTICS:
        numbers = pd.to_numeric(pd.Series(values), errors="coerce")
        if name == "RANK":
            numeric = numbers.to_numpy()
        else:
            numeric = numbers.to_numpy(dtype=float, na_value=np.nan, copy=True)
            numeric[~np.isfinite(numeric)] = np.nan
    elif name == "COUNTA":
        numeric = np.array([np.nan if _missing(value) else 1. for value in values])
    else:
        numeric = np.array([value if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) else np.nan
                            for value in values], dtype=float)
        numeric[~np.isfinite(numeric)] = np.nan
    selected = np.ones(size, dtype=bool)
    if condition is not None:
        condition = _aligned(condition, size)
        if any(not isinstance(value, (bool, np.bool_)) and not _missing(value) for value in condition):
            raise ValueError("WHERE requires a logical expression.")
        selected = np.array([False if _missing(value) else value for value in condition], dtype=bool)
    if partition is None:
        labels = np.zeros(size, dtype=int)
    else:
        labels = pd.Series([None if _missing(value) else (type(value), value)
                            for value in _aligned(partition, size)], dtype=object)
    ordering = [(_aligned(key, size), ascending) for key, ascending in sort_keys]
    operation = {"STDEV": "std", "STDERR": "std", "COUNTA": "count"}.get(name, name.lower())
    if bounds is not None:
        return _moving_statistic(numeric, labels, selected, ordering, bounds, name, operation)
    if name in ROW_STATISTICS:
        result = np.full(size, np.nan)
        for rows in pd.Series(np.arange(size)).groupby(labels, sort=False, dropna=True).indices.values():
            result[rows] = row_statistic(name, numeric[rows], numeric[rows[selected[rows]]])
        return result
    groups = pd.Series(np.where(selected, numeric, np.nan)).groupby(labels, sort=False, dropna=True)
    if name == "STDERR":
        return (groups.transform("std") / np.sqrt(groups.transform("count"))).to_numpy()
    return groups.transform(operation).to_numpy()
