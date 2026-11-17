"""Persistent display names of analyses, kept apart from the statistical options.

A label is literal text chosen for a sheet name (for example by Duplicate family). It is never
translated, never reaches the analysis engine and never changes a calculation. An analysis without a
label keeps the legacy name derived from its method and source.
"""
import unicodedata

MAX_LABEL = 1024
_REFUSED = {"Cc", "Cs", "Zl", "Zp"}


def valid_label(value):
    """True for non-empty literal text with no control, line-break or surrogate characters."""
    return (isinstance(value, str) and 0 < len(value) <= MAX_LABEL and bool(value.strip())
            and not any(unicodedata.category(character) in _REFUSED for character in value))


def validate_labels(labels, count):
    """Return ``labels`` after checking every slot and text, or raise ValueError without side effects."""
    if not isinstance(labels, dict):
        raise ValueError("Invalid saved analysis labels.")
    for slot, label in labels.items():
        if type(slot) is not int or not 0 <= slot < count:
            raise ValueError("Invalid saved analysis label slot.")
        if not valid_label(label):
            raise ValueError("Invalid saved analysis label.")
    return labels


def clean_label(text):
    """Make generated text acceptable as a label: replace refused characters and fit the length limit."""
    text = "".join(" " if unicodedata.category(character) in {"Cc", "Zl", "Zp"}
                   else "�" if unicodedata.category(character) == "Cs" else character for character in text)
    if len(text) > MAX_LABEL:
        text = text[:MAX_LABEL - 1] + "…"
    return text
