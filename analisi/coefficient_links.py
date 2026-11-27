"""Linked coefficients of a custom equation: one coefficient as an affine function of another.

A link is plain recipe data stored on the coefficient it defines (the *target*)::

    {"name": "C", ..., "link": {"source": "A", "factor": 2.0, "offset": 1.0}}   # C = 2*A + 1

Nothing is executed and the equation grammar is unchanged: the link is applied to the coefficient values
before every evaluation of the equation. Rules fixed by this module:

* source and target are coefficients of the same recipe; factor and offset are finite numbers (a negative
  factor is allowed, a zero factor makes the target the constant ``offset``);
* links may form acyclic chains (``D = 3 - 0.5*C``, ``C = 2*A + 1``). Every target is reduced to its *root*,
  the first coefficient of the chain that is not linked: ``target = factor * root + offset`` with the
  composed factor and offset. A cycle is an error that names the whole path;
* a linked coefficient is never Fixed and never a free coordinate of the solver. The solver estimates the
  roots only, and the limits of every target are carried onto its root (intersected, with the direction
  reversed for a negative factor);
* the covariance of a target is the affine image of the root's: ``SE(target) = |factor| * SE(root)``, and
  the profile interval of a target is the image of the root's profile, with the ends swapped for a negative
  factor.
"""
from dataclasses import dataclass
from math import isfinite

import numpy as np

from .field_error import FieldError

LINK = "link"
LINK_KEYS = ("source", "factor", "offset")
LINKED = "Linked"


@dataclass(frozen=True)
class Link:
    target: str
    source: str
    factor: float
    offset: float


def number_text(value):
    """A number with every stored digit (shortest round trip), without a trailing ``.0``."""
    value = float(value)
    if value == 0:
        return "0"
    shown = repr(value)
    return shown[:-2] if shown.endswith(".0") else shown


def _finite(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def read_link(record, name, field="Parameters"):
    """The validated link of one recipe record, or ``None``. Cross-record rules are in :class:`Plan`."""
    raw = record.get(LINK)
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - set(LINK_KEYS):
        raise FieldError(field, f"{name}: a link needs only a source coefficient, a factor and an offset.")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise FieldError(field, f"{name}: choose the source coefficient of the link.")
    factor, offset = raw.get("factor", 1.0), raw.get("offset", 0.0)
    if not _finite(factor):
        raise FieldError(field, f"{name}: the factor of the link must be a finite number.")
    if not _finite(offset):
        raise FieldError(field, f"{name}: the offset of the link must be a finite number.")
    return Link(name, source.strip(), float(factor), float(offset))


def affine_text(name, factor, offset, source):
    """``C = 2*A + 1`` with every digit of factor and offset."""
    if factor == 0:
        return f"{name} = {number_text(offset)}"
    if factor == 1:
        term = source
    elif factor == -1:
        term = f"-{source}"
    else:
        term = f"{number_text(factor)}*{source}"
    if offset == 0:
        return f"{name} = {term}"
    sign = "-" if offset < 0 else "+"
    return f"{name} = {term} {sign} {number_text(abs(offset))}"


def root_interval(lower, upper, factor, offset):
    """Values of the root that keep ``factor * root + offset`` inside ``[lower, upper]`` (factor != 0)."""
    with np.errstate(all="ignore"):
        a, b = (lower - offset) / factor, (upper - offset) / factor
    if factor < 0:
        a, b = b, a
    a = -np.inf if np.isnan(a) else float(a)
    b = np.inf if np.isnan(b) else float(b)
    return a, b


def _range_text(lower, upper):
    low = "−∞" if not np.isfinite(lower) else number_text(lower)
    high = "+∞" if not np.isfinite(upper) else number_text(upper)
    return f"{low} to {high}"


class Plan:
    """The links of one recipe: dependency order and the composed affine map of every target."""

    def __init__(self, coefficients, field="Parameters"):
        self.field = field
        names = [c.name for c in coefficients]
        self.links = {c.name: c.link for c in coefficients if getattr(c, "link", None) is not None}
        by_name = {c.name: c for c in coefficients}
        for target, link in self.links.items():
            if by_name[target].fixed:
                raise FieldError(field, f"{target}: a coefficient cannot be both Fixed and Linked. "
                                        "Choose one of the two.")
            if link.source not in names:
                raise FieldError(field, f"{target}: the link source {link.source} is not a coefficient of this "
                                        "equation. Choose another source or remove the link.")
        self.order = self._order(names)
        self.composed = {}
        for target in self.order:
            link = self.links[target]
            root, factor, offset = self.composed.get(link.source, (link.source, 1.0, 0.0))
            multiplier = link.factor * factor
            intercept = link.factor * offset + link.offset
            if (not isfinite(multiplier) or not isfinite(intercept)
                    or (multiplier == 0 and link.factor != 0 and factor != 0)):
                raise FieldError(field, f"{target}: the combined link exceeds numerical precision. "
                                        "Rescale the coefficients or shorten the chain.")
            self.composed[target] = (root, multiplier, intercept)

    def _order(self, names):
        """Targets with their sources first; a cycle names its path."""
        done, ordered = set(), []
        for start in names:
            if start not in self.links or start in done:
                continue
            path = []
            node = start
            while node in self.links and node not in done:
                if node in path:
                    cycle = path[path.index(node):] + [node]
                    raise FieldError(self.field, "The links form a cycle: " + " → ".join(cycle)
                                     + ". Remove one of the links.")
                path.append(node)
                node = self.links[node].source
            for node in reversed(path):
                done.add(node)
                ordered.append(node)
        return tuple(ordered)

    def __bool__(self):
        return bool(self.links)

    def is_linked(self, name):
        return name in self.links

    def root(self, name):
        """``(root, factor, offset)``: ``name = factor * root + offset`` (identity for an unlinked name)."""
        return self.composed.get(name, (name, 1.0, 0.0))

    def apply(self, values):
        """``values`` with every target recomputed from its source, in dependency order (a new dict)."""
        if not self.links:
            return values
        values = dict(values)
        for target in self.order:
            link = self.links[target]
            values[target] = link.factor * float(values[link.source]) + link.offset
        return values

    def formula(self, name):
        """The typed link and, for a chain, the resolved one: ``D = -0.5*C + 3 (D = -A + 2.5)``."""
        link = self.links[name]
        typed = affine_text(name, link.factor, link.offset, link.source)
        root, factor, offset = self.root(name)
        if root == link.source:
            return typed
        return f"{typed} ({affine_text(name, factor, offset, root)})"

    def dependency_text(self):
        """``A → C → D; B → E``: every chain from its root, in declaration order of the roots."""
        children = {}
        for target in self.order:
            children.setdefault(self.links[target].source, []).append(target)
        roots = []
        for target in self.order:
            root = self.root(target)[0]
            if root not in roots:
                roots.append(root)
        lines = []

        def walk(node, prefix):
            below = children.get(node, [])
            if not below:
                lines.append(prefix)
            for child in below:
                walk(child, f"{prefix} → {child}")

        for root in roots:
            walk(root, root)
        return "; ".join(lines)

    def summary(self):
        """Rows for the fit summary (only when a link exists)."""
        return {"Linked parameters": len(self.links), "Dependency order": self.dependency_text(),
                "Links": "; ".join(self.formula(name) for name in self.order)}

    # -- limits ------------------------------------------------------------------------------------------------
    def carry_limits(self, limits, constant, start, *, where=""):
        """Carry each target's ``[lower, upper]`` onto its root.

        ``limits``: ``{name: [lower, upper]}`` (modified in place for the roots). ``constant``: ``{name: value}``
        for the roots that are not estimated (fixed). ``start``: the starting value of each free root.
        ``where`` prefixes messages that concern one series. Raises ``FieldError`` for an incompatible
        fixed value, an empty range or a start outside the range left by the links.
        """
        narrowed = {}
        for target in self.order:
            root, factor, offset = self.root(target)
            lower, upper = limits[target]
            formula = self.formula(target)
            if factor == 0 or root in constant:
                value = offset if factor == 0 else factor * constant[root] + offset
                if not lower <= value <= upper:
                    raise FieldError(self.field, f"{where}{target}: the link {formula} gives {target} = "
                                                 f"{number_text(value)}, outside its limits "
                                                 f"({_range_text(lower, upper)}). Change the link, the limits "
                                                 f"or the fixed value of {root}.")
                continue
            low, high = root_interval(lower, upper, factor, offset)
            current = limits[root]
            new_low, new_high = max(current[0], low), min(current[1], high)
            if not new_low < new_high:
                raise FieldError(self.field, f"{where}{target}: its limits ({_range_text(lower, upper)}) and the "
                                             f"link {formula} leave no admissible value for {root} within its "
                                             f"limits ({_range_text(*current)}). Widen a limit or change the link.")
            limits[root] = [new_low, new_high]
            narrowed.setdefault(root, []).append(target)
        for root, targets in narrowed.items():
            low, high = limits[root]
            if root in start and not low <= start[root] <= high:
                raise FieldError(self.field, f"{where}{root}: the starting value {number_text(start[root])} lies "
                                             f"outside the range allowed by the links of {', '.join(targets)} "
                                             f"({_range_text(low, high)}). Change the starting value of {root}.")
        return narrowed

    def condition_free(self, condition_names, is_free):
        """Linked coefficients read in a condition whose value moves with a free root."""
        found = []
        for name in condition_names:
            if name not in self.links:
                continue
            root, factor, _ = self.root(name)
            if factor != 0 and is_free(root):
                found.append((name, root))
        return found


def condition_error(found, series=None):
    names = ", ".join(f"{name} (through {root})" for name, root in found)
    where = "" if series is None else f" in series {series!r}"
    return FieldError("Parameters", f"{names} appears in a condition of if(...) and follows a free coefficient "
                                    f"through its link{where}: this fit uses known thresholds and does not "
                                    "estimate change points. Fix the source of the link or remove the link.")


def map_interval(limits, kinds, reasons, factor, offset):
    """The interval of ``factor * root + offset`` from the root's ``[low, high]``; ends swap when factor < 0."""
    low, high = factor * limits[0] + offset, factor * limits[1] + offset
    kinds, reasons = list(kinds), list(reasons)
    if factor < 0:
        low, high = high, low
        kinds.reverse()
        reasons.reverse()
    return [low, high], kinds, reasons
