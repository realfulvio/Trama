"""EN and IT texts of the Curve pipeline: the dialog notes and the messages of its engine.

The engine raises English messages that name their field; ``translate_message`` finds them again through the
English text below (prefix ``curve.pipeline.error.``) and copies the placeholder values literally. The field
captions and the choices (Operation, Smoothing, Half-window …) come from the common interface catalog.
"""

ERROR_PREFIX = "curve.pipeline.error."

EN = {
    "curve.pipeline.note": ("The pipeline reads X and Y as one curve. A row without Y splits it into blocks, and "
                            "differences, areas and smoothing never cross a gap. A difference is placed halfway "
                            "between its two X values; the cumulative area starts again in every block."),
    "curve.pipeline.note.smoothing": ("Savitzky–Golay runs after the operation and needs evenly spaced X inside "
                                      "each block. It gives a descriptive transformation, not a fitted model."),
    "curve.pipeline.error.choice": "{field} must be one of the listed choices.",
    "curve.pipeline.error.finite": "{field} must be a finite number.",
    # The degree message is the more specific one: it must be tried before the general whole-number one.
    "curve.pipeline.error.degree": "Polynomial degree must be a whole number from 0 to {limit} for this half-window.",
    "curve.pipeline.error.whole": "{field} must be a whole number from {low} to {high}.",
    "curve.pipeline.error.column": 'Choose an existing column for {field}: "{column}" is not in the worksheet.',
    "curve.pipeline.error.distinct": "Select distinct columns for X and Y.",
    "curve.pipeline.error.unique": "Worksheet column names must be unique.",
    "curve.pipeline.error.numeric": "Column {column} is not numeric.",
    "curve.pipeline.error.text": "Column {column} has text instead of a number at row {row}.",
    "curve.pipeline.error.infinite": "Column {column} has an infinite value at row {row}.",
    "curve.pipeline.error.rows": "The curve pipeline supports up to {limit} worksheet rows; this sheet has {rows}.",
    "curve.pipeline.error.duplicate": "X must be distinct; the value {value} appears more than once.",
    "curve.pipeline.error.no_y": "Y has no number on a row with a valid X.",
    "curve.pipeline.error.no_block": ("No block has enough points for {operation}: the first difference needs two, "
                                      "the second difference three."),
    "curve.pipeline.error.not_finite": ("The calculation produced a value that is not finite. "
                                        "Rescale X or Y, or choose another operation."),
    "curve.pipeline.error.irregular": ("Savitzky–Golay needs evenly spaced X values; the steps of block {block} "
                                       "differ from the median step by more than {tolerance} of it."),
    "curve.pipeline.error.window": ("No block has the {width} points that this half-window needs. "
                                    "Reduce the half-window or choose a longer curve."),
    # Raised by the dialog itself while it reads the typed numbers.
    "curve.pipeline.error.typed_whole": "{field} must be a whole number.",
    "curve.pipeline.error.typed_number": "{field} must be a number.",
    "curve.pipeline.error.typed_finite": "{field} must be finite.",
    "curve.pipeline.error.typed_range": "{field} exceeds the supported integer range.",
    "curve.pipeline.error.pick": "Choose a column for {field}.",
}

IT = {
    "curve.pipeline.note": ("La pipeline legge X e Y come un’unica curva. Una riga senza Y la divide in blocchi e "
                            "differenze, aree e smussamento non attraversano mai un’interruzione. Una differenza è "
                            "collocata a metà tra i suoi due valori di X; l’area cumulata riparte in ogni blocco."),
    "curve.pipeline.note.smoothing": ("Savitzky–Golay agisce dopo l’operazione e richiede valori di X equidistanti "
                                      "dentro ogni blocco. Dà una trasformazione descrittiva, non un modello "
                                      "adattato."),
    "curve.pipeline.error.choice": "{field} deve essere una delle scelte elencate.",
    "curve.pipeline.error.finite": "{field} deve essere un numero finito.",
    "curve.pipeline.error.degree": ("Il grado del polinomio deve essere un numero intero da 0 a {limit} per questa "
                                    "semilarghezza."),
    "curve.pipeline.error.whole": "{field} deve essere un numero intero da {low} a {high}.",
    "curve.pipeline.error.column": 'Scegli una colonna esistente per {field}: "{column}" non è nel foglio.',
    "curve.pipeline.error.distinct": "Scegli colonne diverse per X e Y.",
    "curve.pipeline.error.unique": "I nomi delle colonne del foglio devono essere univoci.",
    "curve.pipeline.error.numeric": "La colonna {column} non è numerica.",
    "curve.pipeline.error.text": "La colonna {column} contiene testo al posto di un numero alla riga {row}.",
    "curve.pipeline.error.infinite": "La colonna {column} contiene un valore infinito alla riga {row}.",
    "curve.pipeline.error.rows": ("La pipeline della curva accetta fino a {limit} righe del foglio; questo foglio "
                                  "ne ha {rows}."),
    "curve.pipeline.error.duplicate": "I valori di X devono essere distinti; il valore {value} compare più volte.",
    "curve.pipeline.error.no_y": "Y non ha alcun numero in una riga con X valida.",
    "curve.pipeline.error.no_block": ("Nessun blocco ha abbastanza punti per {operation}: la differenza prima ne "
                                      "richiede due, la differenza seconda tre."),
    "curve.pipeline.error.not_finite": ("Il calcolo ha prodotto un valore non finito. Cambia la scala di X o di Y, "
                                        "oppure scegli un’altra operazione."),
    "curve.pipeline.error.irregular": ("Savitzky–Golay richiede valori di X equidistanti; i passi del blocco {block} "
                                       "si discostano dal passo mediano per più di {tolerance} di esso."),
    "curve.pipeline.error.window": ("Nessun blocco ha i {width} punti richiesti da questa semilarghezza. Riduci la "
                                    "semilarghezza o scegli una curva più lunga."),
    "curve.pipeline.error.typed_whole": "{field} deve essere un numero intero.",
    "curve.pipeline.error.typed_number": "{field} deve essere un numero.",
    "curve.pipeline.error.typed_finite": "{field} deve essere finito.",
    "curve.pipeline.error.typed_range": "{field} supera l’intervallo degli interi supportato.",
    "curve.pipeline.error.pick": "Scegli una colonna per {field}.",
}
