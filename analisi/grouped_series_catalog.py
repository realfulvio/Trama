"""Grouped graph per-series drawing styles: English/Italian captions and error messages.

``analisi.interface_catalog`` merges these tables at the end of its own. Recipes keep canonical
English keys and values; series and row titles remain literal.
"""

CAPTIONS = {
    "Series style": "Stile serie",
    "As graph": "Come il grafico",
    "Line and symbols": "Linea e simboli",
}

MESSAGES = {
    "grouped.series.drawing": ("Drawing", "Disegno"),
    "grouped.draw.as_graph": ("As graph", "Come il grafico"),
    "grouped.draw.bars": ("Bars", "Barre"),
    "grouped.draw.symbols": ("Center and interval", "Centro e intervallo"),
    "grouped.draw.line_symbols": ("Line and symbols", "Linea e simboli"),
    "grouped.series.hint_available": (
        "Choose a series. “As graph” inherits the graph’s own Graph style; blank appearance fields keep defaults.",
        "Scegli una serie. «Come il grafico» eredita lo stile globale del grafico; i campi vuoti mantengono i predefiniti.",
    ),
    "grouped.series.unavailable_stacked": (
        "Per-series drawing is unavailable for Stacked and 100% stacked bar placements.",
        "Il controllo Disegno per serie non è disponibile per le disposizioni Impilati e Impilati al 100%.",
    ),
    "grouped.series.unavailable_style": (
        "Per-series drawing is unavailable when Graph style is Individual points or Floating range.",
        "Il controllo Disegno per serie non è disponibile con Osservazioni individuali o Intervalli flottanti.",
    ),
    "grouped.error.stacked_overrides": (
        "Stacked and 100% stacked placements cannot mix per-series drawing styles. Reset every series to “As graph” first.",
        "Le disposizioni Impilati e Impilati al 100% non supportano stili di disegno per serie. Ripristina tutte le serie su «Come il grafico» prima di applicare.",
    ),
    "grouped.error.incompatible_style": (
        "Per-series drawing styles are available for Bars and Center and interval only. Reset every series to “As graph” first.",
        "Gli stili di disegno per serie sono disponibili solo per Barre e Centro e intervallo. Ripristina tutte le serie su «Come il grafico» prima di applicare.",
    ),
    "grouped.error.invalid_series_style": (
        "Choose a valid per-series drawing style: As graph, Bars, Center and interval, or Line and symbols.",
        "Scegli un disegno per serie valido: Come il grafico, Barre, Centro e intervallo o Linea e simboli.",
    ),
    "grouped.confirm.reset_title": ("Reset per-series drawing", "Ripristina disegno per serie"),
    "grouped.confirm.reset_body": (
        "This graph has per-series drawing overrides that are incompatible with this placement or style. Reset every series to “As graph” before applying?",
        "Questo grafico ha serie con un disegno specifico non compatibile con questa disposizione o stile. Vuoi ripristinare tutte le serie su «Come il grafico» prima di applicare?",
    ),
    "graph.format.preview": ("Preview", "Anteprima"),
    "graph.format.preview_hint": (
        "Preview updates the live figure; Cancel restores the original graph.",
        "L’anteprima aggiorna la figura dal vivo; Annulla ripristina il grafico originale.",
    ),
}

_ENGLISH_TO_KEY = {
    "Stacked bars cannot mix per-series drawing styles. Reset every series to As graph first.":
        "grouped.error.stacked_overrides",
    "Per-series drawing styles are available for Bars and Center and interval only. Reset every series to As graph first.":
        "grouped.error.incompatible_style",
    "Choose a valid per-series drawing style.":
        "grouped.error.invalid_series_style",
}


def translate_grouped_error(error):
    from .i18n import tr

    text = str(error)
    if text in _ENGLISH_TO_KEY:
        return tr(_ENGLISH_TO_KEY[text])
    return text
