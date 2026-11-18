"""Dialog parts of the Permutation test for mean difference: captions, choices, notes and error banners.

The recipe keeps the English field names and choices; the dialog shows them through the catalog. Exact hides
Resamples and Seed (they are ignored), and a note under the method says what Auto or Exact would do with the
columns chosen now, so the user sees whether the simulation fields can be used.
"""
from tkinter import ttk

from . import ui_theme
from .graph_dialog import ChoiceBinding
from .i18n import active_language, tr, translate_message, ui
from .mean_permutation import (CHOICE_KEYS, DESIGN, DESIGN_NOTE_KEYS, ERROR_PREFIX, EXACT, FIRST, INDEPENDENT,
                               LABEL_KEYS, MODE, MONTE_CARLO, RESAMPLES, SECOND, SEED, preview, visibility)

HINT = "#486075"
NUMBERS = ("count", "work", "resamples", "units", "limit", "row")


def caption(field):
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def number(text):
    """A whole number written by the engine with English separators, shown in the active language."""
    return text.replace(",", ".") if active_language() == "it" else text


def translate_error(error):
    """An engine or dialog message in the active language; field names inside it become the dialog captions."""
    text = str(error)
    shown = translate_message(text, ERROR_PREFIX, {"field": caption, **dict.fromkeys(NUMBERS, number)})
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The dialog banner: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    named = message.lower()
    if field and field.lower() not in named and label.lower() not in named:
        message = f"{label}: {message}"
    return message


def fields(dialog):
    """Resamples and Seed are hidden when Exact is chosen."""
    if MODE not in dialog.controls:
        return {}
    return visibility(dialog.controls[MODE][1].get())


def parse_seed(text):
    """The Seed entry as an integer of any size; the test itself checks 0 ≤ seed < 2⁶⁴ and names Seed."""
    try:
        return int(str(text).strip())
    except ValueError:
        raise ValueError(f"{SEED} must be a whole number.") from None


def _whole(text, fallback):
    try:
        return int(str(text).strip())
    except ValueError:
        return fallback


def current_options(dialog):
    """The values that decide the method: columns, design, method and the simulation size."""
    controls = dialog.controls
    return {FIRST: controls[FIRST][1].get(), SECOND: controls[SECOND][1].get(), DESIGN: controls[DESIGN][1].get(),
            MODE: controls[MODE][1].get(), RESAMPLES: _whole(controls[RESAMPLES][1].get(), 9_999),
            SEED: _whole(controls[SEED][1].get(), 0)}


def preview_text(data, options):
    """The note under Method: Auto says which way it goes with these columns, Exact how many assignments."""
    mode = options.get(MODE)
    if mode == MONTE_CARLO:
        return tr("perm.preview.monte_carlo")
    planned = preview(data, options) if data is not None else None
    exact = planned is not None and planned["used"] == EXACT
    count = number(f"{planned['assignments']:,}") if exact else None
    if mode == EXACT:
        return tr("perm.preview.exact_count", count=count) if planned else tr("perm.preview.exact")
    if planned is None:
        return tr("perm.preview.auto")
    if planned["used"] == EXACT:
        return tr("perm.preview.auto_exact", count=count)
    return tr("perm.preview.auto_simulate")


def _note(parent, positions, **grid):
    label = ttk.Label(parent, wraplength=ui_theme.px(420), foreground=HINT, justify="left")
    label.grid(row=positions[parent], column=0, columnspan=2, sticky="w", **grid)
    positions[parent] += 1
    return label


def attach(dialog, data_page, test_page, positions):
    """Translate captions and choices, add the design, method and tail notes, and keep them in step."""
    for label, key in LABEL_KEYS.items():
        row = dialog.field_rows.get(label)
        if row is not None:
            row[0].configure(text=tr(key))
    for label, (kind, variable) in dialog.controls.items():
        if not isinstance(kind, tuple):
            continue
        binding = dialog.choice_bindings.get(label)
        if binding is None:
            dialog.choice_bindings[label] = ChoiceBinding(dialog.field_rows[label][1], variable, kind, CHOICE_KEYS)
        else:
            binding.labels_by_value = CHOICE_KEYS
            binding.set_values(kind)
    design_note = _note(data_page, positions, pady=(8, 0))
    method_note = _note(test_page, positions, pady=(8, 0))
    tails_note = _note(test_page, positions, pady=(6, 0))
    tails_note.configure(text=tr("perm.note.tails"))
    dialog.permutation_notes = {"design": design_note, "method": method_note, "tails": tails_note}

    def refresh(*_):
        try:
            options = current_options(dialog)
        except Exception:  # noqa: BLE001 - a half-built dialog shows no note rather than failing
            return
        design_note.configure(text=tr(DESIGN_NOTE_KEYS.get(options[DESIGN], DESIGN_NOTE_KEYS[INDEPENDENT])))
        method_note.configure(text=preview_text(getattr(dialog, "data", None), options))
        dialog.show_fields(fields(dialog))

    for name in (FIRST, SECOND, DESIGN, MODE, RESAMPLES):
        dialog.controls[name][1].trace_add("write", refresh)
    refresh()
    return refresh
