"""Grouped graph per-series drawing styles: English/Italian captions and error messages.

``analisi.interface_catalog`` merges these tables at the end of its own. Recipes keep canonical
English keys and values; series and row titles remain literal.
"""

CAPTIONS = {
    "Series style": "Stile serie",
    "As graph": "Come il grafico",
    "Line and symbols": "Linea e simboli",
    "Interval direction": "Direzione dell’intervallo",
    "Both sides": "Entrambi i lati",
    "Upper only": "Solo superiore",
    "Lower only": "Solo inferiore",
}

MESSAGES = {
    "grouped.order.invalid": ("Choose a valid order for the grouped series.",
                              "Scegli un ordine valido per le serie raggruppate."),
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
    "grouped.spacing.tab": ("Bar arrangement", "Disposizione barre"),
    "grouped.bars.direction": ("Bar direction", "Direzione delle barre"),
    "grouped.bars.vertical": ("Vertical", "Verticale"),
    "grouped.bars.horizontal": ("Horizontal", "Orizzontale"),
    "grouped.bars.direction_hint": (
        "Axis labels, limits and data-anchored objects follow the bars.",
        "Etichette, limiti degli assi e oggetti ancorati ai dati seguono la direzione delle barre.",
    ),
    "grouped.bars.baseline": ("Bar baseline", "Base delle barre"),
    "grouped.bars.baseline_default": ("0 (default)", "0 (predefinita)"),
    "grouped.bars.baseline_hint": (
        "Set where the bars start. The estimates and their intervals keep their positions.",
        "Imposta il valore da cui partono le barre. Le stime e i loro intervalli mantengono le proprie posizioni.",
    ),
    "grouped.bars.baseline_graph": (
        "A custom baseline requires a grouped bar graph without stacks.",
        "La base personalizzata è disponibile nei grafici a barre raggruppate senza pile.",
    ),
    "grouped.bars.baseline_value": (
        "Enter a finite starting value for the bars.", "Inserisci un valore iniziale finito per le barre.",
    ),
    "grouped.bars.baseline_range": (
        "The distance from the bar baseline exceeds the numeric range.",
        "La distanza dalla base delle barre supera l’intervallo numerico.",
    ),
    "grouped.spacing.custom": ("Custom spacing", "Spaziatura personalizzata"),
    "grouped.spacing.hint": (
        "Distances are percentages of a bar’s width. Zero removes the space.",
        "Le distanze sono percentuali della larghezza di una barra. Zero elimina lo spazio.",
    ),
    "grouped.spacing.adjacent": ("Between bars", "Tra barre adiacenti"),
    "grouped.spacing.groups": ("Extra space between groups", "Spazio aggiuntivo tra gruppi"),
    "grouped.spacing.empty": ("Space for missing values", "Spazio per valori mancanti"),
    "grouped.spacing.leading": ("Before the first bar", "Prima della prima barra"),
    "grouped.spacing.trailing": ("After the last bar", "Dopo l’ultima barra"),
    "grouped.spacing.error_value": (
        "Choose valid percentages for the grouped bar spacing.",
        "Scegli percentuali valide per la spaziatura delle barre raggruppate.",
    ),
    "grouped.spacing.error_graph": (
        "Custom spacing is available for grouped bar graphs.",
        "La spaziatura personalizzata è disponibile nei grafici a barre raggruppate.",
    ),
    "grouped.bars.direction_error": (
        "Horizontal direction is available for grouped bar graphs.",
        "La direzione orizzontale è disponibile nei grafici a barre raggruppate.",
    ),
    "grouped.series.drawing": ("Drawing", "Disegno"),
    "grouped.series.axis": ("Value axis", "Asse dei valori"),
    "grouped.series.axis_hint": (
        "Use the left scale or an independent scale on the right.",
        "Usa la scala a sinistra o una scala indipendente a destra.",
    ),
    "grouped.axis.invalid": (
        "Choose the left or right axis for each grouped series.", "Scegli l’asse sinistro o destro per ogni serie.",
    ),
    "grouped.axis.unavailable": (
        "An independent right axis requires a vertical grouped bar or center graph without global stacking.",
        "L’asse destro indipendente è disponibile nei grafici verticali a barre o con centri senza impilamento globale.",
    ),
    "grouped.axis.stack": ("All series in a stack must use the same value axis.",
                           "Tutte le serie di una pila devono usare lo stesso asse dei valori."),
    "grouped.axis.title": ("Enter an axis title of up to 160 characters.", "Inserisci un titolo dell’asse di massimo 160 caratteri."),
    "grouped.axis.scale": ("Choose a linear or logarithmic right axis.",
                          "Scegli una scala lineare o logaritmica per l’asse destro."),
    "grouped.axis.log_data": (
        "The estimates, visible interval limits and points on the right logarithmic axis must be positive.",
        "Le stime, i limiti visibili degli intervalli e i punti sull’asse destro logaritmico devono essere positivi.",
    ),
    "grouped.axis.log_stack": ("A stack on the right needs a linear axis.",
                              "Una pila a destra richiede un asse lineare."),
    "grouped.axis.log_baseline": ("The baseline of logarithmic bars must be positive.",
                                 "Il valore di partenza delle barre logaritmiche deve essere positivo."),
    "grouped.series.interval_direction": ("Interval direction", "Direzione dell’intervallo"),
    "grouped.interval.both": ("Both sides", "Entrambi i lati"),
    "grouped.interval.upper": ("Upper only", "Solo superiore"),
    "grouped.interval.lower": ("Lower only", "Solo inferiore"),
    "graph.series.interval_color": ("Interval color", "Colore dell’intervallo"),
    "graph.series.interval_width": ("Interval thickness (pt)", "Spessore dell’intervallo (pt)"),
    "graph.series.interval_caps": ("Cap length (pt)", "Lunghezza dei cappucci (pt)"),
    "grouped.interval.color_hint": ("Leave empty to use the series color.", "Lascia vuoto per usare il colore della serie."),
    "grouped.interval.width_hint": ("Leave empty for the default thickness.", "Lascia vuoto per lo spessore predefinito."),
    "grouped.interval.caps_hint": ("Enter 0 to hide the caps.", "Inserisci 0 per nascondere i cappucci."),
    "grouped.interval.caps_error": (
        "Enter a cap length between 0 and 72 points.", "Inserisci una lunghezza dei cappucci da 0 a 72 punti.",
    ),
    "grouped.interval.crossed_limit": (
        "The supplied limit is on the wrong side of the estimate.",
        "Il limite indicato è dalla parte opposta alla stima.",
    ),
    "grouped.series.interval_hint": (
        "Show both ends of the interval, just the upper end or just the lower end for this series.",
        "Mostra entrambe le estremità dell’intervallo, solo quella superiore o solo quella inferiore per questa serie.",
    ),
    "grouped.series.interval_inactive": (
        "Set the interval type in the graph parameters to use this control.",
        "Imposta il tipo di intervallo nei parametri del grafico per usare questo controllo.",
    ),
    "grouped.series.interval_value": (
        "Choose a valid interval direction for each series.", "Scegli una direzione dell’intervallo valida per ogni serie.",
    ),
    "grouped.series.interval_graph": (
        "Per-series interval direction requires a grouped bar or center graph that shows intervals.",
        "Per scegliere la direzione per serie, usa un grafico raggruppato a barre o con centri e intervalli.",
    ),
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
    "Choose the left or right axis for each grouped series.": "grouped.axis.invalid",
    "An independent right axis requires a vertical grouped bar or center graph without global stacking.":
        "grouped.axis.unavailable",
    "All series in a stack must use the same value axis.": "grouped.axis.stack",
    "Enter an axis title of up to 160 characters.": "grouped.axis.title",
    "Choose a linear or logarithmic right axis.": "grouped.axis.scale",
    "The estimates, visible interval limits and points on the right logarithmic axis must be positive.":
        "grouped.axis.log_data",
    "A stack on the right needs a linear axis.": "grouped.axis.log_stack",
    "The baseline of logarithmic bars must be positive.": "grouped.axis.log_baseline",
    "The supplied limit is on the wrong side of the estimate.": "grouped.interval.crossed_limit",
    "A custom baseline requires a grouped bar graph without stacks.": "grouped.bars.baseline_graph",
    "Enter a finite starting value for the bars.": "grouped.bars.baseline_value",
    "The distance from the bar baseline exceeds the numeric range.": "grouped.bars.baseline_range",
    "Enter a cap length between 0 and 72 points.": "grouped.interval.caps_error",
    "Horizontal direction is available for grouped bar graphs.": "grouped.bars.direction_error",
    "Choose a valid interval direction for each series.": "grouped.series.interval_value",
    "Per-series interval direction requires a grouped bar or center graph that shows intervals.":
        "grouped.series.interval_graph",
    "Choose valid percentages for the grouped bar spacing.": "grouped.spacing.error_value",
    "Custom spacing is available for grouped bar graphs.": "grouped.spacing.error_graph",
    "Choose a valid order for the grouped series.": "grouped.order.invalid",
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
