"""Subscript and superscript portions of a plain text, kept beside it as ``[start, end, mask]`` spans.

The text stored with an annotation stays plain: ``CO2`` and ``10-3`` are what the payload, the search and a copy
of the text keep. A span marks the characters to draw lowered or raised (``CO₂``, ``10⁻³``); positions are Python
character indexes, as in the Info note styles (``analisi.info``). Spans never cross a line break and never
overlap; the drawing code turns text and spans into a matplotlib math string only at the last moment.
"""
SUBSCRIPT, SUPERSCRIPT = 8, 16
SCRIPT_MASK = SUBSCRIPT | SUPERSCRIPT
MAX_SPANS = 200
INHERITED, UNIFORM, MIXED = "inherited", "uniform", "mixed"

# Characters mathtext reads as markup: each one is spelled out inside a script.
_ESCAPED = {"{": r"\{", "}": r"\}", "\\": r"\backslash ", "^": r"\^{}", "_": r"\_", "$": r"\$", "%": r"\%",
            "&": r"\&", "#": r"\#", "~": r"\~{}", " ": r"\ "}


def validate_spans(text, spans):
    """The canonical list of ``[start, end, mask]`` spans of ``text``; ``ValueError`` for anything else."""
    if not isinstance(spans, (list, tuple)) or len(spans) > MAX_SPANS:
        raise ValueError("Invalid text formatting.")
    result, previous = [], 0
    for span in spans:
        if not isinstance(span, (list, tuple)) or len(span) != 3 or any(type(value) is not int for value in span):
            raise ValueError("Invalid text formatting.")
        start, end, mask = span
        if (not previous <= start < end <= len(text) or mask not in (SUBSCRIPT, SUPERSCRIPT)
                or "\n" in text[start:end] or "\r" in text[start:end]):
            raise ValueError("Invalid text formatting.")
        if result and result[-1][1] == start and result[-1][2] == mask:
            result[-1][1] = end
        else:
            result.append([start, end, mask])
        previous = end
    return result


def _split_lines(text, start, end):
    """The pieces of ``text[start:end]`` between line breaks."""
    pieces, first = [], start
    for index in range(start, end):
        if text[index] in "\r\n":
            if index > first:
                pieces.append((first, index))
            first = index + 1
    if end > first:
        pieces.append((first, end))
    return pieces


def apply_script(text, spans, start, end, mask):
    """``spans`` after the characters ``start`` to ``end`` become a subscript or superscript.

    ``mask`` is ``SUBSCRIPT``, ``SUPERSCRIPT`` or ``None`` to draw those characters normally again. A selection
    that crosses a line break formats each line; the break itself stays normal.
    """
    if mask not in (None, SUBSCRIPT, SUPERSCRIPT):
        raise ValueError("Choose subscript or superscript.")
    start, end = max(0, start), min(len(text), end)
    kept = []
    for first, last, existing in spans:
        if last <= start or first >= end:
            kept.append([first, last, existing])
            continue
        if first < start:
            kept.append([first, start, existing])
        if last > end:
            kept.append([end, last, existing])
    if mask is not None:
        kept.extend([first, last, mask] for first, last in _split_lines(text, start, end))
    kept.sort()
    return validate_spans(text, kept)


def script_state(spans, start, end):
    """``(INHERITED, None)``, ``(UNIFORM, mask)`` or ``(MIXED, None)`` for the characters ``start`` to ``end``."""
    if end <= start:
        return INHERITED, None
    covered, masks = 0, set()
    for first, last, mask in spans:
        overlap = min(last, end) - max(first, start)
        if overlap > 0:
            covered += overlap
            masks.add(mask)
    if not masks:
        return INHERITED, None
    if covered == end - start and len(masks) == 1:
        return UNIFORM, next(iter(masks))
    return MIXED, None


def _script_text(piece, bold, italic):
    body = "".join(_ESCAPED.get(char, char) for char in piece)
    face = {(False, False): "mathrm", (True, False): "mathbf", (False, True): "mathit",
            (True, True): "mathbfit"}[bold, italic]
    return rf"\{face}{{{body}}}"


def mathtext(text, spans, *, bold=False, italic=False):
    """The matplotlib math string of ``text`` with ``spans`` (``$`` outside the spans is escaped)."""
    parts, position = [], 0
    for start, end, mask in spans:
        parts.append(text[position:start].replace("$", r"\$"))
        marker = "_" if mask == SUBSCRIPT else "^"
        parts.append(f"${marker}{{{_script_text(text[start:end], bold, italic)}}}$")
        position = end
    parts.append(text[position:].replace("$", r"\$"))
    return "".join(parts)


def displayed(text, spans, *, bold=False, italic=False):
    """What an annotation hands to matplotlib: the text itself, or its math string when spans exist."""
    return mathtext(text, spans, bold=bold, italic=italic) if spans else text


def check_renders(text, spans, *, bold=False, italic=False):
    """``ValueError`` when matplotlib cannot draw ``spans`` of ``text`` (a script with a character it rejects)."""
    if not spans:
        return
    from matplotlib.mathtext import MathTextParser
    for line in displayed(text, spans, bold=bold, italic=italic).split("\n"):
        try:
            MathTextParser("path").parse(line)
        except Exception as error:
            raise ValueError("Invalid text formatting.") from error
