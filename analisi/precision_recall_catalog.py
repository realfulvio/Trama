"""Precision–recall curve (0.97): Italian captions and engine messages, in a section of their own.

``analisi.interface_catalog`` merges these two tables at the end of its own. Recipes keep the English keys and
values; sheet titles, column titles and worksheet text stay literal. Each message template names a placeholder at
most once (``analisi.i18n.translate_message`` builds one regular expression per template).
"""

CAPTIONS = {
    "Precision–recall curve": "Curva precisione–richiamo",
    "Outcome": "Esito",
    "Score": "Punteggio",
    "Second score": "Secondo punteggio",
    "Second direction": "Direzione del secondo punteggio",
    "Higher is positive": "Più alto è positivo",
    "Lower is positive": "Più basso è positivo",
}

_E = "prec.error."
MESSAGES = {
    "precision.classic": ("Edit precision–recall curves in Trama's Vetro interface.",
                          "Modifica le curve precisione–richiamo nell’interfaccia Vetro di Trama."),
    _E + "column": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    _E + "reused": ('Column "{name}" is already used for {other}. Choose a different column for {field}.',
                    'La colonna "{name}" è già usata per {other}. Scegli una colonna diversa per {field}.'),
    _E + "code": ("Enter the exact label of the {kind} rows.",
                  "Scrivi l’etichetta esatta delle righe {kind}."),
    _E + "same_label": ("Positive and Negative must be different labels.",
                        "Positiva e Negativa devono essere etichette diverse."),
    _E + "choice": ("Choose a valid value for {field}.", "Scegli un valore valido per {field}."),
    _E + "switch": ("{field} must be on or off.", "{field} deve essere attivo o disattivo."),
    _E + "percent": ("{field} must be a number greater than 0 and less than 100.",
                     "{field} deve essere un numero maggiore di 0 e minore di 100."),
    _E + "whole": ("{field} must be a whole number from {low} to {high}.",
                   "Valore di {field}: inserisci un intero da {low} a {high}."),
    _E + "missing": ('Column "{name}" is not in the table.', 'La colonna "{name}" non è nella tabella.'),
    _E + "duplicate": ('More than one column is called "{name}".', 'Più di una colonna si chiama "{name}".'),
    _E + "numbers": ('Column "{name}" must contain numbers.', 'La colonna "{name}" deve contenere numeri.'),
    _E + "finite": ('Column "{name}" has a value that is not a finite number in row {row}.',
                    'La colonna "{name}" ha un valore che non è un numero finito nella riga {row}.'),
    _E + "unknown": ('Outcome has the value "{value}" in row {row}, which is neither Positive ("{positive}") '
                     'nor Negative ("{negative}").',
                     'L’esito ha il valore "{value}" nella riga {row}, che non è né Positivo ("{positive}") '
                     'né Negativo ("{negative}").'),
    _E + "empty": ("No row has an Outcome and a number in every score column.",
                   "Nessuna riga ha un esito e un numero in ogni colonna dei punteggi."),
    _E + "rows": ("Use at most {limit} rows (this selection has {count}).",
                  "Usa al massimo {limit} righe (questa selezione ne ha {count})."),
    _E + "only_negative": ("All {count} complete rows are Negative; at least one Positive row is needed.",
                           "Tutte le {count} righe complete sono Negative: serve almeno una riga Positiva."),
    _E + "only_positive": ("All {count} complete rows are Positive; at least one Negative row is needed.",
                           "Tutte le {count} righe complete sono Positive: serve almeno una riga Negativa."),
    _E + "work": ("Bootstrap replicates × samples = {a} × {b} exceeds the limit of {limit}.",
                  "Repliche bootstrap × campioni = {a} × {b} supera il limite di {limit}."),
}
