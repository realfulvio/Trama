"""Translated captions for analysis fields and choices.

The classic dialog maps each canonical English label to a catalog key through per-analysis tables
(``LABEL_KEYS``/``CHOICE_KEYS`` in the engine modules). The Qt dialog collects the same tables once,
then falls back to the menu captions of ``ui`` and finally to an exact match in the English catalog.
"""
from functools import lru_cache
import importlib

from analisi import i18n
from analisi.i18n import active_language, tr, ui

# Engine modules (no Tk) that publish label and choice tables, with the attribute names they use.
_SOURCES = (
    ("anova_diagnostics", ("LABEL_KEYS",), ("GRAPH_CHOICE_KEYS", "TEST_CHOICE_KEYS")),
    ("anova_marginal_means", ("LABEL_KEYS",), ()),
    ("anova_planned_contrasts", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("competing_risks_workbench", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("equivalence_workbench", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("linear_estimates", ("LABEL_KEYS",), ()),
    ("lognormal_anova", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("lognormal_tests", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("meta_analysis", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("nb2_dialog", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("nonlinear_bands", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("parameter_intervals", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("pca_overlays", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("pca_regression", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("pca_reports", ("LABEL_KEYS",), ()),
    ("pca_retention", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("rank_tests", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("reference_normalization_dialog", ("LABEL_KEYS",), ()),
    ("rmcorr", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("ttest_options", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("yuen", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("brunner_munzel", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("mood_median", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("variance_assumptions", ("LABEL_KEYS",), ()),
    ("variance_ratio", ("LABEL_KEYS",), ("CHOICE_KEYS",)),
    ("xy_errors", ("XY_ERROR_LABEL_KEYS",), ("XY_ERROR_CHOICE_KEYS",)),
)


def _flat(table):
    """Tables map a label to a key, or to a dict of choice keys (heat map layout)."""
    flat = {}
    for label, key in table.items():
        if isinstance(label, str) and isinstance(key, str):
            flat.setdefault(label, key)
        elif isinstance(key, dict):
            flat.update({k: v for k, v in key.items() if isinstance(k, str) and isinstance(v, str)})
    return flat


@lru_cache(maxsize=1)
def _tables():
    labels, choices = {}, {}
    for name, label_attrs, choice_attrs in _SOURCES:
        try:
            module = importlib.import_module(f"analisi.{name}")
        except Exception:  # A module renamed later only loses its captions.
            continue
        for attrs, target in ((label_attrs, labels), (choice_attrs, choices)):
            for attr in attrs:
                table = getattr(module, attr, None)
                if isinstance(table, dict):
                    for label, key in _flat(table).items():
                        target.setdefault(label, key)
    english = {}
    for key, text in i18n._EN.items():
        if isinstance(text, str):
            english.setdefault(text, key)
    return labels, choices, english


def _caption(text, table):
    if active_language() == "en" or not isinstance(text, str) or not text:
        return text
    labels, choices, english = _tables()
    key = table.get(text)
    if key:
        translated = tr(key)
        if translated != key:
            return translated
    shown = ui(text)
    if shown != text:
        return shown
    key = english.get(text)
    return tr(key) if key else text


def field_label(label):
    return _caption(label, _tables()[0])


def choice_label(value):
    return _caption(value, _tables()[1])


def method_label(name):
    return _caption(name, {})
