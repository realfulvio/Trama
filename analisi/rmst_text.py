"""English and Italian text of Restricted mean survival time: captions, hints and every validation message.

This is a leaf module (it imports nothing from Trama), so the engine takes its messages from here and ``i18n``
merges the catalogs without a cycle. The engine raises the English text; ``translate_message`` with the prefix
``rmst.error.`` shows it in the active language. In a template, ``{field}``, ``{role}`` and ``{first}`` are the
canonical names of dialog fields (the dialog shows their captions), ``{value}`` and ``{limit}`` are numbers
(written with the decimal comma in Italian) and every other placeholder is a worksheet value copied literally.
Recipes keep the English field names.
"""

# Captions, tabs and hints: key suffix -> (English, Italian). "interface.*" keys name the method in menus.
INTERFACE = {
    "tab.data": ("Data", "Dati"),
    "tab.options": ("Codes and estimate", "Codici e stima"),
    "field.time": ("Time", "Tempo"),
    "field.status": ("Status", "Stato"),
    "field.group": ("Group", "Gruppo"),
    "field.reference": ("Reference group", "Gruppo di riferimento"),
    "field.event": ("Event code", "Codice evento"),
    "field.censor": ("Censor code", "Codice censura"),
    "field.horizon": ("Horizon", "Orizzonte"),
    "field.level": ("Confidence level (%)", "Livello di confidenza (%)"),
    "field.show_graph": ("Show graph", "Mostra grafico"),
    "hint.horizon": (
        "The horizon τ is a time in the units of the Time column, measured from the same origin for every "
        "subject. It cannot exceed the longest observed time of any group.",
        "L’orizzonte τ è un tempo nelle unità della colonna Tempo, misurato dalla stessa origine per tutti i "
        "soggetti. Non può superare il tempo osservato più lungo di nessun gruppo."),
    "hint.limit": ("Largest usable horizon: {limit}.", "Orizzonte massimo utilizzabile: {limit}."),
    "hint.estimate": (
        "RMST is the mean event-free time up to τ: the area under the Kaplan–Meier curve from 0 to τ. Two "
        "independent groups are compared as compared − reference and compared / reference. Intervals are "
        "asymptotic Wald intervals and can be fragile with few events.",
        "La RMST è il tempo medio senza evento fino a τ: l’area sotto la curva di Kaplan–Meier da 0 a τ. Due "
        "gruppi indipendenti si confrontano come confronto − riferimento e confronto / riferimento. Gli "
        "intervalli sono di Wald, asintotici, e possono essere fragili con pochi eventi."),
    "hint.codes": (
        "Codes are read as the type of the Status column: whole numbers for a numeric column, exact text "
        "otherwise.",
        "I codici sono letti come il tipo della colonna Stato: numeri interi per una colonna numerica, testo "
        "esatto altrimenti."),
    "interface.Restricted mean survival time": ("Restricted mean survival time", "Sopravvivenza media ristretta"),
}

# Validation messages: key -> (English, Italian).
ERRORS = {
    "choose": ("Choose a column for {role}.", "Scegli una colonna per {role}."),
    "exists": ('Choose an existing column for {role}: "{name}" is not in the worksheet.',
               'Scegli una colonna esistente per {role}: "{name}" non è nel foglio.'),
    "unique": ("Worksheet column names must be unique.", "I nomi delle colonne del foglio devono essere univoci."),
    "different": ("Choose different columns for {first} and {role}.", "Scegli colonne diverse per {first} e {role}."),
    "rows": ("Restricted mean survival time reads up to {limit} complete rows; this worksheet has {count}.",
             "La sopravvivenza media ristretta legge fino a {limit} righe complete; questo foglio ne ha {count}."),
    "no_complete": ("No complete rows: every row misses the time, the status or the group.",
                    "Nessuna riga completa: in ogni riga mancano il tempo, lo stato o il gruppo."),
    "time_type": ('Column "{name}" must be numeric.', 'La colonna "{name}" deve essere numerica.'),
    "time_precision": ('Column "{name}" contains integers outside the supported precision.',
                       'La colonna "{name}" contiene interi oltre la precisione supportata.'),
    "time_value": ("Source row {row}: time {shown} must be a finite number of 0 or more.",
                   "Riga {row} del foglio: il tempo {shown} deve essere un numero finito pari ad almeno 0."),
    "status_type": ('Column "{name}" must hold whole-number codes or text, not booleans or complex numbers.',
                    'La colonna "{name}" deve contenere codici interi o testo, non valori logici o complessi.'),
    "status_value": ('Column "{name}" must hold whole-number codes or text; {shown} is not allowed.',
                     'La colonna "{name}" deve contenere codici interi o testo; {shown} non è ammesso.'),
    "status_mixed": ('Column "{name}" mixes numbers and text. Use one kind of status code.',
                     'La colonna "{name}" mescola numeri e testo. Usa un solo tipo di codice di stato.'),
    "code_type": ('{field}: a code is written as text, such as "1".',
                  '{field}: un codice si scrive come testo, per esempio "1".'),
    "code_empty": ("{field}: enter a code.", "{field}: inserisci un codice."),
    "code_whole": ("{field}: {shown} must be a whole number for a numeric status column.",
                   "{field}: {shown} deve essere un numero intero per una colonna di stato numerica."),
    "code_range": ("{field}: {shown} is outside the 64-bit integer range.",
                   "{field}: {shown} è fuori dall’intervallo degli interi a 64 bit."),
    "same_codes": ("The event code and the censor code are the same status. Use different codes.",
                   "Il codice evento e il codice censura indicano lo stesso stato. Usa codici diversi."),
    "unknown_status": ("Source row {row}: status {shown} is neither the event code nor the censor code.",
                       "Riga {row} del foglio: lo stato {shown} non è né il codice evento né il codice censura."),
    "group_text": ("Group names must stay distinct when written as text.",
                   "I nomi dei gruppi devono restare distinti quando sono scritti come testo."),
    "group_count": ('Column "{name}" has {count} groups among the complete rows. Choose a column with exactly two '
                    "groups, or leave Group empty for one cohort.",
                    'La colonna "{name}" ha {count} gruppi fra le righe complete. Scegli una colonna con '
                    "esattamente due gruppi, oppure lascia Gruppo vuoto per una sola coorte."),
    "reference_empty": ("Choose the reference group: {first_group} or {second_group}.",
                        "Scegli il gruppo di riferimento: {first_group} o {second_group}."),
    "reference_unknown": ('"{name}" is not a group of the complete rows. Choose {first_group} or {second_group}.',
                          '"{name}" non è un gruppo delle righe complete. Scegli {first_group} o {second_group}.'),
    "horizon_empty": ("Enter the horizon: a time greater than 0, in the units of the Time column.",
                      "Inserisci l’orizzonte: un tempo maggiore di 0, nelle unità della colonna Tempo."),
    "horizon_number": ("{field} must be a finite number greater than 0.",
                       "{field} deve essere un numero finito maggiore di 0."),
    "horizon_beyond": ("{field} {value} is beyond the follow-up. Group {name} is observed up to {limit}: use a "
                       "horizon greater than 0 and no larger than that.",
                       "{field} {value} supera il follow-up. Il gruppo {name} è osservato fino a {limit}: usa un "
                       "orizzonte maggiore di 0 e non oltre questo valore."),
    "horizon_beyond_one": ("{field} {value} is beyond the follow-up. The longest observed time is {limit}: use a "
                           "horizon greater than 0 and no larger than that.",
                           "{field} {value} supera il follow-up. Il tempo osservato più lungo è {limit}: usa un "
                           "orizzonte maggiore di 0 e non oltre questo valore."),
    "horizon_none": ("No horizon is usable: every observed time of group {name} is 0.",
                     "Nessun orizzonte è utilizzabile: tutti i tempi osservati del gruppo {name} valgono 0."),
    "horizon_none_one": ("No horizon is usable: every observed time is 0.",
                         "Nessun orizzonte è utilizzabile: tutti i tempi osservati valgono 0."),
    "level": ("{field} must be a number greater than 0 and less than 100.",
              "{field} deve essere un numero maggiore di 0 e minore di 100."),
    "show_graph": ("{field} must be on or off.", "{field} deve essere attivo o disattivo."),
}

PREFIX = "rmst."
ERROR_PREFIX = PREFIX + "error."
MESSAGES = {key: english for key, (english, _) in ERRORS.items()}

EN, IT = {}, {}
for _key, (_english, _italian) in INTERFACE.items():
    _name = _key if _key.startswith("interface.") else PREFIX + _key
    EN[_name], IT[_name] = _english, _italian
for _key, (_english, _italian) in ERRORS.items():
    EN[ERROR_PREFIX + _key], IT[ERROR_PREFIX + _key] = _english, _italian
