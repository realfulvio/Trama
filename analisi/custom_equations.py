"""Restricted mathematical grammar for user equations.

The text is tokenised and parsed by a small recursive-descent parser into an immutable tree of
tuples. Nothing is ever passed to ``eval``, ``exec``, ``compile`` or ``ast``: names, calls and
operators outside the grammar are syntax errors, and the size budgets are checked while parsing,
before any node is evaluated. No Tk and no I/O here.

Two syntaxes share the parser (0.81). ``Arithmetic`` is the default and the only path of recipes
without an ``Equation syntax`` field: it is exactly the 0.61 grammar, where ``if``, ``and``, ``or``
and ``not`` are ordinary coefficient names. ``Conditional`` is an explicit opt-in that adds
``if(condition, value if true, value if false)``, the comparisons ``< <= > >= == !=`` and the
combinations ``not``/``and``/``or`` (in that order of precedence) inside conditions. A condition is
never a number and a number is never a condition. Each branch, and the right side of ``and``/``or``,
is evaluated only on the elements for which it is active.
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
             "sin": np.sin, "cos": np.cos, "tan": np.tan,
             # 0.109.x: inverse and hyperbolic functions (NIST Roszman1 needs atan).
             "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan,
             "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh}
RESERVED = frozenset({VARIABLE, "Y", *CONSTANTS, *FUNCTIONS})
ARITHMETIC, CONDITIONAL = SYNTAXES = ("Arithmetic", "Conditional")
CONDITIONAL_WORDS = ("if", "and", "or", "not")
# Words of the Conditional syntax: in that syntax they cannot be coefficient names. Arithmetic keeps them free.
CONDITIONAL_RESERVED = frozenset({*RESERVED, *CONDITIONAL_WORDS})
COMPARISONS = ("<=", ">=", "==", "!=", "<", ">")

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_OPERATORS = ("**", "+", "-", "*", "/", "(", ")", ",")
_CONDITIONAL_OPERATORS = ("**", *COMPARISONS, "+", "-", "*", "/", "(", ")", ",")
_COMPARE = {"<": np.less, "<=": np.less_equal, ">": np.greater, ">=": np.greater_equal,
            "==": np.equal, "!=": np.not_equal}


def syntax_of(value):
    """The canonical syntax; a missing field (None) is Arithmetic, anything else unknown is an error."""
    if value is None:
        return ARITHMETIC
    if value not in SYNTAXES:
        raise FieldError("Equation syntax", "Choose Arithmetic or Conditional.")
    return value


def check_name(name, syntax=ARITHMETIC):
    """Validate a coefficient name; raises FieldError on Parameters."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or not name.isascii():
        raise FieldError("Parameters", f"Coefficient name {name} must be letters, digits and underscores, "
                                       "starting with a letter.")
    if len(name) > MAX_NAME:
        raise FieldError("Parameters", f"Coefficient name {name[:12]}… is longer than {MAX_NAME} characters.")
    if name in RESERVED:
        raise FieldError("Parameters", f"{name} is reserved (X, Y, pi, e and function names cannot be coefficients).")
    if syntax == CONDITIONAL and name in CONDITIONAL_WORDS:
        raise FieldError("Parameters", f"{name} is a word of the Conditional syntax and cannot be a coefficient "
                                       "there. Rename the coefficient, or choose Arithmetic.")


def _tokens(text, syntax=ARITHMETIC):
    operators = _CONDITIONAL_OPERATORS if syntax == CONDITIONAL else _OPERATORS
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
        for operator in operators:
            if text.startswith(operator, position):
                tokens.append(("op", operator, position))
                position += len(operator)
                break
        else:
            if syntax == CONDITIONAL and char in "=!":
                raise FieldError("Equation", f"Unexpected {char!r} at position {position + 1}. "
                                             "Compare with < <= > >= == or != inside if(...).")
            if char in "<>=!":
                raise FieldError("Equation", f"Unexpected {char!r} at position {position + 1}. "
                                             "Comparisons and if(...) need the Conditional equation syntax.")
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
    def __init__(self, tokens, names, syntax=ARITHMETIC):
        self.tokens, self.index, self.names, self.nodes, self.nest = tokens, 0, names, 0, 0
        self.used = set()
        self.syntax = syntax
        # Conditional bookkeeping: names read inside any condition, and the number of if(...) nodes.
        self.conditioned, self.condition_level, self.branches = set(), 0, 0

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

    def word(self, text):
        kind, value, _ = self.peek()
        if kind == "name" and value == text:
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

    def comparison_ahead(self):
        kind, value, _ = self.peek()
        return kind == "op" and value in COMPARISONS

    def not_a_number(self):
        _, value, position = self.peek()
        raise FieldError("Equation", f"A comparison is not a number ({value} at position {position + 1}). "
                                     "Use comparisons only as the condition of if(condition, value if true, "
                                     "value if false).")

    def parse(self):
        tree = self.expression(1)
        kind, value, position = self.peek()
        if kind != "end":
            if self.comparison_ahead():
                self.not_a_number()
            if self.syntax == CONDITIONAL and kind == "name" and value in ("and", "or", "not"):
                raise FieldError("Equation", f"{value} combines conditions: use it only inside the condition "
                                             "of if(condition, value if true, value if false).")
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
            if self.syntax == CONDITIONAL:
                if value == "if":
                    return self.conditional(depth)
                if value in ("and", "or", "not"):
                    raise FieldError("Equation", f"{value} combines conditions: use it only inside the condition "
                                                 "of if(condition, value if true, value if false).")
            if value in FUNCTIONS:
                if not self.accept("("):
                    raise FieldError("Equation", f"{value} is a function: write it with an argument in parentheses, "
                                                 f"for example {value}(X).")
                argument = self.expression(depth + 1)
                if self.accept(","):
                    raise FieldError("Equation", f"{value} takes exactly one argument.")
                if not self.accept(")"):
                    if self.comparison_ahead():
                        self.not_a_number()
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
            if self.condition_level:
                self.conditioned.add(value)
            return self.node(depth, "param", value)
        if kind == "op" and value == "(":
            inner = self.expression(depth + 1)
            if not self.accept(")"):
                if self.comparison_ahead():
                    self.not_a_number()
                raise FieldError("Equation", "Missing ) to close a parenthesis.")
            return inner
        if kind == "end":
            raise FieldError("Equation", f"The equation ends too early: something is missing after position {position}.")
        raise FieldError("Equation", f"Unexpected {value!r} at position {position + 1}.")

    # --- Conditional syntax ----------------------------------------------------------------------

    def _arguments_error(self):
        kind, value, position = self.peek()
        if kind == "op" and value == ")":
            raise FieldError("Equation", "if takes exactly three arguments: if(condition, value if true, "
                                         "value if false).")
        if kind == "end":
            raise FieldError("Equation", f"The equation ends too early: something is missing after position {position}.")
        if self.comparison_ahead():
            self.not_a_number()
        raise FieldError("Equation", f"Unexpected {value!r} at position {position + 1}.")

    def conditional(self, depth):
        # The recursion guard is already counted by expression() and unary() around this call.
        if not self.accept("("):
            raise FieldError("Equation", "if is the conditional: write if(condition, value if true, value if false).")
        ordinal = self.branches
        self.branches += 1
        self.condition_level += 1
        condition = self.condition(depth + 1)
        self.condition_level -= 1
        if not self.accept(","):
            self._arguments_error()
        when_true = self.expression(depth + 1)
        if not self.accept(","):
            self._arguments_error()
        when_false = self.expression(depth + 1)
        if self.accept(","):
            raise FieldError("Equation", "if takes exactly three arguments: if(condition, value if true, "
                                         "value if false).")
        if not self.accept(")"):
            if self.comparison_ahead():
                self.not_a_number()
            raise FieldError("Equation", "Missing ) after the arguments of if.")
        return self.node(depth, "if", ordinal, condition, when_true, when_false)

    def condition(self, depth):
        """``or`` of ``and`` of ``not`` of comparisons or parenthesised conditions."""
        self.enter()
        try:
            left = self.conjunction(depth + 1)
            while self.word("or"):
                left = self.node(depth, "or", left, self.conjunction(depth + 1))
            return left
        finally:
            self.leave()

    def conjunction(self, depth):
        left = self.negation(depth + 1)
        while self.word("and"):
            left = self.node(depth, "and", left, self.negation(depth + 1))
        return left

    def negation(self, depth):
        self.enter()
        try:
            if self.word("not"):
                return self.node(depth, "not", self.negation(depth + 1))
            return self.relation(depth + 1)
        finally:
            self.leave()

    def grouped(self):
        """At "(": True when it opens a condition, False when it opens the number on the left of a comparison.

        The parenthesis is matched on the token list. A comparison or an arithmetic operator right after
        the closing parenthesis means the group is a number, as in (X+1)*2 > 3; anything else (and, or, a
        comma, a closing parenthesis) means a condition. An unmatched parenthesis is read as a condition,
        whose own parser then reports the missing ).
        """
        level = 0
        for position in range(self.index, len(self.tokens)):
            kind, value, _ = self.tokens[position]
            if kind == "op" and value == "(":
                level += 1
            elif kind == "op" and value == ")":
                level -= 1
                if level == 0:
                    after_kind, after, _ = self.tokens[position + 1]
                    return not (after_kind == "op" and after in (*COMPARISONS, "+", "-", "*", "/", "**"))
        return True

    def relation(self, depth):
        if self.peek()[:2] == ("op", "(") and self.grouped():
            self.take()
            inner = self.condition(depth + 1)
            if not self.accept(")"):
                kind, value, position = self.peek()
                if kind == "end":
                    raise FieldError("Equation", "Missing ) to close a parenthesis.")
                raise FieldError("Equation", f"Unexpected {value!r} at position {position + 1}.")
            return inner
        left = self.expression(depth + 1)
        kind, operator, position = self.peek()
        if not (kind == "op" and operator in COMPARISONS):
            if kind == "end":
                raise FieldError("Equation", "A condition needs a comparison such as X < T (use < <= > >= == or "
                                             "!=); the equation ends before one.")
            raise FieldError("Equation", f"A condition needs a comparison such as X < T (use < <= > >= == or !=); "
                                         f"none was found before position {position + 1}.")
        self.take()
        right = self.expression(depth + 1)
        if self.comparison_ahead():
            _, value, position = self.peek()
            raise FieldError("Equation", f"Chained comparisons such as 0<X<1 are not supported ({value} at position "
                                         f"{position + 1}). Join two comparisons with and, as in (0<X) and (X<1).")
        return self.node(depth, "cmp", operator, left, right)


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


class ConditionError(FieldError):
    """A comparison met a value that is not a finite number on an element where it is evaluated.

    ``x`` is that element of X and ``position`` its index in the flattened input, so a fit can name the
    source row. The condition is never read as False.
    """

    def __init__(self, x, position):
        super().__init__("Equation", f"A condition of if(...) is not defined at X = {x:g}: one side of a comparison "
                                     "is not a finite number. Check divisions, logarithms and roots in the condition.")
        self.x, self.position = x, position


def _lazy(node, x, values, where, codes):
    """Like :func:`_evaluate` on a 1-D ``x``, but if(...) evaluates each branch only where it is active.

    ``where`` holds the positions of ``x`` in the full input; ``codes`` (or None) collects the branch path.
    """
    kind = node[0]
    if kind == "if":
        _, ordinal, condition, when_true, when_false = node
        mask = _truth(condition, x, values, where, codes)
        out = np.empty(len(x), dtype=float)
        for chosen, branch, digit in ((mask, when_true, 1), (~mask, when_false, 2)):
            active = np.flatnonzero(chosen)
            if active.size:
                if codes is not None:
                    codes[where[active]] += digit * 3 ** ordinal
                out[active] = _lazy(branch, x[active], values, where[active], codes)
        return out
    if kind == "x":
        return x
    if kind == "num":
        return np.full_like(x, node[1])
    if kind == "param":
        return np.full_like(x, values[node[1]])
    if kind == "neg":
        return -_lazy(node[1], x, values, where, codes)
    if kind == "call":
        return FUNCTIONS[node[1]](_lazy(node[2], x, values, where, codes))
    operator = node[1]
    left, right = _lazy(node[2], x, values, where, codes), _lazy(node[3], x, values, where, codes)
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        return left / right
    return np.power(left, right)


def _truth(node, x, values, where, codes):
    """Boolean array of a condition; the right side of and/or only where the left side does not decide."""
    kind = node[0]
    if kind == "not":
        return ~_truth(node[1], x, values, where, codes)
    if kind in ("and", "or"):
        left = _truth(node[1], x, values, where, codes)
        pending = np.flatnonzero(left if kind == "and" else ~left)
        result = left.copy()
        if pending.size:
            result[pending] = _truth(node[2], x[pending], values, where[pending], codes)
        return result
    _, operator, left_node, right_node = node
    left = np.asarray(_lazy(left_node, x, values, where, codes), dtype=float)
    right = np.asarray(_lazy(right_node, x, values, where, codes), dtype=float)
    finite = np.isfinite(left) & np.isfinite(right)
    if not finite.all():
        bad = int(np.flatnonzero(~finite)[0])
        raise ConditionError(float(x[bad]), int(where[bad]))
    # Exact comparisons: no tolerance.
    return _COMPARE[operator](left, right)


@dataclass(frozen=True)
class CompiledEquation:
    """Immutable parsed equation. Holds no callable supplied by the user and no project state.

    ``condition_parameters`` are the coefficients read inside a condition, in declared order;
    ``branches`` counts the if(...) nodes (0 for every Arithmetic equation).
    """
    text: str
    parameters: tuple
    tree: tuple
    syntax: str = ARITHMETIC
    condition_parameters: tuple = ()
    branches: int = 0

    def _values(self, parameters):
        try:
            return {name: float(parameters[name]) for name in self.parameters}
        except KeyError as error:
            raise FieldError("Parameters", f"Missing a value for {error.args[0]}.") from None

    def evaluate(self, x, parameters):
        """Values with the shape of ``x`` (float). Points where the model is undefined are nan or ±inf.

        With if(...) each branch is evaluated only on its own elements; a condition that is not a finite
        comparison on an evaluated element raises :class:`ConditionError` (field Equation).
        """
        x = np.asarray(x, dtype=float)
        values = self._values(parameters)
        if not self.branches:
            with np.errstate(all="ignore"):
                return np.asarray(_evaluate(self.tree, x, values), dtype=float)
        return self._run(x, values, None)

    def _run(self, x, values, codes):
        flat = x.reshape(-1)
        with np.errstate(all="ignore"):
            result = _lazy(self.tree, flat, values, np.arange(flat.size), codes) if flat.size else flat.copy()
        return np.array(result, dtype=float).reshape(x.shape)

    def branch_codes(self, x, parameters):
        """Integers with the shape of ``x``: equal for elements that follow the same path through if(...).

        Each if(...) is a base-3 digit in order of appearance (0 not reached, 1 true, 2 false), so a code
        does not depend on which elements are evaluated together. An equation without if(...) gives 0.
        """
        x = np.asarray(x, dtype=float)
        values = self._values(parameters)
        codes = np.zeros(x.size, dtype=np.int64)
        if self.branches and x.size:
            self._run(x, values, codes)
        return codes.reshape(x.shape)


def curve_with_breaks(x, y, codes):
    """New 1-D copies of ``x`` and ``y`` with one nan between neighbours whose branch codes differ.

    No source point is dropped or reordered; a drawn line therefore never joins two branches. Points
    that are not finite stay as they are (a line is not drawn through them either).
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    codes = np.asarray(codes).reshape(-1)
    if not len(x) == len(y) == len(codes):
        raise ValueError("x, y and codes must have the same length.")
    breaks = np.flatnonzero(codes[1:] != codes[:-1]) + 1
    return np.insert(x, breaks, np.nan), np.insert(y, breaks, np.nan)


def compile_equation(text, parameter_names, *, syntax=ARITHMETIC):
    """Parse ``text`` against the declared coefficient names (every one must be used).

    ``syntax`` is "Arithmetic" (the default, and the meaning of a missing recipe field) or "Conditional".
    """
    syntax = syntax_of(syntax)
    if not isinstance(text, str) or not text.strip():
        raise FieldError("Equation", "Enter an equation, for example A + B*X.")
    names = tuple(parameter_names)
    if len(names) > MAX_PARAMETERS:
        raise FieldError("Parameters", f"Use at most {MAX_PARAMETERS} coefficients.")
    for name in names:
        check_name(name, syntax)
    if len(set(names)) != len(names):
        raise FieldError("Parameters", "Coefficient names must be distinct.")
    parser = _Parser(_tokens(text, syntax), set(names), syntax)
    tree = parser.parse()
    unused = [name for name in names if name not in parser.used]
    if unused:
        raise FieldError("Parameters", f"The equation does not use {', '.join(unused)}. "
                                       "Remove the coefficient or add it to the equation.")
    if syntax == ARITHMETIC:
        return CompiledEquation(text, names, tree)
    return CompiledEquation(text, names, tree, syntax,
                            tuple(name for name in names if name in parser.conditioned), parser.branches)
