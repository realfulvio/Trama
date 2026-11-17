"""Restricted mathematical grammar for user equations.

The text is tokenised and parsed by a small recursive-descent parser into an immutable tree of
tuples. Nothing is ever passed to ``eval``, ``exec``, ``compile`` or ``ast``: names, calls and
operators outside the grammar are syntax errors, and the size budgets are checked while parsing,
before any node is evaluated. No Tk and no I/O here.
"""
import math
import re
from dataclasses import dataclass

import numpy as np

from .field_error import FieldError

MAX_LENGTH, MAX_NODES, MAX_DEPTH, MAX_PARAMETERS, MAX_NAME = 1024, 128, 32, 12, 32
VARIABLE = "X"
CONSTANTS = {"pi": math.pi, "e": math.e}
FUNCTIONS = {"exp": np.exp, "log": np.log, "log10": np.log10, "sqrt": np.sqrt, "abs": np.abs,
             "sin": np.sin, "cos": np.cos, "tan": np.tan}
RESERVED = frozenset({VARIABLE, "Y", *CONSTANTS, *FUNCTIONS})

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_OPERATORS = ("**", "+", "-", "*", "/", "(", ")", ",")


def check_name(name):
    """Validate a coefficient name; raises FieldError on Parameters."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or not name.isascii():
        raise FieldError("Parameters", f"Coefficient name {name} must be letters, digits and underscores, "
                                       "starting with a letter.")
    if len(name) > MAX_NAME:
        raise FieldError("Parameters", f"Coefficient name {name[:12]}… is longer than {MAX_NAME} characters.")
    if name in RESERVED:
        raise FieldError("Parameters", f"{name} is reserved (X, Y, pi, e and function names cannot be coefficients).")


def _tokens(text):
    if len(text) > MAX_LENGTH:
        raise FieldError("Equation", f"The equation is longer than {MAX_LENGTH} characters.")
    text = text.replace("^", "**")
    position, tokens = 0, []
    while position < len(text):
        char = text[position]
        if char.isspace():
            position += 1
            continue
        if char.isdigit() or char == ".":
            match = _NUMBER.match(text, position)
            if not match:
                raise FieldError("Equation", f"Unexpected {char!r} at position {position + 1}.")
            end = match.end()
            if end < len(text) and (text[end].isalnum() or text[end] in "._"):
                raise FieldError("Equation", f"Invalid number near position {position + 1} "
                                             "(complex, hexadecimal and attribute syntax are not supported).")
            value = float(match.group())
            if not math.isfinite(value):
                raise FieldError("Equation", f"The number {match.group()} is not finite.")
            tokens.append(("num", value, position))
            position = end
            continue
        if char.isascii() and char.isalpha():
            match = _NAME.match(text, position)
            tokens.append(("name", match.group(), position))
            position = match.end()
            continue
        for operator in _OPERATORS:
            if text.startswith(operator, position):
                tokens.append(("op", operator, position))
                position += len(operator)
                break
        else:
            raise FieldError("Equation", f"Unexpected {char!r} at position {position + 1}. "
                                         "Use numbers, X, the coefficients, + - * / ^ ( ) and the functions "
                                         + ", ".join(FUNCTIONS) + ".")
        if len(tokens) > 4 * MAX_NODES:
            raise FieldError("Equation", f"The equation has more than {MAX_NODES} elements.")
    tokens.append(("end", None, len(text)))
    return tokens


def _height(content):
    return 1 + max((_height(child) for child in content if isinstance(child, tuple)), default=0)


class _Parser:
    def __init__(self, tokens, names):
        self.tokens, self.index, self.names, self.nodes, self.nest = tokens, 0, names, 0, 0
        self.used = set()

    def peek(self):
        return self.tokens[self.index]

    def take(self):
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, operator):
        kind, value, _ = self.peek()
        if kind == "op" and value == operator:
            self.index += 1
            return True
        return False

    def node(self, _depth, *content):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FieldError("Equation", f"The equation has more than {MAX_NODES} elements.")
        if _height(content) > MAX_DEPTH:
            raise FieldError("Equation", f"The equation is nested deeper than {MAX_DEPTH} levels.")
        return content

    def enter(self):
        # Guards the recursion of the parser itself on inputs such as 500 opening parentheses.
        self.nest += 1
        if self.nest > MAX_DEPTH:
            raise FieldError("Equation", f"The equation is nested deeper than {MAX_DEPTH} levels.")

    def leave(self):
        self.nest -= 1

    def parse(self):
        tree = self.expression(1)
        kind, value, position = self.peek()
        if kind != "end":
            raise FieldError("Equation", f"Unexpected {value!r} at position {position + 1}.")
        return tree

    def expression(self, depth):
        self.enter()
        left = self.term(depth + 1)
        while True:
            for operator in ("+", "-"):
                if self.accept(operator):
                    left = self.node(depth, "bin", operator, left, self.term(depth + 1))
                    break
            else:
                self.leave()
                return left

    def term(self, depth):
        left = self.unary(depth + 1)
        while True:
            for operator in ("*", "/"):
                if self.accept(operator):
                    left = self.node(depth, "bin", operator, left, self.unary(depth + 1))
                    break
            else:
                return left

    def unary(self, depth):
        self.enter()
        try:
            for sign in ("+", "-"):
                if self.accept(sign):
                    operand = self.unary(depth + 1)
                    return self.node(depth, "neg", operand) if sign == "-" else operand
            return self.power(depth + 1)
        finally:
            self.leave()

    def power(self, depth):
        base = self.atom(depth + 1)
        if self.accept("**"):
            # Right associative; the exponent may carry a sign, as in 2^-X.
            return self.node(depth, "bin", "**", base, self.unary(depth + 1))
        return base

    def atom(self, depth):
        kind, value, position = self.take()
        if kind == "num":
            return self.node(depth, "num", value)
        if kind == "name":
            if value in FUNCTIONS:
                if not self.accept("("):
                    raise FieldError("Equation", f"{value} is a function: write it with an argument in parentheses, "
                                                 f"for example {value}(X).")
                argument = self.expression(depth + 1)
                if self.accept(","):
                    raise FieldError("Equation", f"{value} takes exactly one argument.")
                if not self.accept(")"):
                    raise FieldError("Equation", f"Missing ) after the argument of {value}.")
                return self.node(depth, "call", value, argument)
            if self.peek()[:2] == ("op", "("):
                raise FieldError("Equation", f"{value} is not an available function. "
                                             f"Functions: {', '.join(FUNCTIONS)}.")
            if value == VARIABLE:
                return self.node(depth, "x")
            if value in CONSTANTS:
                return self.node(depth, "num", CONSTANTS[value])
            if value == "Y":
                raise FieldError("Equation", "Y is the response and cannot appear in the equation.")
            if value not in self.names:
                raise FieldError("Equation", f"{value} is not declared as a coefficient. Add it to Parameters "
                                             "or check the spelling (names are case-sensitive).")
            self.used.add(value)
            return self.node(depth, "param", value)
        if kind == "op" and value == "(":
            inner = self.expression(depth + 1)
            if not self.accept(")"):
                raise FieldError("Equation", "Missing ) to close a parenthesis.")
            return inner
        if kind == "end":
            raise FieldError("Equation", f"The equation ends too early: something is missing after position {position}.")
        raise FieldError("Equation", f"Unexpected {value!r} at position {position + 1}.")


def _evaluate(node, x, values):
    kind = node[0]
    if kind == "x":
        return x
    if kind == "num":
        return np.full_like(x, node[1])
    if kind == "param":
        return np.full_like(x, values[node[1]])
    if kind == "neg":
        return -_evaluate(node[1], x, values)
    if kind == "call":
        return FUNCTIONS[node[1]](_evaluate(node[2], x, values))
    operator, left, right = node[1], _evaluate(node[2], x, values), _evaluate(node[3], x, values)
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        return left / right
    return np.power(left, right)


@dataclass(frozen=True)
class CompiledEquation:
    """Immutable parsed equation. Holds no callable supplied by the user and no project state."""
    text: str
    parameters: tuple
    tree: tuple

    def evaluate(self, x, parameters):
        """Values with the shape of ``x`` (float). Points where the model is undefined are nan or ±inf."""
        x = np.asarray(x, dtype=float)
        try:
            values = {name: float(parameters[name]) for name in self.parameters}
        except KeyError as error:
            raise FieldError("Parameters", f"Missing a value for {error.args[0]}.") from None
        with np.errstate(all="ignore"):
            return np.asarray(_evaluate(self.tree, x, values), dtype=float)


def compile_equation(text, parameter_names):
    """Parse ``text`` against the declared coefficient names (every one must be used)."""
    if not isinstance(text, str) or not text.strip():
        raise FieldError("Equation", "Enter an equation, for example A + B*X.")
    names = tuple(parameter_names)
    if len(names) > MAX_PARAMETERS:
        raise FieldError("Parameters", f"Use at most {MAX_PARAMETERS} coefficients.")
    for name in names:
        check_name(name)
    if len(set(names)) != len(names):
        raise FieldError("Parameters", "Coefficient names must be distinct.")
    parser = _Parser(_tokens(text), set(names))
    tree = parser.parse()
    unused = [name for name in names if name not in parser.used]
    if unused:
        raise FieldError("Parameters", f"The equation does not use {', '.join(unused)}. "
                                       "Remove the coefficient or add it to the equation.")
    return CompiledEquation(text, names, tree)
