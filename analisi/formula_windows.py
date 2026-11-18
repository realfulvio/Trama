"""Normalize and evaluate whole-partition worksheet statistics."""
from numbers import Real
import tokenize

import numpy as np
import pandas as pd

WINDOW_CALLS = {"MEAN", "SUM", "MIN", "MAX", "STDEV", "STDERR", "COUNT", "COUNTA"}
CONDITIONAL_CALLS = {f"{name}IF": name for name in WINDOW_CALLS}
WINDOW_CLAUSES = {"OVER", "WHERE"}
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


def _lower(nodes):
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
            result.extend([_OPEN, *_lower(node), _CLOSE])
            continue
        statistic = CONDITIONAL_CALLS.get(name, name)
        if statistic not in WINDOW_CALLS:
            raise ValueError("Use OVER or WHERE after a worksheet statistic with one argument.")
        values, inline_filter = _statistic_arguments(node, conditional)
        result.pop()
        partition, condition = _NONE, _NONE
        if clause in WINDOW_CLAUSES:
            end = index + 1
            while end < len(nodes) and nodes[end] != _COMMA:
                end += 1
            terms = nodes[index + 1:end]
            index = end
            words = [_word(term) for term in terms]
            if "ROWS" in words or any(a == "ORDER" and b == "BY" for a, b in zip(words, words[1:])):
                raise ValueError("ORDER BY and ROWS are unavailable in worksheet statistics.")
            if clause == "OVER":
                split = words.index("WHERE") if "WHERE" in words else len(terms)
                partition = _clause_expression(terms[:split])
                if split != len(terms):
                    condition = _clause_expression(terms[split + 1:])
            else:
                condition = _clause_expression(terms)
        if conditional:
            if condition is _NONE:
                condition = inline_filter
            else:
                condition = [(tokenize.NAME, "AND"), _OPEN, *inline_filter, _COMMA, *condition, _CLOSE]
        result.extend([(tokenize.NAME, WINDOW_FUNCTION), _OPEN,
                       (tokenize.STRING, repr(statistic)), _COMMA, *values, _COMMA,
                       *partition, _COMMA, *condition, _CLOSE])
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


def worksheet_statistic(name, values, partition, condition, size):
    if name not in WINDOW_CALLS:
        raise ValueError("Unknown worksheet statistic.")
    values = _aligned(values, size)
    if name == "COUNTA":
        numeric = np.array([np.nan if _missing(value) else 1. for value in values])
    else:
        numeric = np.array([value if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) else np.nan
                            for value in values], dtype=float)
        numeric[~np.isfinite(numeric)] = np.nan
    if condition is not None:
        condition = _aligned(condition, size)
        if any(not isinstance(value, (bool, np.bool_)) and not _missing(value) for value in condition):
            raise ValueError("WHERE requires a logical expression.")
        numeric = np.where([False if _missing(value) else value for value in condition], numeric, np.nan)
    if partition is None:
        labels = np.zeros(size, dtype=int)
    else:
        labels = pd.Series([None if _missing(value) else (type(value), value)
                            for value in _aligned(partition, size)], dtype=object)
    groups = pd.Series(numeric).groupby(labels, sort=False, dropna=True)
    if name == "STDERR":
        return (groups.transform("std") / np.sqrt(groups.transform("count"))).to_numpy()
    operation = {"STDEV": "std", "COUNTA": "count"}.get(name, name.lower())
    return groups.transform(operation).to_numpy()
