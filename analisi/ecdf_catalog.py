"""Empirical cumulative distribution (ECDF) graph: Italian captions and engine messages.

``analisi.interface_catalog`` merges these two tables at the end of its own. Recipes keep the
canonical English keys and values; sheet titles, column titles and worksheet text stay literal.
"""

CAPTIONS = {
    "Empirical cumulative distribution": "Distribuzione cumulativa empirica",
    "Y axis": "Asse Y",
    "Proportion": "Proporzione",
}

_E = "ecdf.error."
MESSAGES = {
    _E + "unique": ("Worksheet column names must be unique.",
                    "I nomi delle colonne del foglio devono essere univoci."),
    _E + "choice": ("Choose a valid {field}.",
                    "Scegli un valore valido per {field}."),
    _E + "variables": ("Choose 1 to 12 distinct numeric columns.",
                       "Scegli da 1 a 12 colonne numeriche distinte."),
    _E + "max_curves": ("Plot up to {limit} curves at once.",
                        "Puoi tracciare al massimo {limit} curve alla volta."),
    _E + "response": ("Choose a column for Response.",
                      "Scegli una colonna per Risposta."),
    _E + "group": ("Choose an existing grouping column.",
                   "Scegli una colonna di raggruppamento esistente."),
    _E + "same_group": ("Choose a grouping column different from the response.",
                        "Scegli una colonna di raggruppamento diversa dalla risposta."),
    _E + "no_groups": ('Column "{name}" has no group values.',
                       'La colonna "{name}" non contiene valori di gruppo.'),
    _E + "empty_column": ('Column "{name}" has no valid numeric observations.',
                          'La colonna "{name}" non contiene osservazioni numeriche valide.'),
    _E + "empty_group": ('Group "{name}" has no valid numeric observations.',
                         'Il gruppo "{name}" non contiene osservazioni numeriche valide.'),
    _E + "non_numeric": ('Column "{name}" contains text or infinite values.',
                         'La colonna "{name}" contiene testo o valori infiniti.'),
    _E + "complex": ('Column "{name}" contains complex data.',
                     'La colonna "{name}" contiene dati complessi.'),
    _E + "precision": ('Column "{name}" contains integers outside the supported precision.',
                       'La colonna "{name}" contiene interi fuori dalla precisione supportata.'),
    _E + "max_obs": ("Select at most {limit} observations across all curves.",
                     "Seleziona al massimo {limit} osservazioni complessive tra tutte le curve."),
    _E + "range": ("The selected values exceed the numeric range for this graph.",
                   "I valori selezionati superano l’intervallo numerico supportato dal grafico."),
    "ecdf.summary.caption": ("Selection", "Selezione"),
    "ecdf.summary.order": ("Series order: {names}", "Ordine delle serie: {names}"),
    "ecdf.summary.none": ("Choose 1 to 12 numeric columns.", "Scegli da 1 a 12 colonne numeriche."),
    "ecdf.summary.single": ("Response: {response}", "Risposta: {response}"),
    "ecdf.summary.grouped": ("Response: {response} · Group: {group}", "Risposta: {response} · Gruppo: {group}"),
}
