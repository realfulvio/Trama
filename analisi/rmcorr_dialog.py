"""Dialog parts of Repeated-measures correlation: captions, notes and the translated error banner.

The engine (``rmcorr``) raises English messages that name their field. Here they are shown in the active language,
with the field caption of the dialog in front when the message does not already name it. Column names, subject
labels and typed values inside a message are copied literally.
"""
import re

from .i18n import DEFAULT_LANGUAGE, active_language, tr, translate_message, ui
from .rmcorr import ERROR_PREFIX, LABEL_KEYS

NOTE_MODEL, NOTE_BOOTSTRAP = "rmcorr.note.model", "rmcorr.note.bootstrap"


def caption(field):
    """The dialog caption of a field; unknown names stay literal."""
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def number(text):
    """A count written with English thousands separators (2,000,000), in the separators of the active language."""
    if active_language() != DEFAULT_LANGUAGE:
        return text.replace(",", ".")
    return text


def translate_error(error):
    text = str(error)
    converters = {"field": caption, "low": number, "high": number, "limit": number, "count": number,
                  "work": number}
    shown = translate_message(text, ERROR_PREFIX, converters)
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The banner text: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    if field and not (_names(message, field) or _names(message, label)):
        message = f"{label}: {message}"
    return message


def _names(message, name):
    """True when the message names the field itself; quoted worksheet text such as a column name does not count."""
    bare = re.sub(r'"[^"]*"', "", message)
    return re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", bare) is not None
