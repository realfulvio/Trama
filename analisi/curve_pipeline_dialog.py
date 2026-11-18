"""Dialog parts of the Curve pipeline: the notes under the options and the banner of an engine error.

The engine keeps raising English messages that name their field. ``describe_error`` shows them in the active
language and puts the field caption in front when the message does not already name it, like the banners of the
other analyses.
"""
import re

from .curve_pipeline_text import ERROR_PREFIX
from .i18n import DEFAULT_LANGUAGE, active_language, translate_message, ui

GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")
NOTE_KEYS = ("curve.pipeline.note", "curve.pipeline.note.smoothing")


def number(text):
    """A count written with English thousands separators (200,000), in the separators of the active language."""
    if active_language() != DEFAULT_LANGUAGE and GROUPED.fullmatch(text):
        return text.replace(",", ".")
    return text


def caption(field):
    return ui(field)


def translate_error(error):
    """An engine or dialog message in the active language; field and operation names become their captions."""
    converters = {"field": caption, "operation": ui, "limit": number, "rows": number}
    return translate_message(str(error), ERROR_PREFIX, converters)


def describe_error(error, field=None):
    """The dialog banner for an error: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    named = message.lower()
    if field and field.lower() not in named and label.lower() not in named:
        message = f"{label}: {message}"
    return message


def notes_visibility(method, smoothing, pipeline, savitzky_golay):
    """Which of the two notes show: the pipeline note with the pipeline, the smoothing note with smoothing on."""
    shown = method == pipeline
    return (shown, shown and smoothing == savitzky_golay)
