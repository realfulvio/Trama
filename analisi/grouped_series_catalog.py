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
    "grouped.series.placement": ("Placement", "Disposizione"),
    "grouped.placement.beside": ("Beside previous", "Affianca alla precedente"),
    "grouped.placement.overlay": ("Overlay previous", "Sovrapponi alla precedente"),
    "grouped.placement.stack": ("Stack on previous", "Impila sulla precedente"),
    "grouped.placement.gap": ("Separate from previous", "Distanzia dalla precedente"),
    "grouped.placement.first": ("The first series starts the group.", "La prima serie apre il gruppo."),
    "grouped.placement.previous": ("Position relative to {name}.", "Posizione rispetto a {name}."),
    "grouped.placement.stacks_note": (
        "In a stack, intervals refer to individual series. Individual observations stay visible outside the stacks.",
        "Nelle pile gli intervalli si riferiscono alle singole serie. Le osservazioni individuali restano visibili fuori dalle pile.",
    ),
    "grouped.placement.error_value": (
        "Choose a valid placement for each series.", "Scegli una disposizione valida per ogni serie.",
    ),
    "grouped.placement.error_graph": (
        "Choose a grouped bar or center graph with side-by-side or overlaid placement.",
        "Scegli un grafico raggruppato a barre o con centri e una disposizione affiancata o sovrapposta.",
    ),
    "grouped.placement.error_stack": (
        "All series in the same stack must use bars.", "Tutte le serie della stessa pila devono usare le barre.",
    ),
    "grouped.placement.reset_title": ("Reset per-series settings", "Ripristina impostazioni per serie"),
    "grouped.placement.reset_body": (
        "The chosen graph settings require resetting the drawing and placement of individual series. Continue?",
        "Le impostazioni del grafico richiedono il ripristino del disegno e della disposizione per serie. Continuare?",
    ),
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
        "Update the preview with the current settings.",
        "Aggiorna l’anteprima con le impostazioni correnti.",
    ),
}

_ENGLISH_TO_KEY = {
    "Choose a valid placement for each series.": "grouped.placement.error_value",
    "Choose a grouped bar or center graph with side-by-side or overlaid placement.": "grouped.placement.error_graph",
    "All series in the same stack must use bars.": "grouped.placement.error_stack",
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
