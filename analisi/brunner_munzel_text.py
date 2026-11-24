"""English messages and Italian captions for the Brunner–Munzel test.

The engine raises the English strings. ``analisi.i18n`` copies both catalogs; the dialog
translates a raised message by matching it, so the English text here is the contract.
"""

EN = {
    "bm.method": "Brunner–Munzel test",
    "bm.tab.data": "Data",
    "bm.tab.test": "Test",
    "bm.field.first": "First sample",
    "bm.field.second": "Second sample",
    "bm.field.alternative": "Alternative",
    "bm.field.level": "Confidence level",
    "bm.choice.two_sided": "Two-sided",
    "bm.choice.greater": "Greater",
    "bm.choice.less": "Less",
    "bm.note": "Probability is P(First > Second) + ½ P(First = Second). "
               "T is positive when the first sample tends to be larger. "
               "The p-value and the interval use a Student approximation; "
               "SciPy’s Brunner–Munzel statistic has the opposite sign for the same orientation.",
    "bm.error.column": "Choose a column for {field}.",
    "bm.error.missing": '{field}: "{name}" is not in the worksheet.',
    "bm.error.duplicate": 'Worksheet column names must be unique: "{name}" appears more than once.',
    "bm.error.distinct": "Choose distinct columns for the two samples.",
    "bm.error.level": "Confidence level must be a finite number strictly between 0 and 100.",
    "bm.error.alternative": "Alternative: choose Two-sided, Greater or Less.",
    "bm.error.short": "{field}: at least 2 finite observations are needed; {count} found.",
    "bm.error.boolean": "{field}: source row {row} is boolean; choose a numeric column.",
    "bm.error.not_number": "{field}: source row {row} is not a number ({shown}).",
    "bm.error.not_finite": "{field}: source row {row} must be a finite number.",
    "bm.reason.se": "Inference is not defined because the standard error is zero "
                    "(all ties, complete separation, or another case with no spread in the placement scores).",
    "bm.note.small": "Small samples: the Student approximation for the p-value and the interval "
                     "is less reliable when either sample has fewer than 10 observations.",
    "bm.note.approx": "P-value and confidence interval use a Student approximation with "
                      "Welch–Satterthwaite degrees of freedom on the placement-score variances.",
    "bm.orientation": "First sample compared with Second sample: Probability > ½ and T > 0 "
                      "when values in the first sample tend to be larger.",
}

IT = {
    "bm.method": "Test di Brunner–Munzel",
    "bm.tab.data": "Dati",
    "bm.tab.test": "Test",
    "bm.field.first": "Primo campione",
    "bm.field.second": "Secondo campione",
    "bm.field.alternative": "Ipotesi alternativa",
    "bm.field.level": "Livello di confidenza",
    "bm.choice.two_sided": "Bilaterale",
    "bm.choice.greater": "Maggiore",
    "bm.choice.less": "Minore",
    "bm.note": "La probabilità è P(Primo > Secondo) + ½ P(Primo = Secondo). "
               "T è positivo quando il primo campione tende a essere più grande. "
               "Il p-value e l’intervallo usano un’approssimazione di Student; "
               "la statistica Brunner–Munzel di SciPy ha segno opposto con lo stesso orientamento.",
    "bm.error.column": "Scegli una colonna per {field}.",
    "bm.error.missing": '{field}: "{name}" non è nel foglio.',
    "bm.error.duplicate": 'I nomi delle colonne devono essere univoci: "{name}" compare più di una volta.',
    "bm.error.distinct": "Scegli due colonne diverse per i due campioni.",
    "bm.error.level": "Il livello di confidenza deve essere un numero finito strettamente compreso tra 0 e 100.",
    "bm.error.alternative": "Ipotesi alternativa: scegli Bilaterale, Maggiore o Minore.",
    "bm.error.short": "{field}: servono almeno 2 osservazioni finite; trovate {count}.",
    "bm.error.boolean": "{field}: la riga di origine {row} è booleana; scegli una colonna numerica.",
    "bm.error.not_number": "{field}: la riga di origine {row} non è un numero ({shown}).",
    "bm.error.not_finite": "{field}: la riga di origine {row} deve essere un numero finito.",
    "bm.reason.se": "L’inferenza non è definita perché l’errore standard è zero "
                    "(tutti i pareggi, separazione completa o altro caso senza dispersione nei punteggi di posizione).",
    "bm.note.small": "Campioni piccoli: l’approssimazione di Student per il p-value e l’intervallo "
                     "è meno affidabile quando uno dei due campioni ha meno di 10 osservazioni.",
    "bm.note.approx": "Il p-value e l’intervallo di confidenza usano un’approssimazione di Student "
                      "con gradi di libertà di Welch–Satterthwaite sulle varianze dei punteggi di posizione.",
    "bm.orientation": "Primo campione confrontato con il secondo: Probability > ½ e T > 0 "
                      "quando i valori del primo campione tendono a essere più grandi.",
}


def text(key, **values):
    """The English message the engine raises."""
    return EN[key].format(**values)
