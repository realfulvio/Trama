"""English and Italian text of Weibull AFT regression: captions, choices, hints and every validation message.

This is a leaf module (it imports nothing from Trama) so the engine can take its messages from here and ``i18n``
can merge the catalogs without a cycle. The engine raises the English text; ``translate_message`` with the prefix
``weibull.error.`` shows it in the active language. In a template, ``{field}``, ``{role}`` and ``{first}`` are
the canonical names of dialog fields (the dialog converts them to captions); every other placeholder is a
worksheet value that is copied literally. Recipes keep the English field names and choice values.
"""

# Field captions, tabs and fixed choices: key suffix -> (English, Italian).
INTERFACE = {
    "tab.data": ("Data", "Dati"),
    "tab.model": ("Model", "Modello"),
    "tab.predicted": ("Predicted survival", "Sopravvivenza prevista"),
    "field.time": ("Time", "Tempo"),
    "field.event": ("Event", "Evento"),
    "field.event_value": ("Event value", "Valore dell’evento"),
    "field.censor_value": ("Censor value", "Valore di censura"),
    "field.predictors": ("Predictors", "Predittori"),
    "field.categorical": ("Categorical predictors", "Predittori categoriali"),
    "field.shape_mode": ("Shape mode", "Modalità della forma"),
    "field.shape": ("Shape", "Forma"),
    "field.level": ("Confidence level (%)", "Livello di confidenza (%)"),
    "field.profiles": ("Profiles", "Profili"),
    "field.times": ("Times", "Tempi"),
    "field.show_graph": ("Show graph", "Mostra il grafico"),
    "choice.estimated": ("Estimated ML", "Stimata (massima verosimiglianza)"),
    "choice.fixed": ("Fixed", "Fissa"),
    "hint.model": (
        "A time ratio above 1 stretches the distribution of times for comparable predictors; below 1 it shortens "
        "it. Right-censored times and one Weibull shape for all rows are assumed. With an estimated shape the "
        "standard errors include its uncertainty; with a fixed shape they do not.",
        "Un rapporto dei tempi maggiore di 1 allunga la distribuzione dei tempi a predittori confrontabili; "
        "minore di 1 la accorcia. Si assumono tempi censurati a destra e una sola forma di Weibull per tutte le "
        "righe. Con la forma stimata gli errori standard ne includono l’incertezza; con la forma fissa no."),
    "hint.profiles": (
        "Up to 12 profiles. Curves are point estimates of the fitted model; times beyond the longest observed "
        "time are extrapolated and marked.",
        "Fino a 12 profili. Le curve sono stime puntuali del modello adattato; i tempi oltre il più lungo "
        "osservato sono estrapolati e contrassegnati."),
    "hint.times": (
        "Optional. One time per line, not negative and strictly increasing. Left empty, 101 points are used from "
        "0 to the longest observed time. Blank lines are ignored.",
        "Facoltativo. Un tempo per riga, non negativo e strettamente crescente. Se vuoto, si usano 101 punti da "
        "0 al tempo osservato più lungo. Le righe vuote sono ignorate."),
    "hint.status": (
        "The codes are read as the type of the Event column. Text matches exactly as written.",
        "I codici sono letti come il tipo della colonna dell’evento. Il testo deve coincidere esattamente."),
    "profile.hint": (
        "Up to 12 profiles. Predictions use this fit and its reference levels.",
        "Fino a 12 profili. Le previsioni usano questo adattamento e i suoi livelli di riferimento."),
    "interface.Weibull AFT regression": ("Weibull AFT regression", "Regressione Weibull AFT"),
}

# Validation messages: key -> (English, Italian).
ERRORS = {
    "choose": ("Choose a column for {role}.", "Scegli una colonna per {role}."),
    "exists": ('Choose an existing column for {role}: "{name}" is not in the worksheet.',
               'Scegli una colonna esistente per {role}: "{name}" non è nel foglio.'),
    "unique": ("Worksheet column names must be unique.", "I nomi delle colonne del foglio devono essere univoci."),
    "different": ("Choose different columns for {first} and {role}.", "Scegli colonne diverse per {first} e {role}."),
    "time_predictor": ("The Time column cannot also be a predictor.",
                       "La colonna del tempo non può essere anche un predittore."),
    "event_predictor": ("The Event column cannot also be a predictor.",
                        "La colonna dell’evento non può essere anche un predittore."),
    "columns_list": ("{field}: choose columns from the worksheet.", "{field}: scegli colonne del foglio."),
    "predictors_many": ("Choose up to {limit} predictors; {count} were selected.",
                        "Scegli al massimo {limit} predittori; ne hai scelti {count}."),
    "predictors_repeat": ("Predictors must be distinct columns: {name} appears twice.",
                          "I predittori devono essere colonne distinte: {name} compare due volte."),
    "categorical_subset": ('Categorical predictor "{name}" must also be one of the predictors.',
                           'Il predittore categoriale "{name}" deve essere anche uno dei predittori.'),
    "rows": ("Weibull AFT regression reads up to {limit} rows; this worksheet has {count}.",
             "La regressione Weibull AFT legge fino a {limit} righe; questo foglio ne ha {count}."),
    "numeric": ('Column "{name}" contains non-numeric or infinite data.',
                'La colonna "{name}" contiene dati non numerici o infiniti.'),
    "numeric_type": ('Column "{name}" must be numeric.', 'La colonna "{name}" deve essere numerica.'),
    "no_complete": ("No complete rows: every row misses the time, the status or a predictor.",
                    "Nessuna riga completa: in ogni riga mancano il tempo, lo stato o un predittore."),
    "time_value": ("Source row {row}: time {value} must be a finite number greater than 0.",
                   "Riga origine {row}: il tempo {value} deve essere un numero finito maggiore di 0."),
    "no_events": ("No complete row records an event: at least one event is needed.",
                  "Nessuna riga completa registra un evento: serve almeno un evento."),
    "code_missing": ("Enter a value for {field}.", "Inserisci un valore per {field}."),
    "code_numeric": ('{field} must be a number because column "{name}" is numeric.',
                     '{field} deve essere un numero perché la colonna "{name}" è numerica.'),
    "status_complex": ('Column "{name}" contains complex data.', 'La colonna "{name}" contiene dati complessi.'),
    "status_same": ("Event and censor values must be different.",
                    "I valori di evento e di censura devono essere diversi."),
    "status_unknown": ("Source row {row}: column \"{name}\" holds {value}, which is neither the event value nor the "
                       "censor value. Values present: {shown}.",
                       "Riga origine {row}: la colonna \"{name}\" contiene {value}, che non è né il valore "
                       "dell’evento né il valore di censura. Valori presenti: {shown}."),
    "status_no_event": ('No row of "{name}" equals the event value {value}. Values present: {shown}.',
                        'Nessuna riga di "{name}" è uguale al valore dell’evento {value}. Valori presenti: {shown}.'),
    "levels": ('Categorical predictor "{name}" needs at least 2 levels among the rows used.',
               'Il predittore categoriale "{name}" richiede almeno 2 livelli tra le righe usate.'),
    "coefficients": ("The model would have {count} coefficients (intercept included); the limit is {limit}.",
                     "Il modello avrebbe {count} coefficienti (intercetta inclusa); il limite è {limit}."),
    "duplicate": ('Duplicate model term "{term}". Rename the source column.',
                  'Termine del modello duplicato "{term}". Rinomina la colonna di origine.'),
    "collinear": ("The predictors are collinear: the term {term} adds no information. Remove a redundant "
                  "predictor.",
                  "I predittori sono collineari: il termine {term} non aggiunge informazione. Rimuovi un "
                  "predittore ridondante."),
    "collinear_combination": ("The predictors are collinear: some combination of them adds no information. Remove "
                              "a redundant predictor.",
                              "I predittori sono collineari: una loro combinazione non aggiunge informazione. "
                              "Rimuovi un predittore ridondante."),
    "extreme_lowest": ("The coefficient of {term} cannot be estimated: every event has the lowest value of this "
                       "term ({value}), so the likelihood has no finite maximum. Merge levels or remove the "
                       "predictor.",
                       "Il coefficiente di {term} non può essere stimato: ogni evento ha il valore più basso di "
                       "questo termine ({value}), quindi la verosimiglianza non ha un massimo finito. Unisci i "
                       "livelli o rimuovi il predittore."),
    "extreme_highest": ("The coefficient of {term} cannot be estimated: every event has the highest value of this "
                        "term ({value}), so the likelihood has no finite maximum. Merge levels or remove the "
                        "predictor.",
                        "Il coefficiente di {term} non può essere stimato: ogni evento ha il valore più alto di "
                        "questo termine ({value}), quindi la verosimiglianza non ha un massimo finito. Unisci i "
                        "livelli o rimuovi il predittore."),
    "diverged": ("The model has no finite maximum: the coefficients grow without limit. Review the predictors.",
                 "Il modello non ha un massimo finito: i coefficienti crescono senza limite. Controlla i "
                 "predittori."),
    "not_converged": ("The fit did not converge in {limit} iterations. Review the predictors or use a fixed shape.",
                      "L’adattamento non è convergito in {limit} iterazioni. Controlla i predittori o usa una "
                      "forma fissa."),
    "shape_edge": ("The estimated shape lies at the edge of its range ({low} to {high}): the likelihood has no "
                   "interior maximum. Use a fixed shape or review the data.",
                   "La forma stimata è al bordo del suo intervallo ({low} – {high}): la verosimiglianza non ha un "
                   "massimo interno. Usa una forma fissa o controlla i dati."),
    "information": ("The information matrix cannot be inverted, so the standard errors are not usable.",
                    "La matrice di informazione non è invertibile, quindi gli errori standard non sono "
                    "utilizzabili."),
    "conditioning": ("The information matrix is nearly singular: some coefficient is not determined by these data. "
                     "Review the predictors.",
                     "La matrice di informazione è quasi singolare: qualche coefficiente non è determinato da "
                     "questi dati. Controlla i predittori."),
    "not_finite": ("The estimates are not finite for these data.", "Le stime non sono finite per questi dati."),
    "range": ("Times and median times outside the representable range: change the unit of Time.",
              "Tempi e tempi mediani fuori dall’intervallo rappresentabile: cambia l’unità del tempo."),
    "shape_mode": ("{field}: choose one of the listed options.", "{field}: scegli una delle opzioni elencate."),
    "shape_number": ("{field} must be a number from {low} to {high}.",
                     "{field} deve essere un numero da {low} a {high}."),
    "level": ("{field} must be a number greater than 0 and less than 100.",
              "{field} deve essere un numero maggiore di 0 e minore di 100."),
    "show_graph": ("{field} must be on or off.", "{field} deve essere attivo o disattivo."),
    "profiles_list": ("{field}: enter a list of profiles.", "{field}: inserisci un elenco di profili."),
    "profiles_many": ("Use at most {limit} profiles; {count} were given.",
                      "Usa al massimo {limit} profili; ne hai dati {count}."),
    "profile_object": ("Profile {number} is not a valid profile.", "Il profilo {number} non è valido."),
    "profile_name": ("Profile {number} needs a name.", "Il profilo {number} richiede un nome."),
    "profile_repeat": ('Profile names must be unique: "{name}" appears twice.',
                       'I nomi dei profili devono essere univoci: "{name}" compare due volte.'),
    "profile_unknown": ('Profile "{name}" sets {predictor}, which is not a predictor of this model.',
                        'Il profilo "{name}" imposta {predictor}, che non è un predittore di questo modello.'),
    "profile_missing": ('Profile "{name}" needs a value for {predictor}.',
                        'Il profilo "{name}" richiede un valore per {predictor}.'),
    "profile_number": ('Profile "{name}": {predictor} needs a finite number.',
                       'Profilo "{name}": {predictor} richiede un numero finito.'),
    "profile_level": ('Profile "{name}": {value} is not a category of {predictor}. Categories: {levels}.',
                      'Profilo "{name}": {value} non è una categoria di {predictor}. Categorie: {levels}.'),
    "graph_profiles": ("{graph} needs at least one profile.", "{graph} richiede almeno un profilo."),
    "times_list": ("{field}: enter a list of times.", "{field}: inserisci un elenco di tempi."),
    "times_value": ("{field}: value {position} ({shown}) must be a finite number of 0 or more.",
                    "{field}: il valore {position} ({shown}) deve essere un numero finito pari ad almeno 0."),
    "times_order": ("{field}: values must be strictly increasing; value {position} ({shown}) does not follow "
                    "{previous}.",
                    "{field}: i valori devono essere strettamente crescenti; il valore {position} ({shown}) non "
                    "segue {previous}."),
    "pairs": ("The curves would have {count} profile-time pairs; the limit is {limit}. Use fewer times or "
              "profiles.",
              "Le curve avrebbero {count} coppie profilo-tempo; il limite è {limit}. Usa meno tempi o profili."),
}

PREFIX = "weibull."
ERROR_PREFIX = PREFIX + "error."
MESSAGES = {key: english for key, (english, _) in ERRORS.items()}

EN, IT = {}, {}
for _key, (_english, _italian) in INTERFACE.items():
    _name = _key if _key.startswith("interface.") else PREFIX + _key
    EN[_name], IT[_name] = _english, _italian
for _key, (_english, _italian) in ERRORS.items():
    EN[ERROR_PREFIX + _key], IT[ERROR_PREFIX + _key] = _english, _italian
