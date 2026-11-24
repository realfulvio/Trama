"""English and Italian text of the formatting of single points (engine messages and Inspector captions).

The ``point.error.`` entries are the exact English messages of ``analisi.point_style``;
``i18n.translate_message`` matches them. The ``point.reason.`` entries say why a point style is not drawn.
"""

EN = {
    "point.error.count": "Format up to 256 individual points.",
    "point.error.record": "Invalid point style.",
    "point.error.reference": "Invalid point reference.",
    "point.error.series": "Points can be formatted in XY series and scatter plots only.",
    "point.error.fields": "Choose a color, a symbol or a size for the point.",
    "point.error.twice": "A point is formatted twice.",
    "point.item": "Row {row} · X = {x} · Y = {y}",
    "point.status.suspended": "Point formatting is suspended ({count}): {reason}",
    "point.reason.not_drawn": ("Source row {row} is not drawn: it is excluded, has a missing value or "
                               "belongs to another series."),
    "point.reason.no_series": "The series {series} is no longer in this graph.",
    "point.reason.no_rows": "This graph does not record the source rows of its points.",
    "point.reason.no_symbols": ("This XY series is drawn without symbols. Choose Points or Line and points "
                                "in Format graph."),
    "point.reason.breaks": "Point formatting is not drawn while axis breaks are active.",
    "point.reason.mixed": ("This series already gives its points different colors, sizes or symbols, so single "
                           "points cannot be formatted."),
    "point.reason.recipe": "The columns this graph reads changed after the point of row {row} was formatted.",
    "point.reason.not_found": "The point of row {row} cannot be found after the rows changed.",
    "point.reason.ambiguous": ("After the rows changed, identical rows make the point of row {row} uncertain. "
                               "Its style was not given to another row."),
}

IT = {
    "point.error.count": "Formatta al massimo 256 punti singoli.",
    "point.error.record": "Formato del punto non valido.",
    "point.error.reference": "Riferimento al punto non valido.",
    "point.error.series": "I punti si possono formattare solo nelle serie XY e nei grafici a dispersione.",
    "point.error.fields": "Scegli un colore, un simbolo o una dimensione per il punto.",
    "point.error.twice": "Un punto è formattato due volte.",
    "point.item": "Riga {row} · X = {x} · Y = {y}",
    "point.status.suspended": "Il formato dei punti è sospeso ({count}): {reason}",
    "point.reason.not_drawn": ("La riga {row} non è disegnata: è esclusa, ha un valore mancante o appartiene "
                               "a un’altra serie."),
    "point.reason.no_series": "La serie {series} non è più in questo grafico.",
    "point.reason.no_rows": "Questo grafico non registra le righe sorgente dei suoi punti.",
    "point.reason.no_symbols": ("Questa serie XY è disegnata senza simboli. Scegli Punti o Linea e punti "
                                "in Formato grafico."),
    "point.reason.breaks": "Il formato dei punti non viene disegnato con le interruzioni dell’asse attive.",
    "point.reason.mixed": ("Questa serie ha già colori, dimensioni o simboli diversi per i suoi punti: i punti singoli "
                           "non si possono formattare."),
    "point.reason.recipe": "Le colonne lette dal grafico sono cambiate dopo la formattazione del punto della riga {row}.",
    "point.reason.not_found": "Il punto della riga {row} non si trova più dopo la modifica delle righe.",
    "point.reason.ambiguous": ("Dopo la modifica delle righe, righe identiche rendono incerto il punto della riga "
                               "{row}. Il suo stile non è stato dato a un’altra riga."),
}
