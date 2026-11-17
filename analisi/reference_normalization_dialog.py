"""Captions and error text for Normalize to references.

The engine stays free of Tk. ``tramastat`` owns the widgets and calls the helpers here.
"""
from .i18n import translate_message, tr, ui
from .reference_normalization import EACH, INDEPENDENT, ROW_MEANS, SUMMARY

LABEL_KEYS = {
    "Zero rows": "reference.field.zero_rows",
    "One rows": "reference.field.one_rows",
}
ERROR_PREFIX = "reference.error."
NOTE_ROWS = "reference.note.rows"
NOTE_ROW_MEANS = "reference.note.row_means"
NOTE_EACH = "reference.note.each"
NOTE_UNCERTAINTY = "reference.note.uncertainty"


def field_caption(name):
    """Dialog caption for a fixed field or role. Worksheet names are not passed here."""
    key = LABEL_KEYS.get(name)
    if key:
        text = tr(key)
        if text != key:
            return text
    return ui(name)


def translate_error(error):
    """Engine or dialog message in the active language.

    ``field`` and ``role`` are fixed identifiers and become captions. A column name in ``name``
    stays exactly as it was written.
    """
    return translate_message(str(error), ERROR_PREFIX, {"field": field_caption, "role": field_caption})


def replicate_note_key(mode, replicates):
    """Note under the replicate choice, or None when that choice does not apply."""
    if mode == SUMMARY or replicates == INDEPENDENT:
        return None
    if replicates == ROW_MEANS:
        return NOTE_ROW_MEANS
    if replicates == EACH:
        return NOTE_EACH
    return None
