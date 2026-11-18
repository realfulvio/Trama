"""Captions, hints and validation messages of Ordinal logistic regression, in English and Italian.

The English ``ord.error.`` entries are the exact messages raised by ``ordinal_logit`` (the engine formats them with
``str.format``). ``i18n.translate_message`` turns them back into the active language and copies the placeholder values
(worksheet text, numbers) literally. Recipes keep the English canonical field names, so nothing here reaches a calculation.
"""

EN = {
    "ord.method": "Ordinal logistic regression",
    "ord.field.order": "Category order",
    "ord.tab.profiles": "Profiles",
    "ord.hint.order": "From the lowest to the highest category. Select a category and move it with Up and Down; "
                      "Reset reads the categories again from the worksheet.",
    "ord.hint.order_empty": "Choose the response and the predictors to read its categories.",
    "ord.hint.order_changed": "The categories in the worksheet changed. New: {added}. No longer used: {removed}. "
                              "Check the order and press Run Analysis.",
    "ord.hint.order_removed": "No longer used: {removed}. Press Reset to read the categories again.",
    "ord.hint.order_added": "New in the worksheet: {added}. Press Reset to read the categories again.",
    "ord.hint.profiles": "Up to 12 profiles. Each gives the predicted probability of every category. "
                         "Show graph draws them as stacked bars.",
    "ord.button.reset": "Reset",
    "ord.error.response_choose": "Choose a column for Response.",
    "ord.error.response_exists": 'Choose an existing column for Response: "{name}" is not in the worksheet.',
    "ord.error.unique": "Worksheet column names must be unique.",
    "ord.error.predictors_none": "Select at least one column for Predictors.",
    "ord.error.predictors_count": "Select 1 to {limit} columns for Predictors; {count} were chosen.",
    "ord.error.predictors_list": "Predictors must be a list of column names.",
    "ord.error.predictors_exists": 'Predictors: "{name}" is not a column of the worksheet.',
    "ord.error.predictors_repeat": 'Predictors: "{name}" is chosen more than once.',
    "ord.error.predictors_response": 'Predictors cannot include the response column "{name}".',
    "ord.error.categorical_list": "Categorical predictors must be a list of column names.",
    "ord.error.categorical_subset": 'Categorical predictors: "{name}" is not one of the chosen Predictors.',
    "ord.error.level": "Confidence level (%) must be a number greater than 0 and less than 100.",
    "ord.error.graph_flag": "Show graph must be on or off.",
    "ord.error.graph_profiles": "Show graph needs at least one profile. Add a profile or turn Show graph off.",
    "ord.error.order_list": "Category order must be a list of category labels.",
    "ord.error.profiles_list": "Profiles must be a list.",
    "ord.error.profiles_many": "Use at most {limit} profiles; {count} were given.",
    "ord.error.profile_shape": "Profile {position} must have a Name and Values.",
    "ord.error.profile_name": "Profile {position} needs a name.",
    "ord.error.profile_repeat": 'Profile names must be distinct: "{name}" appears twice.',
    "ord.error.profile_unknown": 'Profile "{profile}" sets "{name}", which is not a predictor.',
    "ord.error.profile_missing": 'Profile "{profile}" needs a value for {name}.',
    "ord.error.profile_number": 'Profile "{profile}": {name} needs a finite number.',
    "ord.error.profile_category": 'Profile "{profile}": {value} is not a category of {name}.',
    "ord.error.response_value": 'Response column "{name}" holds a value that is neither a number nor text '
                                "(source row {row}).",
    "ord.error.response_infinite": 'Response column "{name}" contains an infinite number (source row {row}).',
    "ord.error.predictor_numeric": 'Predictors: column "{name}" must hold finite numbers; source row {row} has {value}.',
    "ord.error.no_rows": "No complete rows: every row misses the response or a predictor.",
    "ord.error.rows": "Ordinal logistic regression reads up to {limit} complete rows; this worksheet has {count}.",
    "ord.error.levels_few": "The response needs at least {minimum} distinct categories among the complete rows; "
                            "{count} found. For two outcomes use Multiple regression with the Logistic family.",
    "ord.error.levels_many": "The response has more than {limit} distinct categories among the complete rows. "
                             "Choose a column with fewer categories.",
    "ord.error.label_clash": 'The response mixes values of different types that print as the same label "{label}". '
                             "Use one type for each category.",
    "ord.error.order_duplicate": 'Category order lists "{name}" more than once.',
    "ord.error.order_missing": "Category order must list every category used by the complete rows. Missing: {names}.",
    "ord.error.order_extra": "Category order lists categories that are not used by the complete rows: {names}.",
    "ord.error.coefficients": "The model would have {count} coefficients; the limit is {limit}. "
                              "Remove predictors or merge categories.",
    "ord.error.category_levels": 'Categorical predictor "{name}" needs at least 2 categories among the complete rows.',
    "ord.error.term_repeat": 'Two model terms are both named "{name}". Rename a source column.',
    "ord.error.constant": "The predictors include a constant column or a combination that equals a constant. "
                          "The thresholds already play the role of the intercept; remove it.",
    "ord.error.rank": "The predictors are collinear: the model is rank deficient. Remove redundant predictors.",
    "ord.error.too_few": "Only {count} complete rows for {parameters} parameters. Use more rows or fewer predictors.",
    "ord.error.converge": "The estimation did not converge. Check the categories and the predictors for separation "
                          "(a predictor that orders the categories perfectly).",
    "ord.error.separation": "The estimates are not finite or not identified, which is typical of separation "
                            "(a predictor that orders the categories perfectly). Remove the predictor or merge the "
                            "categories involved.",
    "ord.error.thresholds": "Two thresholds are numerically equal, typically because the predictors separate a "
                            "category perfectly. Merge categories or remove the predictor involved.",
    "ord.error.covariance": "The covariance of the estimates is not positive definite, so the model is not identified. "
                            "Check separation and collinearity.",
    "ord.error.range": "The estimates are outside the supported range. Rescale the predictors.",
}

IT = {
    "ord.method": "Regressione logistica ordinale",
    "ord.field.order": "Ordine delle categorie",
    "ord.tab.profiles": "Profili",
    "ord.hint.order": "Dalla categoria più bassa alla più alta. Seleziona una categoria e spostala con Su e Giù; "
                      "Ripristina rilegge le categorie dal foglio.",
    "ord.hint.order_empty": "Scegli la risposta e i predittori per leggere le sue categorie.",
    "ord.hint.order_changed": "Le categorie nel foglio sono cambiate. Nuove: {added}. Non più usate: {removed}. "
                              "Controlla l’ordine e premi Esegui analisi.",
    "ord.hint.order_removed": "Non più usate: {removed}. Premi Ripristina per rileggere le categorie.",
    "ord.hint.order_added": "Nuove nel foglio: {added}. Premi Ripristina per rileggere le categorie.",
    "ord.hint.profiles": "Fino a 12 profili. Ognuno dà la probabilità prevista di ogni categoria. "
                         "Mostra grafico li disegna come barre impilate.",
    "ord.button.reset": "Ripristina",
    "ord.error.response_choose": "Scegli una colonna per Risposta.",
    "ord.error.response_exists": 'Scegli una colonna esistente per Risposta: "{name}" non è nel foglio.',
    "ord.error.unique": "I nomi delle colonne del foglio devono essere univoci.",
    "ord.error.predictors_none": "Seleziona almeno una colonna per Predittori.",
    "ord.error.predictors_count": "Seleziona da 1 a {limit} colonne per Predittori; ne hai scelte {count}.",
    "ord.error.predictors_list": "I predittori devono essere un elenco di nomi di colonna.",
    "ord.error.predictors_exists": 'Predittori: "{name}" non è una colonna del foglio.',
    "ord.error.predictors_repeat": 'Predittori: "{name}" è scelta più di una volta.',
    "ord.error.predictors_response": 'I predittori non possono includere la colonna della risposta "{name}".',
    "ord.error.categorical_list": "I predittori categorici devono essere un elenco di nomi di colonna.",
    "ord.error.categorical_subset": 'Predittori categorici: "{name}" non è fra i predittori scelti.',
    "ord.error.level": "Il livello di confidenza (%) deve essere un numero maggiore di 0 e minore di 100.",
    "ord.error.graph_flag": "Mostra grafico deve essere attivo o disattivo.",
    "ord.error.graph_profiles": "Mostra grafico richiede almeno un profilo. Aggiungi un profilo o disattiva "
                                "Mostra grafico.",
    "ord.error.order_list": "L’ordine delle categorie deve essere un elenco di etichette.",
    "ord.error.profiles_list": "I profili devono essere un elenco.",
    "ord.error.profiles_many": "Usa al massimo {limit} profili; ne hai dati {count}.",
    "ord.error.profile_shape": "Il profilo {position} deve avere un nome e dei valori.",
    "ord.error.profile_name": "Il profilo {position} ha bisogno di un nome.",
    "ord.error.profile_repeat": 'I nomi dei profili devono essere distinti: "{name}" compare due volte.',
    "ord.error.profile_unknown": 'Il profilo "{profile}" imposta "{name}", che non è un predittore.',
    "ord.error.profile_missing": 'Il profilo "{profile}" ha bisogno di un valore per {name}.',
    "ord.error.profile_number": 'Profilo "{profile}": {name} richiede un numero finito.',
    "ord.error.profile_category": 'Profilo "{profile}": {value} non è una categoria di {name}.',
    "ord.error.response_value": 'La colonna della risposta "{name}" contiene un valore che non è né un numero né '
                                "testo (riga origine {row}).",
    "ord.error.response_infinite": 'La colonna della risposta "{name}" contiene un numero infinito '
                                   "(riga origine {row}).",
    "ord.error.predictor_numeric": 'Predittori: la colonna "{name}" deve contenere numeri finiti; la riga origine '
                                   "{row} contiene {value}.",
    "ord.error.no_rows": "Nessuna riga completa: in ogni riga mancano la risposta o un predittore.",
    "ord.error.rows": "La regressione logistica ordinale legge fino a {limit} righe complete; questo foglio ne ha "
                      "{count}.",
    "ord.error.levels_few": "La risposta richiede almeno {minimum} categorie distinte tra le righe complete; ne ho "
                            "trovate {count}. Per due esiti usa la Regressione multipla con la famiglia Logistica.",
    "ord.error.levels_many": "La risposta ha più di {limit} categorie distinte tra le righe complete. Scegli una "
                             "colonna con meno categorie.",
    "ord.error.label_clash": 'La risposta mescola valori di tipo diverso che si scrivono con la stessa etichetta '
                             '"{label}". Usa un solo tipo per ogni categoria.',
    "ord.error.order_duplicate": 'L’ordine delle categorie elenca "{name}" più di una volta.',
    "ord.error.order_missing": "L’ordine delle categorie deve elencare ogni categoria usata dalle righe complete. "
                               "Mancano: {names}.",
    "ord.error.order_extra": "L’ordine delle categorie elenca categorie che le righe complete non usano: {names}.",
    "ord.error.coefficients": "Il modello avrebbe {count} coefficienti; il limite è {limit}. "
                              "Togli predittori o unisci categorie.",
    "ord.error.category_levels": 'Il predittore categorico "{name}" richiede almeno 2 categorie tra le righe '
                                 "complete.",
    "ord.error.term_repeat": 'Due termini del modello si chiamano entrambi "{name}". Rinomina una colonna di origine.',
    "ord.error.constant": "I predittori includono una colonna costante o una combinazione uguale a una costante. "
                          "Le soglie fanno già da intercetta; eliminala.",
    "ord.error.rank": "I predittori sono collineari: il modello ha rango incompleto. Elimina i predittori ridondanti.",
    "ord.error.too_few": "Solo {count} righe complete per {parameters} parametri. Usa più righe o meno predittori.",
    "ord.error.converge": "La stima non converge. Controlla le categorie e i predittori: potrebbe esserci separazione "
                          "(un predittore che ordina perfettamente le categorie).",
    "ord.error.separation": "Le stime non sono finite o non sono identificate, come accade con la separazione "
                            "(un predittore che ordina perfettamente le categorie). Elimina il predittore o unisci "
                            "le categorie coinvolte.",
    "ord.error.thresholds": "Due soglie sono numericamente uguali, di solito perché i predittori separano "
                            "perfettamente una categoria. Unisci le categorie o elimina il predittore coinvolto.",
    "ord.error.covariance": "La covarianza delle stime non è definita positiva, quindi il modello non è identificato. "
                            "Controlla separazione e collinearità.",
    "ord.error.range": "Le stime sono fuori dall’intervallo supportato. Riscala i predittori.",
}
