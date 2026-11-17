"""Pairwise comparison brackets on native box, violin and column graphs.

The P values come from an analysis of the same table: the Multiple comparisons
sheet of a one-way ANOVA, the Dunn comparisons sheet of a Kruskal–Wallis test
or the t-test sheet of a paired t-test on two columns. Nothing is recalculated
here and the stored graph recipe never contains P values.

Groups are matched by typed source keys (``category:str:A``, ``column:Before``),
never by the text of a comparison, an axis label or the order of a sheet.

The same section can instead show a compact letter display (``Display`` = Compact letters): one text per
visible group, computed by :mod:`analisi.compact_letters` from the same source rows.
"""
from math import isfinite, log10

from matplotlib.colors import is_color_like
from matplotlib.lines import Line2D
from matplotlib.text import Text
import numpy as np
import pandas as pd

from . import compact_letters as cl

SECTION = "Pairwise comparisons"
ONE_WAY, KRUSKAL, PAIRED_COLUMNS = SOURCE_METHODS = ("One-way ANOVA", "Kruskal–Wallis", "Paired t-test (columns)")
ADJUSTED_SHEETS = {ONE_WAY: "Multiple comparisons", KRUSKAL: "Dunn comparisons"}
FDR = "FDR (Benjamini–Hochberg)"
ALL, SELECTED = SELECTIONS = ("All", "Selected")
STARS, P_VALUE = LABELS = ("Stars", "P value")
NO_FILTER, AT_OR_BELOW = FILTERS = ("All", "At or below cutoff")
DEFAULT_CUTOFF = .05
DEFAULT_COLOR = "#303640"
MAX_BRACKETS = 30
MAX_STORED_PAIRS = 5050
MAX_KEY = 1024
STAR_THRESHOLDS = (.05, .01, .001, .0001)
BRACKETS, LETTERS = DISPLAYS = ("Brackets", "Compact letters")
IDENTIFIER_NAMES = {"Lowercase": "lower", "Uppercase": "upper", "Numbers": "numbers"}
PLACEMENT_NAMES = {"Individual": "individual", "Aligned": "aligned"}
LETTER_SIZES = (8, 18)
DEFAULT_LETTER_SIZE = 10
LETTER_FIELDS = {"Display", "Alpha", "Identifiers", "Letter placement", "Letter size"}
FIELDS = {"Source slot", "Source method", "Selection", "Pairs", "Label", "Filter", "Cutoff", "Color"} | LETTER_FIELDS
LETTERS_SHEET = "Comparison letters"
LETTERS_MEANING = ("Groups that share a letter were not found different by the chosen test (P > alpha); "
                   "a shared letter is not evidence that the groups are equal. Groups without a common letter "
                   "differ with P ≤ alpha.")
COLUMN_STYLES = ("Individual points", "Bars", "Center and interval", "Floating range")
ADJUSTED_NOTE = "Labels use the adjusted P values of the source (Adjusted p column)."
GAP = .04
LABEL_HEIGHT, LABEL_AXES_HEIGHT = 15., 180.


# ---------------------------------------------------------------------------
# Source results


def _probability(value):
    """A finite P value in [0, 1] as float, or None."""
    if value is None or isinstance(value, (bool, np.bool_, str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) and 0 <= number <= 1 else None


def comparison_rows(method, tables, options, endpoint):
    """Rows ``{"left", "right", "p"}`` of a compatible source, in source order.

    ``endpoint`` converts a group label of the source into the typed key used by
    the graph. An incompatible method, an FDR family or a missing sheet gives [].
    """
    if not isinstance(tables, dict) or not isinstance(options, dict):
        return []
    if method in ADJUSTED_SHEETS:
        if method == ONE_WAY and options.get("Post-hoc") == FDR:
            return []
        sheet = tables.get(ADJUSTED_SHEETS[method])
        columns = getattr(sheet, "columns", ())
        if any(name not in columns for name in ("First", "Second", "Adjusted p")):
            return []
        rows = []
        for first, second, adjusted in zip(sheet["First"].tolist(), sheet["Second"].tolist(),
                                           sheet["Adjusted p"].tolist(), strict=True):
            p = _probability(adjusted)
            if p is not None:
                rows.append({"left": endpoint(first), "right": endpoint(second), "p": p})
        return rows
    if method == PAIRED_COLUMNS:
        first, second = options.get("First"), options.get("Second")
        sheet = tables.get("t-test")
        if (not isinstance(first, str) or not isinstance(second, str) or first == second
                or "Value" not in getattr(sheet, "columns", ()) or "p" not in sheet.index):
            return []
        p = _probability(sheet.at["p", "Value"])
        return [] if p is None else [{"left": endpoint(first), "right": endpoint(second), "p": p}]
    return []


# ---------------------------------------------------------------------------
# Labels and bracket placement


def p_label(p, mode):
    """Stars with fixed inclusive thresholds, or the P value rounded to four significant digits."""
    if mode == "p":
        return "p < 0.0001" if p < .0001 else f"p = {p:.4g}"
    count = sum(p <= threshold for threshold in STAR_THRESHOLDS)
    return "*" * count if count else "ns"


def _finite(value):
    if isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _candidates(anchors, comparisons, settings, log):
    """Visible endpoints and the deduplicated pairs that pass the selection and the cutoff."""
    eligible = {}
    for key, anchor in anchors.items():
        x, top = _finite(anchor.get("x")), _finite(anchor.get("top"))
        if x is None or top is None or (log and top <= 0):
            continue
        eligible[key] = anchor["x"], (log10(top) if log else top)
    pairs = settings.get("pairs")
    chosen = None if pairs is None else {frozenset(pair) for pair in pairs}
    cutoff = settings.get("cutoff")
    first = {}
    for row in comparisons:
        left, right, p = row.get("left"), row.get("right"), _probability(row.get("p"))
        if p is None or left not in eligible or right not in eligible:
            continue
        pair = frozenset((left, right))
        if chosen is not None and pair not in chosen:
            continue
        if eligible[left][0] == eligible[right][0]:
            continue
        first.setdefault(pair, (left, right, p))
    matches = []
    for left, right, p in first.values():
        if cutoff is not None and p > cutoff:
            continue
        if eligible[left][0] > eligible[right][0]:
            left, right = right, left
        x0, x1 = eligible[left][0], eligible[right][0]
        matches.append((float(x1) - float(x0), float(x0), float(x1), left, right, p, x0, x1))
    return eligible, matches


def plan_brackets(anchors, comparisons, settings, y_limits, *, yscale="linear", fixed_y=False):
    """Place one bracket per pair in the first free lane. Returns ``(brackets, top, warning)``."""
    low, high = y_limits
    log = yscale == "log"
    eligible, matches = _candidates(anchors, comparisons, settings, log)
    if not matches:
        return [], high, None
    if yscale not in ("linear", "log"):
        return [], high, "Pairwise comparisons need a linear or logarithmic Y axis."
    if not (_finite(low) is not None and _finite(high) is not None and low < high):
        return [], high, "Pairwise comparisons are not drawn on an inverted or empty Y axis."
    if log and low <= 0:
        return [], high, "The logarithmic Y axis has no room for pairwise comparisons."
    if len(matches) > MAX_BRACKETS:
        return [], high, (f"{len(matches)} comparisons exceed the limit of {MAX_BRACKETS} brackets. "
                          "Select fewer pairs or show only P values at or below the cutoff.")
    forward = log10 if log else float
    inverse = (lambda value: 10 ** value) if log else float
    span = forward(high) - forward(low)
    gap = GAP * span
    ceiling = max(top for _, top in eligible.values())
    placed, brackets, top, clipped = [], [], high, False
    for _, start, end, left, right, p, x0, x1 in sorted(matches, key=lambda item: item[:6]):
        occupied = {lane for a, b, lane in placed if start <= b and a <= end}
        lane = next(index for index in range(len(placed) + 1) if index not in occupied)
        placed.append((start, end, lane))
        line = ceiling + (2 + 2 * lane) * gap
        try:
            y, tip_y, text_y, limit = (inverse(value) for value in (line, line - gap / 2, line + gap / 2,
                                                                    line + 1.5 * gap))
        except OverflowError:
            continue
        if not all(isfinite(value) for value in (y, tip_y, text_y, limit)):
            continue
        if fixed_y and text_y > high:
            clipped = True
            continue
        brackets.append({"left": left, "right": right, "label": p_label(p, "p" if settings.get("label") == "p"
                                                                         else "stars"),
                         "lane": lane, "x0": x0, "x1": x1, "y": y, "tip_y": tip_y, "text_y": text_y})
        if not fixed_y:
            top = max(top, limit)
    warning = "Some comparison brackets do not fit below the fixed Y maximum." if clipped else None
    return brackets, top, warning


def effective_count(anchors, comparisons, settings):
    """Number of brackets the settings would draw, before the lane and axis checks."""
    return len(_candidates(anchors, comparisons, settings, False)[1])


# ---------------------------------------------------------------------------
# Stored recipe section


def _key(value):
    return isinstance(value, str) and 0 < len(value) <= MAX_KEY


def read_section(options):
    """Return ``(settings, problem)``. A missing section is the legacy state ``(None, None)``."""
    section = options.get(SECTION) if isinstance(options, dict) else None
    if section is None:
        return None, None
    problem = "The saved pairwise comparison settings are not valid. Open Pairwise Comparisons to set them again."
    if not isinstance(section, dict) or section.keys() - FIELDS:
        return None, problem
    slot = section.get("Source slot")
    if type(slot) is not int or not 0 <= slot < 256 or section.get("Source method") not in SOURCE_METHODS:
        return None, problem
    selection = section.get("Selection", ALL)
    pairs = section.get("Pairs", [])
    if (selection not in SELECTIONS or not isinstance(pairs, list) or len(pairs) > MAX_STORED_PAIRS
            or any(not isinstance(pair, list) or len(pair) != 2 or not all(map(_key, pair)) or pair[0] == pair[1]
                   for pair in pairs)):
        return None, problem
    label, filtering = section.get("Label", STARS), section.get("Filter", NO_FILTER)
    cutoff = section.get("Cutoff", DEFAULT_CUTOFF)
    color = section.get("Color", DEFAULT_COLOR)
    if (label not in LABELS or filtering not in FILTERS or type(cutoff) not in (int, float)
            or not isfinite(cutoff) or not 0 < cutoff <= 1
            or not isinstance(color, str) or len(color) > 40 or not is_color_like(color)):
        return None, problem
    # Optional 0.57 compact letter fields; a 0.57.0 section without them is Brackets.
    display, alpha = section.get("Display", BRACKETS), section.get("Alpha", cl.DEFAULT_ALPHA)
    identifiers = section.get("Identifiers", "Lowercase")
    placement, size = section.get("Letter placement", "Individual"), section.get("Letter size", DEFAULT_LETTER_SIZE)
    if (display not in DISPLAYS or type(alpha) not in (int, float) or not isfinite(alpha) or not 0 < alpha < 1
            or identifiers not in IDENTIFIER_NAMES or placement not in PLACEMENT_NAMES
            or type(size) not in (int, float) or not isfinite(size)
            or not LETTER_SIZES[0] <= size <= LETTER_SIZES[1]):
        return None, problem
    return {"slot": slot, "method": section["Source method"], "selection": selection,
            "pairs": [tuple(pair) for pair in pairs] if selection == SELECTED else None,
            "label": "p" if label == P_VALUE else "stars", "filter": filtering,
            "cutoff": float(cutoff) if filtering == AT_OR_BELOW else None, "stored_cutoff": float(cutoff),
            "color": color, "display": "letters" if display == LETTERS else "brackets", "alpha": float(alpha),
            "identifiers": IDENTIFIER_NAMES[identifiers], "placement": PLACEMENT_NAMES[placement],
            "size": float(size)}, None


def section_record(slot, method, *, selection=ALL, pairs=(), label=STARS, filtering=NO_FILTER,
                   cutoff=DEFAULT_CUTOFF, color=DEFAULT_COLOR, display=BRACKETS, alpha=cl.DEFAULT_ALPHA,
                   identifiers="Lowercase", placement="Individual", size=DEFAULT_LETTER_SIZE):
    """The JSON section stored in the graph recipe. Raises ValueError for invalid choices.

    The bracket choices are kept in Compact letters mode (and the letter choices in Brackets mode),
    so switching back restores them.
    """
    record = {"Source slot": slot, "Source method": method, "Selection": selection,
              "Pairs": [list(pair) for pair in pairs] if selection == SELECTED else [],
              "Label": label, "Filter": filtering, "Cutoff": cutoff, "Color": color, "Display": display,
              "Alpha": alpha, "Identifiers": identifiers, "Letter placement": placement, "Letter size": size}
    settings, problem = read_section({SECTION: record})
    if problem:
        raise ValueError(problem)
    return record


# ---------------------------------------------------------------------------
# Graph and source compatibility


def graph_problem(method, options):
    """Why this graph recipe cannot carry pairwise comparisons, or None."""
    from .category_graphs import COLUMN_GRAPH
    from .distribution_graphs import BOX_VIOLIN, SINGLE

    if method == BOX_VIOLIN:
        if options.get("Input", SINGLE) != SINGLE or not options.get("Group"):
            return "Pairwise comparisons need a box or violin plot of one response by group."
        return None
    if method == COLUMN_GRAPH:
        if options.get("Graph style", COLUMN_STYLES[0]) not in COLUMN_STYLES:
            return "Pairwise comparisons are available for points, bars, center and interval or floating ranges."
        return None
    return "Pairwise comparisons are available on native box, violin and column graphs."


def source_problem(graph_method, graph_options, method, options):
    """Why an analysis of the same table cannot label this graph, or None."""
    from .category_graphs import COLUMN_GRAPH
    from .distribution_graphs import BOX_VIOLIN

    if not isinstance(options, dict):
        return "The comparison source is not valid."
    if graph_method == BOX_VIOLIN and method in ADJUSTED_SHEETS:
        if options.get("Response") != graph_options.get("Response") or options.get("Group") != graph_options.get("Group"):
            return "The comparison source must use the same Response and Group as the graph."
        if method == ONE_WAY:
            posthoc = options.get("Post-hoc", "None")
            if posthoc == FDR:
                return "FDR comparisons are not used as a source for graph brackets."
            if posthoc == "None":
                return "The one-way ANOVA has no multiple comparisons."
        elif options.get("Dunn comparisons", "None") == "None":
            return "The Kruskal–Wallis test has no Dunn comparisons."
        return None
    if graph_method == COLUMN_GRAPH and method == PAIRED_COLUMNS:
        variables = graph_options.get("Variables") or []
        first, second = options.get("First"), options.get("Second")
        if not isinstance(variables, list) or first not in variables or second not in variables or first == second:
            return "The paired t-test must compare two columns that the graph shows."
        return None
    return "This analysis does not provide comparisons for the graph."


def endpoint_resolver(graph_method):
    """Typed key of a source label for the graph."""
    from .category_graphs import COLUMN_GRAPH
    from .distribution_graphs import SINGLE, _identity

    if graph_method == COLUMN_GRAPH:
        return lambda name: f"column:{name}"
    return lambda label: _identity(SINGLE, True, label)


# ---------------------------------------------------------------------------
# Rendering on the figure


def register_anchors(axes, anchors):
    """Graph code records the X center, highest drawn value and display name of each group."""
    axes._tramastat_pairwise_anchors = dict(anchors)


def graph_anchors(axes):
    """Anchors of the groups that are visible now (Inspector visibility applied)."""
    anchors = getattr(axes, "_tramastat_pairwise_anchors", {})
    groups = getattr(axes, "_tramastat_style", {}).get("groups", {})
    return {key: anchor for key, anchor in anchors.items()
            if groups.get(anchor.get("group"), {}).get("visible", True)}


def _base_limits(axes):
    """Y limits without annotations: the explicit style limits, or the analysis/autoscaled range."""
    style = getattr(axes, "_tramastat_style", {})
    options = style.get("axis", {}).get("y", {})
    if "min" in options:
        return (options["min"], options["max"]), True
    defaults = getattr(axes, "_tramastat_defaults", {}).get("axes", {}).get("y")
    if defaults and axes.get_yscale() == defaults["scale"]:
        axes.set_ylim(defaults["limits"], auto=defaults["auto"])
    else:
        axes.set_autoscaley_on(True)
        axes.autoscale_view(scalex=False)
    return axes.get_ylim(), False


def _text_room(low, text_y, log, size=10.):
    """Upper limit that keeps one label line above the highest text position.

    The planned top leaves one gap above the text anchor. On a short axes a label is taller than that gap,
    so autoscale adds the height of a label on an axes of LABEL_AXES_HEIGHT points (a small window).
    The label height scales with the font size (10 pt for brackets).
    """
    forward = log10 if log else float
    share = min(LABEL_HEIGHT * size / 10 / LABEL_AXES_HEIGHT, .5)
    try:
        value = forward(low) + (forward(text_y) - forward(low)) / (1 - share)
        return 10 ** value if log else value
    except (OverflowError, ValueError):
        return text_y


def _clear(axes):
    for artist in getattr(axes, "_tramastat_pairwise_artists", ()):
        artist.remove()
    axes._tramastat_pairwise_artists = []
    axes._tramastat_letters = None


def _font(axes):
    style = getattr(axes, "_tramastat_style", {})
    return {"family": style["font_family"]} if "font_family" in style else {}


def letter_groups(anchors):
    """Keys of the visible groups with a finite X, in X order (then key)."""
    found = [(float(anchor["x"]), key) for key, anchor in anchors.items() if _finite(anchor.get("x")) is not None]
    return [key for _, key in sorted(found)]


def assign_letters(anchors, rows, settings, cache=None):
    """``(groups, letters)`` for the visible groups; raises ValueError when the matrix is incomplete.

    ``cache`` (a dict) keeps the assignment while only the style changes.
    """
    groups = letter_groups(anchors)
    key = (tuple(groups), settings["alpha"], settings["identifiers"])
    if cache is not None and cache.get("key") == key:
        return groups, cache["letters"]
    try:
        letters = cl.compact_letters(groups, rows, alpha=settings["alpha"], identifiers=settings["identifiers"])
    except ValueError as error:
        # The engine names typed keys; the user sees the group names of the graph.
        message = str(error)
        for key in sorted(groups, key=lambda value: -len(str(value))):
            message = message.replace(str(key), str(anchors[key].get("name", key)))
        raise ValueError(message) from None
    if cache is not None:
        cache.clear()
        cache.update(key=key, letters=letters)
    return groups, letters


def _crowded(axes, texts):
    """Whether letter texts overlap each other or run past the sides of the axes, where they would be clipped
    (estimated with the figure's renderer at its current size)."""
    figure = axes.figure
    try:
        renderer = (figure.canvas.get_renderer() if hasattr(figure.canvas, "get_renderer")
                    else figure._get_renderer())
        boxes = [text.get_window_extent(renderer) for text in texts]
        frame = axes.get_window_extent(renderer)
    except Exception:
        return False
    if any(box.x0 < frame.x0 - .5 or box.x1 > frame.x1 + .5 for box in boxes):
        return True
    return any(a.x1 > b.x0 + .5 and b.x1 > a.x0 + .5 and a.y0 < b.y1 and b.y0 < a.y1
               for i, a in enumerate(boxes) for b in boxes[i + 1:])


def _redraw_letters(axes, state):
    settings = state["settings"]
    anchors = graph_anchors(axes)
    try:
        groups, letters = assign_letters(anchors, state["rows"], settings, state.setdefault("cache", {}))
    except ValueError as error:
        axes._tramastat_pairwise_warning = f"Compact letters are not shown. {error}"
        return
    axes._tramastat_letters = {"groups": groups, "letters": letters, "alpha": settings["alpha"],
                               "names": {key: anchors[key].get("name", key) for key in groups}}
    limits, fixed = _base_limits(axes)
    scale = axes.get_yscale()
    labels, top, warning = cl.plan_letters(anchors, letters, limits, yscale=scale, fixed_y=fixed,
                                           placement=settings["placement"])
    size = settings["size"]
    if not fixed and labels:
        top = max(top, _text_room(limits[0], max(label["y"] for label in labels), scale == "log", size))
        if top > limits[1]:
            axes.set_ylim(limits[0], top)
    figure, color, artists = axes.figure, state["color"], []
    for index, label in enumerate(labels):
        text = Text(label["x"], label["y"], label["text"], transform=axes.transData, color=color, ha="center",
                    va="bottom", fontsize=size, label="_pairwise", gid=f"pairwise:letters:{index + 1}", **_font(axes))
        text.set_parse_math(False)
        # Figure-level artists stay out of the axes series, legend handles and data limits.
        figure.add_artist(text)
        text.set_clip_box(axes.bbox)
        artists.append(text)
    axes._tramastat_pairwise_artists = artists
    axes._tramastat_pairwise_brackets = []
    axes._tramastat_letters["drawn"] = [(label["key"], label["text"]) for label in labels]
    if warning is None and artists and _crowded(axes, artists):
        warning = ("Some compact letters overlap or run past the plot area. "
                   "Use a smaller text size, fewer symbols or a wider graph.")
    axes._tramastat_pairwise_warning = warning


def redraw(axes):
    """Remove the previous brackets and draw them again for the current style and visible groups."""
    _clear(axes)
    state = getattr(axes, "_tramastat_pairwise", None)
    if state is None:
        return
    axes._tramastat_pairwise_warning = state.get("message")
    if state.get("message"):
        return
    if state["settings"].get("display") == "letters":
        _redraw_letters(axes, state)
        return
    limits, fixed = _base_limits(axes)
    scale = axes.get_yscale()
    brackets, top, warning = plan_brackets(graph_anchors(axes), state["rows"], state["settings"], limits,
                                           yscale=scale, fixed_y=fixed)
    axes._tramastat_pairwise_warning = warning
    if not fixed and brackets:
        top = max(top, _text_room(limits[0], max(b["text_y"] for b in brackets), scale == "log"))
        if top > limits[1]:
            axes.set_ylim(limits[0], top)
    figure, color = axes.figure, state["color"]
    font = _font(axes)
    artists = []
    for index, bracket in enumerate(brackets):
        x0, x1, y, tip = bracket["x0"], bracket["x1"], bracket["y"], bracket["tip_y"]
        line = Line2D([x0, x0, x1, x1], [tip, y, y, tip], transform=axes.transData, color=color, linewidth=1.1,
                      solid_capstyle="butt", label="_pairwise", gid=f"pairwise:bracket:{index + 1}")
        text = Text((float(x0) + float(x1)) / 2, bracket["text_y"], bracket["label"], transform=axes.transData,
                    color=color, ha="center", va="bottom", fontsize=10, label="_pairwise",
                    gid=f"pairwise:label:{index + 1}", **font)
        text.set_parse_math(False)
        for artist in (line, text):
            # Figure-level artists stay out of the axes series, legend handles and data limits.
            figure.add_artist(artist)
            artist.set_clip_box(axes.bbox)
            artists.append(artist)
    axes._tramastat_pairwise_artists = artists
    axes._tramastat_pairwise_brackets = brackets


def attach(figure, rows, settings, *, message=None):
    """Store the comparisons on the graph and draw them. Style changes redraw through apply_style."""
    from .presentation import capture_defaults

    if figure is None or not figure.axes:
        return
    capture_defaults(figure)
    axes = figure.axes[0]
    axes._tramastat_pairwise = {"rows": list(rows or ()), "settings": settings or {}, "message": message,
                                "color": (settings or {}).get("color", DEFAULT_COLOR)}
    axes._tramastat_after_style = redraw
    redraw(axes)


def pairwise_warning(figure):
    """The message to show next to the graph, or None."""
    if figure is None or not figure.axes:
        return None
    return getattr(figure.axes[0], "_tramastat_pairwise_warning", None)


def drawn_brackets(figure):
    if figure is None or not figure.axes:
        return []
    axes = figure.axes[0]
    return list(getattr(axes, "_tramastat_pairwise_brackets", ())) if getattr(axes, "_tramastat_pairwise_artists", None) else []


def drawn_letters(figure):
    """``[(key, text)]`` of the letters drawn now, in X order."""
    if figure is None or not figure.axes:
        return []
    axes = figure.axes[0]
    state = getattr(axes, "_tramastat_letters", None)
    return list(state.get("drawn", ())) if state else []


def letters_table(figure):
    """The Comparison letters sheet of the current assignment, or None outside a valid letters mode.

    Rows follow the X order of the groups included in the assignment; a label omitted for lack of room
    under a fixed Y maximum keeps its row.
    """
    if figure is None or not figure.axes:
        return None
    state = getattr(figure.axes[0], "_tramastat_letters", None)
    if not state:
        return None
    groups = state["groups"]
    return pd.DataFrame({"Group": [str(state["names"][key]) for key in groups], "Group key": groups,
                         "Letters": [" ".join(state["letters"][key]) for key in groups],
                         "Alpha": [state["alpha"]] * len(groups)})


def sync_letters_table(result):
    """Add, refresh or remove the Comparison letters sheet of a graph result from its figure."""
    if result is None or not isinstance(getattr(result, "tables", None), dict):
        return
    table = letters_table(result.figure)
    if table is None:
        result.tables.pop(LETTERS_SHEET, None)
    else:
        result.tables[LETTERS_SHEET] = table


def plan_settings(settings):
    """The subset of the stored settings that ``plan_brackets`` reads."""
    return {"label": settings["label"], "cutoff": settings["cutoff"], "pairs": settings["pairs"]}
