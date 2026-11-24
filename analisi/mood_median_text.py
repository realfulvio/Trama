"""English messages and Italian captions for Mood's median test.

The engine raises the English strings. ``analisi.i18n`` copies both catalogs; the dialog
translates a raised message by matching it, so the English text here is the contract.
"""

EN = {
    "mood.method": "Mood median test",
    "mood.tab.data": "Data",
    "mood.tab.test": "Test",
    "mood.field.variables": "Variables",
    "mood.field.ties": "Ties",
    "mood.field.yates": "Yates correction",
    "mood.choice.below": "Below",
    "mood.choice.above": "Above",
    "mood.choice.ignore": "Ignore",
    "mood.note": "Compares medians of two or more independent samples in separate columns. "
                 "Counts are taken against the pooled median; Ties places values equal to that "
                 "median Below (default), Above, or Ignore. Yates correction applies only with "
                 "exactly two samples. Pearson χ² uses k−1 degrees of freedom.",
    "mood.error.variables": "Choose at least two distinct numeric columns for Variables.",
    "mood.error.missing": 'Variables: "{name}" is not in the worksheet.',
    "mood.error.duplicate": 'Worksheet column names must be unique: "{name}" appears more than once.',
    "mood.error.ties": "Ties: choose Below, Above or Ignore.",
    "mood.error.yates": "Yates correction must be on or off.",
    "mood.error.short": 'Variables "{name}": at least 2 finite observations are needed; {count} found.',
    "mood.error.boolean": 'Variables "{name}": source row {row} is boolean; choose a numeric column.',
    "mood.error.not_number": 'Variables "{name}": source row {row} is not a number ({shown}).',
    "mood.error.not_finite": 'Variables "{name}": source row {row} must be a finite number.',
    "mood.reason.margin": "Inference is not defined because a contingency-table margin is zero "
                          "(complete separation relative to the pooled median, or Ignore emptied a sample).",
    "mood.reason.ignore": "Inference is not defined because Ties = Ignore left at least one sample "
                          "with no observations above or below the pooled median.",
    "mood.note.expected": "At least one expected frequency is below 5; the chi-square approximation "
                          "may be unreliable.",
    "mood.note.yates_inactive": "Yates correction is ignored when more than two samples are selected.",
    "mood.note.pearson": "Pearson χ² on the 2×k table of counts above and below the pooled median, "
                         "with upper-tail p-value and k−1 degrees of freedom.",
}

IT = {
    "mood.method": "Test delle mediane di Mood",
    "mood.tab.data": "Dati",
    "mood.tab.test": "Test",
    "mood.field.variables": "Variabili",
    "mood.field.ties": "Pareggi",
    "mood.field.yates": "Correzione di Yates",
    "mood.choice.below": "Sotto",
    "mood.choice.above": "Sopra",
    "mood.choice.ignore": "Ignora",
    "mood.note": "Confronta le mediane di due o più campioni indipendenti in colonne distinte. "
                 "I conteggi sono rispetto alla mediana complessiva; Pareggi colloca i valori "
                 "uguali a quella mediana Sotto (predefinito), Sopra o Ignora. La correzione di "
                 "Yates vale solo con esattamente due campioni. Il χ² di Pearson usa k−1 gradi "
                 "di libertà.",
    "mood.error.variables": "Scegli almeno due colonne numeriche distinte per Variabili.",
    "mood.error.missing": 'Variabili: "{name}" non è nel foglio.',
    "mood.error.duplicate": 'I nomi delle colonne devono essere univoci: "{name}" compare più di una volta.',
    "mood.error.ties": "Pareggi: scegli Sotto, Sopra o Ignora.",
    "mood.error.yates": "La correzione di Yates deve essere attiva o disattiva.",
    "mood.error.short": 'Variabili "{name}": servono almeno 2 osservazioni finite; trovate {count}.',
    "mood.error.boolean": 'Variabili "{name}": la riga di origine {row} è booleana; scegli una colonna numerica.',
    "mood.error.not_number": 'Variabili "{name}": la riga di origine {row} non è un numero ({shown}).',
    "mood.error.not_finite": 'Variabili "{name}": la riga di origine {row} deve essere un numero finito.',
    "mood.reason.margin": "L’inferenza non è definita perché un margine della tabella di contingenza è nullo "
                          "(separazione completa rispetto alla mediana complessiva, oppure Ignora ha "
                          "svuotato un campione).",
    "mood.reason.ignore": "L’inferenza non è definita perché Pareggi = Ignora ha lasciato almeno un "
                          "campione senza osservazioni sopra o sotto la mediana complessiva.",
    "mood.note.expected": "Almeno una frequenza attesa è inferiore a 5; l’approssimazione del chi-quadro "
                          "può essere inaffidabile.",
    "mood.note.yates_inactive": "La correzione di Yates è ignorata quando sono selezionati più di due campioni.",
    "mood.note.pearson": "χ² di Pearson sulla tabella 2×k dei conteggi sopra e sotto la mediana complessiva, "
                         "con p-value della coda superiore e k−1 gradi di libertà.",
}


def text(key, **values):
    """The English message the engine raises."""
    return EN[key].format(**values)
