"""English and Italian text of the labels of the observations (engine messages and Inspector captions).

The ``label.error.`` entries are the exact English messages of ``analisi.observation_labels``;
``i18n.translate_message`` matches them. The ``label.reason.`` entries say why a label is not drawn.
"""

EN = {
    "label.error.count": "Label up to {count} series.",
    "label.error.record": "Invalid label setting.",
    "label.error.series": "Labels are available in XY series and scatter plots only.",
    "label.error.twice_series": "A series has two label settings.",
    "label.error.source": "Invalid label source.",
    "label.error.visibility": "Invalid label visibility.",
    "label.error.color": "Enter a valid label color, for example #2866ae.",
    "label.error.position": "Choose where the label goes: above, below, left or right.",
    "label.error.size": "Enter a label size between {low} and {high} points.",
    "label.error.limit": "Enter a limit of 1 to {high} labels.",
    "label.error.observation": "Invalid label of an observation.",
    "label.error.overrides": "Set the labels of up to {count} individual observations.",
    "label.error.twice": "An observation has two label settings.",
    "label.section": "Data labels",
    "label.hint": ("Write next to each point of the selected series the title of its row or the value of a column. "
                   "Nothing in the worksheet changes."),
    "label.source": "Label from",
    "label.none": "No labels",
    "label.row_title": "Row titles",
    "label.missing_item": "{name} (column no longer in the worksheet)",
    "label.show": "Show the labels of this series",
    "label.color": "Label color",
    "label.position": "Position",
    "label.position.above": "Above the point",
    "label.position.below": "Below the point",
    "label.position.left": "Left of the point",
    "label.position.right": "Right of the point",
    "label.size": "Size (pt)",
    "label.limit": "Maximum labels",
    "label.shown": "{shown} labels shown.",
    "label.omitted": ("{shown} of {total} labels shown: {omitted} omitted because the limit of {limit} was reached. "
                      "The observations you chose to show come first, then the others in worksheet order."),
    "label.nothing": ("No observation of this series has a label to show: an empty, missing or excluded cell "
                      "gives none."),
    "label.point": "Selected point",
    "label.point_none": "Select a point in Single point or on the graph to show or hide its label.",
    "label.point_text": "Row {row} · label: {text}",
    "label.point_empty": "Row {row} · no label: the cell is empty, missing or excluded.",
    "label.point_follow": "As series",
    "label.point_show": "Always show",
    "label.point_hide": "Hide",
    "label.point_first": "Choose the source of the labels of this series first.",
    "label.observations": "Labels set on observations",
    "label.observation_item": "Row {row} · {series} · {state}",
    "label.state.show": "shown",
    "label.state.hide": "hidden",
    "label.reset_selected": "Reset label in list",
    "label.status.suspended": "Data labels are suspended ({count}): {reason}",
    "label.reason.unsupported": "Labels are available in XY series and scatter plots only.",
    "label.reason.no_series": "The series {series} is no longer in this graph.",
    "label.reason.no_rows": "This graph does not record the source rows of its points.",
    "label.reason.no_symbols": ("This XY series is drawn without symbols. Choose Points or Line and points "
                                "in Format graph."),
    "label.reason.breaks": "Labels are not drawn while axis breaks are active.",
    "label.reason.mixed": ("This series already gives its points different colors, sizes or symbols, so its "
                           "observations cannot be labelled one by one."),
    "label.reason.no_data": "This graph does not carry its worksheet, so it cannot read the text of the labels.",
    "label.reason.missing": ("The column {column} is no longer in the worksheet. Choose another source to draw "
                             "the labels again."),
    "label.reason.no_title": "This worksheet has no row title column.",
    "label.reason.not_drawn": ("Source row {row} is not drawn: it is excluded, has a missing value or "
                               "belongs to another series."),
    "label.reason.recipe": "The columns this graph reads changed after the label of row {row} was set.",
    "label.reason.not_found": "The observation of row {row} cannot be found after the rows changed.",
    "label.reason.ambiguous": ("After the rows changed, identical rows make the observation of row {row} uncertain. "
                               "Its label setting was not given to another row."),
}

IT = {
    "label.error.count": "Etichetta al massimo {count} serie.",
    "label.error.record": "Impostazione delle etichette non valida.",
    "label.error.series": "Le etichette sono disponibili solo nelle serie XY e nei grafici a dispersione.",
    "label.error.twice_series": "Una serie ha due impostazioni di etichette.",
    "label.error.source": "Origine delle etichette non valida.",
    "label.error.visibility": "Visibilità delle etichette non valida.",
    "label.error.color": "Inserisci un colore etichetta valido, per esempio #2866ae.",
    "label.error.position": "Scegli dove va l’etichetta: sopra, sotto, a sinistra o a destra.",
    "label.error.size": "Inserisci una dimensione dell’etichetta tra {low} e {high} punti.",
    "label.error.limit": "Inserisci un limite da 1 a {high} etichette.",
    "label.error.observation": "Etichetta di un’osservazione non valida.",
    "label.error.overrides": "Imposta le etichette di al massimo {count} osservazioni singole.",
    "label.error.twice": "Un’osservazione ha due impostazioni di etichetta.",
    "label.section": "Etichette dati",
    "label.hint": ("Scrive accanto a ogni punto della serie selezionata il titolo della sua riga o il valore di una "
                   "colonna. Nel foglio non cambia nulla."),
    "label.source": "Etichetta da",
    "label.none": "Nessuna etichetta",
    "label.row_title": "Titoli delle righe",
    "label.missing_item": "{name} (colonna non più nel foglio)",
    "label.show": "Mostra le etichette di questa serie",
    "label.color": "Colore etichette",
    "label.position": "Posizione",
    "label.position.above": "Sopra il punto",
    "label.position.below": "Sotto il punto",
    "label.position.left": "A sinistra del punto",
    "label.position.right": "A destra del punto",
    "label.size": "Dimensione (pt)",
    "label.limit": "Etichette al massimo",
    "label.shown": "{shown} etichette mostrate.",
    "label.omitted": ("{shown} etichette mostrate su {total}: {omitted} omesse perché si è raggiunto il limite di "
                      "{limit}. Prima vengono le osservazioni che hai scelto di mostrare, poi le altre nell’ordine "
                      "del foglio."),
    "label.nothing": ("Nessuna osservazione di questa serie ha un’etichetta da mostrare: una cella vuota, mancante "
                      "o esclusa non ne dà."),
    "label.point": "Punto selezionato",
    "label.point_none": "Seleziona un punto in Punto singolo o sul grafico per mostrarne o nasconderne l’etichetta.",
    "label.point_text": "Riga {row} · etichetta: {text}",
    "label.point_empty": "Riga {row} · nessuna etichetta: la cella è vuota, mancante o esclusa.",
    "label.point_follow": "Come la serie",
    "label.point_show": "Mostra sempre",
    "label.point_hide": "Nascondi",
    "label.point_first": "Scegli prima l’origine delle etichette di questa serie.",
    "label.observations": "Etichette impostate sulle osservazioni",
    "label.observation_item": "Riga {row} · {series} · {state}",
    "label.state.show": "mostrata",
    "label.state.hide": "nascosta",
    "label.reset_selected": "Ripristina etichetta in elenco",
    "label.status.suspended": "Le etichette dati sono sospese ({count}): {reason}",
    "label.reason.unsupported": "Le etichette sono disponibili solo nelle serie XY e nei grafici a dispersione.",
    "label.reason.no_series": "La serie {series} non è più in questo grafico.",
    "label.reason.no_rows": "Questo grafico non registra le righe sorgente dei suoi punti.",
    "label.reason.no_symbols": ("Questa serie XY è disegnata senza simboli. Scegli Punti o Linea e punti "
                                "in Formato grafico."),
    "label.reason.breaks": "Le etichette non vengono disegnate con le interruzioni dell’asse attive.",
    "label.reason.mixed": ("Questa serie ha già colori, dimensioni o simboli diversi per i suoi punti: le sue "
                           "osservazioni non si possono etichettare una per una."),
    "label.reason.no_data": ("Questo grafico non porta con sé il foglio di lavoro: non può leggere il testo "
                             "delle etichette."),
    "label.reason.missing": ("La colonna {column} non è più nel foglio. Scegli un’altra origine per disegnare di "
                             "nuovo le etichette."),
    "label.reason.no_title": "Questo foglio non ha una colonna dei titoli di riga.",
    "label.reason.not_drawn": ("La riga {row} non è disegnata: è esclusa, ha un valore mancante o appartiene "
                               "a un’altra serie."),
    "label.reason.recipe": "Le colonne lette dal grafico sono cambiate dopo l’impostazione dell’etichetta della riga {row}.",
    "label.reason.not_found": "L’osservazione della riga {row} non si trova più dopo la modifica delle righe.",
    "label.reason.ambiguous": ("Dopo la modifica delle righe, righe identiche rendono incerta l’osservazione della "
                               "riga {row}. La sua impostazione non è stata data a un’altra riga."),
}
