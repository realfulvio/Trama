"""English messages and Italian captions for Yuen's trimmed-mean test.

The engine raises the English strings. ``analisi.i18n`` copies both catalogs; the dialog translates a
raised message by matching it, so the English text here is the contract.
"""

EN = {
    "yuen.method": "Yuen's test for trimmed means",
    "yuen.tab.data": "Data",
    "yuen.tab.test": "Test",
    "yuen.field.trim": "Trimming per tail (%)",
    "yuen.note": "The difference is the trimmed mean of the first sample minus the trimmed mean of the second. "
                 "Each tail drops the whole number of observations equal to n times the trimming percentage, "
                 "floored on the percentage you typed.",
    "yuen.error.format": "Choose a sample format.",
    "yuen.error.trim": "Trimming per tail (%) must be at least 0 and less than 50.",
    "yuen.error.level": "The confidence level must be strictly between 0 and 100.",
    "yuen.error.reverse": "Reverse first and second samples: choose on or off.",
    "yuen.error.column": "Choose a column for {field}.",
    "yuen.error.missing": '{field}: "{name}" is not in the worksheet.',
    "yuen.error.duplicate": 'Worksheet column names must be unique: "{name}" appears more than once.',
    "yuen.error.distinct": "Choose distinct columns for the two samples.",
    "yuen.error.groups": "{field} must contain exactly two non-blank labels; {count} found.",
    "yuen.error.short": "{field}: at least 2 finite observations are needed; {count} found.",
    "yuen.error.short_group": '{field}: group "{sample}" needs at least 2 finite observations; {count} found.',
    "yuen.error.trim_short": '{field}: trimming leaves {kept} observations in "{sample}"; at least 2 must remain.',
    "yuen.error.overflow": "{field}: the values are too large to compute a trimmed mean or its variance.",
    "yuen.error.overflow_group": '{field}: group "{sample}" has values too large to compute a trimmed mean '
                                 "or its variance.",
    "yuen.reason.se": "Inference is not available because the standard error is zero.",
}

IT = {
    "yuen.method": "Test di Yuen per medie troncate",
    "yuen.tab.data": "Dati",
    "yuen.tab.test": "Test",
    "yuen.field.trim": "Troncamento per coda (%)",
    "yuen.note": "La differenza è la media troncata del primo campione meno la media troncata del secondo. "
                 "Da ogni coda si toglie il numero intero di osservazioni pari a n per la percentuale di "
                 "troncamento, con il pavimento calcolato sulla percentuale digitata.",
    "yuen.error.format": "Scegli un formato dei campioni.",
    "yuen.error.trim": "Troncamento per coda (%) deve essere almeno 0 e minore di 50.",
    "yuen.error.level": "Il livello di confidenza deve essere strettamente compreso tra 0 e 100.",
    "yuen.error.reverse": "Inverti primo e secondo campione: scegli sì o no.",
    "yuen.error.column": "Scegli una colonna per {field}.",
    "yuen.error.missing": '{field}: "{name}" non è nel foglio.',
    "yuen.error.duplicate": 'I nomi delle colonne devono essere univoci: "{name}" compare più di una volta.',
    "yuen.error.distinct": "Scegli due colonne diverse per i due campioni.",
    "yuen.error.groups": "{field} deve contenere esattamente due etichette non vuote; trovate {count}.",
    "yuen.error.short": "{field}: servono almeno 2 osservazioni finite; trovate {count}.",
    "yuen.error.short_group": '{field}: il gruppo "{sample}" richiede almeno 2 osservazioni finite; trovate {count}.',
    "yuen.error.trim_short": '{field}: il troncamento lascia {kept} osservazioni in "{sample}"; devono restarne almeno 2.',
    "yuen.error.overflow": "{field}: i valori sono troppo grandi per calcolare la media troncata o la sua varianza.",
    "yuen.error.overflow_group": '{field}: il gruppo "{sample}" ha valori troppo grandi per calcolare la media '
                                 "troncata o la sua varianza.",
    "yuen.reason.se": "L'inferenza non è disponibile perché l'errore standard è zero.",
}


def text(key, **values):
    """The English message the engine raises."""
    return EN[key].format(**values)
