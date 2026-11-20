"""Validate binary logistic model (0.96): Italian captions and engine messages, in a section of their own.

``analisi.interface_catalog`` merges these two tables at the end of its own. Recipes keep the English keys and
values; sheet titles, column titles and worksheet text stay literal. Each message template names a placeholder at
most once (``analisi.i18n.translate_message`` builds one regular expression per template).
"""

CAPTIONS = {
    "Validate binary logistic model": "Valida il modello logistico binario",
    "Folds": "Numero di fold",
    "Validation fold": "Colonna dei fold",
    "Threshold": "Soglia",
    "Calibration bins": "Classi di calibrazione",
    "Graph view": "Vista del grafico",
    "Calibration": "Calibrazione",
    "Precision–recall": "Precisione–richiamo",
    "All panels": "Tutti i pannelli",
}

_E = "logval.error."
MESSAGES = {
    _E + "whole": ("{field}: enter a whole number from {low} to {high}.",
                   "{field}: inserisci un numero intero da {low} a {high}."),
    _E + "fraction": ("{field}: enter a number from 0 to 1.", "{field}: inserisci un numero da 0 a 1."),
    _E + "columns": ("{field}: choose columns from the table.", "{field}: scegli colonne della tabella."),
    _E + "once": ("Select each column only once.", "Seleziona ogni colonna una sola volta."),
    _E + "predictor": ("Choose at least one predictor.", "Scegli almeno un predittore."),
    _E + "missing": ('Column "{name}" is not in the table.', 'La colonna "{name}" non è nella tabella.'),
    _E + "duplicate": ('More than one column is called "{name}".', 'Più di una colonna si chiama "{name}".'),
    _E + "complex": ('Column "{name}" contains complex data.', 'La colonna "{name}" contiene dati complessi.'),
    _E + "text": ('Column "{name}" contains text (source row {row}).',
                  'La colonna "{name}" contiene testo (riga {row} della sorgente).'),
    _E + "infinite": ('Column "{name}" contains an infinite value (source row {row}).',
                      'La colonna "{name}" contiene un valore infinito (riga {row} della sorgente).'),
    _E + "response": ("Choose the response column (0 or 1).", "Scegli la colonna della risposta (0 o 1)."),
    _E + "subset": ("Categorical predictors must also be selected as predictors.",
                    "I predittori categorici devono essere scelti anche tra i predittori."),
    _E + "role": ("The response cannot also be a predictor.", "La risposta non può essere anche un predittore."),
    _E + "view": ("Choose a graph view.", "Scegli una vista del grafico."),
    _E + "fold_choice": ("Choose a column for the validation folds, or none.",
                         "Scegli una colonna per i fold di validazione, oppure nessuna."),
    _E + "fold_role": ("The validation fold column must differ from the response and the predictors.",
                       "La colonna dei fold deve essere diversa dalla risposta e dai predittori."),
    _E + "binary": ('Response "{name}" must hold 0 or 1 (source row {row}: {value}).',
                    'La risposta "{name}" deve contenere 0 o 1 (riga {row} della sorgente: {value}).'),
    _E + "empty": ("No row has a value in the response and in every predictor.",
                   "Nessuna riga ha un valore nella risposta e in tutti i predittori."),
    _E + "rows": ("Use at most {limit} usable rows (this selection has {count}).",
                  "Usa al massimo {limit} righe utilizzabili (questa selezione ne ha {count})."),
    _E + "classes": ("The usable rows need both outcomes, 0 and 1.",
                     "Le righe utilizzabili devono contenere entrambi gli esiti, 0 e 1."),
    _E + "levels": ('Categorical predictor "{name}" needs 2 to {limit} levels (it has {count}).',
                    'Il predittore categorico "{name}" richiede da 2 a {limit} livelli (ne ha {count}).'),
    _E + "terms": ("The model has {count} coefficients after expanding the categories; the limit is {limit}.",
                   "Il modello ha {count} coefficienti dopo l’espansione delle categorie; il limite è {limit}."),
    _E + "per_fold": ("Each outcome needs at least {folds} usable rows, one per fold (outcome {outcome} has "
                      "{count}).",
                      "Ogni esito richiede almeno {folds} righe utilizzabili, una per fold (l’esito {outcome} ne "
                      "ha {count})."),
    _E + "no_code": ("Source row {row} has no fold code.", "La riga {row} della sorgente non ha un codice di fold."),
    _E + "code": ("Source row {row}: fold code {value} is not a whole number from 1 to {folds}.",
                  "Riga {row} della sorgente: il codice di fold {value} non è un intero da 1 a {folds}."),
    _E + "absent": ("Fold {fold} has no usable rows: use codes 1 to {folds}.",
                    "Il fold {fold} non ha righe utilizzabili: usa i codici da 1 a {folds}."),
    _E + "test_classes": ("The test rows of fold {fold} need both outcomes, 0 and 1.",
                          "Le righe di test del fold {fold} devono contenere entrambi gli esiti, 0 e 1."),
    _E + "few": ("The model has {terms} coefficients and only {count} usable rows.",
                 "Il modello ha {terms} coefficienti e solo {count} righe utilizzabili."),
    _E + "rank": ("The model is rank deficient. Remove redundant or constant predictors.",
                  "Il modello non ha rango pieno. Rimuovi i predittori ridondanti o costanti."),
    _E + "separation": ("Fold {fold}: the training rows are separated (complete or quasi-complete separation), "
                        "so the logistic fit has no finite estimate. Change the predictors, the folds or the seed.",
                        "Fold {fold}: le righe di addestramento sono separate (separazione completa o quasi "
                        "completa), quindi il fit logistico non ha una stima finita. Cambia i predittori, i fold "
                        "o il seme."),
    _E + "convergence": ("Fold {fold}: the logistic fit did not converge on the training rows (no separation was "
                         "found). Check the scale and variance of the predictors.",
                         "Fold {fold}: il fit logistico non converge sulle righe di addestramento (non è stata "
                         "trovata separazione). Controlla la scala e la varianza dei predittori."),
    _E + "condition": ("Fold {fold}: the logistic fit is ill-conditioned on the training rows. Remove nearly "
                       "redundant predictors.",
                       "Fold {fold}: il fit logistico è mal condizionato sulle righe di addestramento. Rimuovi i "
                       "predittori quasi ridondanti."),
    _E + "fold_rank": ("Fold {fold}: the training design is rank deficient. A predictor is constant or redundant "
                       "in the training rows of this fold.",
                       "Fold {fold}: la matrice del modello non ha rango pieno sulle righe di addestramento. Un "
                       "predittore è costante o ridondante in queste righe."),
    _E + "unseen": ('Fold {fold}: level "{level}" of "{name}" occurs in the test rows but not in the training '
                    "rows. Merge rare levels, or change the folds or the seed.",
                    'Fold {fold}: il livello "{level}" di "{name}" compare nelle righe di test ma non in quelle di '
                    "addestramento. Unisci i livelli rari, oppure cambia i fold o il seme."),
    _E + "pure": ('Fold {fold}: every training row with level "{level}" of "{name}" has outcome {outcome} '
                  "(quasi-complete separation). Merge rare levels, or change the folds or the seed.",
                  'Fold {fold}: tutte le righe di addestramento con il livello "{level}" di "{name}" hanno esito '
                  "{outcome} (separazione quasi completa). Unisci i livelli rari, oppure cambia i fold o il seme."),
    _E + "single": ('Fold {fold}: "{name}" has a single level in the training rows.',
                    'Fold {fold}: "{name}" ha un solo livello nelle righe di addestramento.'),
    _E + "train_rows": ("Fold {fold}: {count} training rows are not enough for the model coefficients.",
                        "Fold {fold}: {count} righe di addestramento non bastano per i coefficienti del modello."),
}
