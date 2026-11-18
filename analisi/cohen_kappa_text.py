"""English and Italian text of Cohen's kappa: captions, choices, hints and every validation message.

This is a leaf module (it imports nothing from Trama) so the engine can take its messages from here and ``i18n``
can merge the catalogs without a cycle. The engine raises the English text; ``translate_message`` with the prefix
``kappa.error.`` shows it in the active language. In a template, ``{field}`` and ``{first}`` are canonical names
of dialog fields and ``{weighting}`` is a canonical choice (the dialog converts them to captions); every other
placeholder is a worksheet value or a number that is copied literally. Recipes keep the English field names and
choice values.
"""

# Field captions, tabs, fixed choices and the controls of the order editor: key suffix -> (English, Italian).
INTERFACE = {
    "tab.ratings": ("Ratings", "Valutazioni"),
    "tab.interval": ("Interval and graph", "Intervallo e grafico"),
    "field.first": ("First rating", "Primo valutatore"),
    "field.second": ("Second rating", "Secondo valutatore"),
    "field.weighting": ("Weighting", "Pesi"),
    "field.order": ("Category order", "Ordine delle categorie"),
    "field.interval": ("Confidence interval", "Intervallo di confidenza"),
    "field.level": ("Confidence level (%)", "Livello di confidenza (%)"),
    "field.resamples": ("Resamples", "Repliche"),
    "field.seed": ("Seed", "Seme"),
    "field.show_graph": ("Show graph", "Mostra grafico"),
    "choice.unweighted": ("Unweighted", "Non pesato"),
    "choice.linear": ("Linear", "Lineare"),
    "choice.quadratic": ("Quadratic", "Quadratico"),
    "choice.none": ("None", "Nessuno"),
    "choice.bootstrap": ("Bootstrap percentile", "Bootstrap percentile"),
    "order.up": ("Up", "Su"),
    "order.down": ("Down", "Giù"),
    "order.propose": ("Propose", "Proponi"),
    "order.restore": ("Restore", "Ripristina"),
    "order.clear": ("Clear", "Svuota"),
    "order.automatic": ("Empty: automatic order, Unweighted only.",
                        "Vuoto: ordine automatico, solo con Non pesato."),
    "order.keys": ("Alt+Up and Alt+Down move the selected category. Propose keeps this order, drops the "
                   "categories not in the pairs and adds the new ones. Restore brings back the saved order.",
                   "Alt+Su e Alt+Giù spostano la categoria selezionata. Proponi mantiene quest’ordine, toglie le "
                   "categorie assenti dalle coppie e aggiunge quelle nuove. Ripristina riporta l’ordine salvato."),
    "order.new": ("Not in the order yet: {levels}", "Non ancora nell’ordine: {levels}"),
    "order.stale": ("Not in the complete pairs: {levels}", "Non presenti nelle coppie complete: {levels}"),
    "order.needed": ("Linear and Quadratic weights need an order that lists every category once.",
                     "I pesi Lineare e Quadratico richiedono un ordine che elenchi ogni categoria una sola volta."),
    "order.preview": ("Categories of the complete pairs: {count}", "Categorie delle coppie complete: {count}"),
    "hint.ratings": (
        "Each row is one subject rated twice: the first rating gives the rows of the matrix, the second its "
        "columns. Rows with a missing rating are left out and counted once. Text and numbers are different "
        "categories, so the text 01 and the number 1 stay apart; numbers are labelled 1, 2.5, 1e+20.",
        "Ogni riga è un soggetto valutato due volte: il primo valutatore dà le righe della matrice, il secondo "
        "le colonne. Le righe con una valutazione mancante sono escluse e contate una volta. Testo e numeri sono "
        "categorie diverse, quindi il testo 01 e il numero 1 restano distinti; i numeri si scrivono 1, 2.5, "
        "1e+20."),
    "hint.interval": (
        "The bootstrap resamples whole pairs with the given seed, so the same recipe gives the same interval. "
        "Kappa is undefined in a resample with a single category; at least 90% of the resamples must be valid.",
        "Il bootstrap ricampiona coppie intere con il seme indicato, quindi la stessa ricetta dà lo stesso "
        "intervallo. Il kappa non è definito in una replica con una sola categoria; almeno il 90% delle repliche "
        "deve essere valido."),
    "interface.Cohen's kappa": ("Cohen's kappa", "Concordanza tra valutatori (kappa di Cohen)"),
}

# Validation messages: key -> (English, Italian). No template repeats a placeholder.
ERRORS = {
    "choose": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    "exists": ('Choose an existing column for {field}: "{name}" is not in the worksheet.',
               'Scegli una colonna esistente per {field}: "{name}" non è nel foglio.'),
    "unique": ("Worksheet column names must be unique.", "I nomi delle colonne del foglio devono essere univoci."),
    "same": ("Choose a column different from {first} for {field}.",
             "Scegli per {field} una colonna diversa da {first}."),
    "choice": ("{field}: choose one of the listed options.", "{field}: scegli una delle opzioni elencate."),
    "level": ("{field} must be a number greater than 0 and less than 100.",
              "{field} deve essere un numero maggiore di 0 e minore di 100."),
    "whole": ("{field} must be a whole number from {low} to {high}.",
              "{field} deve essere un numero intero da {low} a {high}."),
    "flag": ("{field} must be on or off.", "{field} deve essere attivo o disattivo."),
    "order_list": ("{field}: enter a list of categories.", "{field}: inserisci un elenco di categorie."),
    "order_item": ("{field}: item {position} must be a category name.",
                   "{field}: la voce {position} deve essere il nome di una categoria."),
    "order_needed": ("{field}: {weighting} weights need an order that lists every category once.",
                     "{field}: con i pesi «{weighting}» serve un ordine che elenchi ogni categoria una sola volta."),
    "order_repeat": ('{field}: "{name}" appears more than once.', '{field}: "{name}" compare più di una volta.'),
    "order_unknown": ('{field}: "{name}" is not a category of the complete pairs.',
                      '{field}: "{name}" non è una categoria delle coppie complete.'),
    "order_missing": ("{field}: list every category once; missing {names}.",
                      "{field}: elenca ogni categoria una sola volta; mancano {names}."),
    "value": ('Source row {row}: the value {value} in column "{column}" is not a finite number.',
              'Riga di origine {row}: il valore {value} nella colonna "{column}" non è un numero finito.'),
    "value_type": ('Source row {row}: the value {value} in column "{column}" must be text or a finite number.',
                   'Riga di origine {row}: il valore {value} nella colonna "{column}" deve essere testo o un '
                   'numero finito.'),
    "collision_number": ('The text "{text}" and a number are different categories with the same label. Use one '
                         'type in both columns or change the text.',
                         'Il testo "{text}" e un numero sono categorie diverse con la stessa etichetta. Usa un solo '
                         'tipo in entrambe le colonne o cambia il testo.'),
    "collision_logical": ('The text "{text}" and a logical value are different categories with the same label. '
                          'Use one type in both columns or change the text.',
                          'Il testo "{text}" e un valore logico sono categorie diverse con la stessa etichetta. '
                          'Usa un solo tipo in entrambe le colonne o cambia il testo.'),
    "pairs_few": ("Cohen's kappa needs at least {minimum} complete pairs; found {count}.",
                  "Il kappa di Cohen richiede almeno {minimum} coppie complete; trovate {count}."),
    "pairs_many": ("Cohen's kappa reads up to {limit} complete pairs; found {count}.",
                   "Il kappa di Cohen legge fino a {limit} coppie complete; trovate {count}."),
    "levels_many": ("Cohen's kappa supports up to {limit} categories; the complete pairs have {count}.",
                    "Il kappa di Cohen ammette al massimo {limit} categorie; le coppie complete ne hanno {count}."),
}

PREFIX = "kappa."
ERROR_PREFIX = PREFIX + "error."
MESSAGES = {key: english for key, (english, _) in ERRORS.items()}

EN, IT = {}, {}
for _key, (_english, _italian) in INTERFACE.items():
    _name = _key if _key.startswith("interface.") else PREFIX + _key
    EN[_name], IT[_name] = _english, _italian
for _key, (_english, _italian) in ERRORS.items():
    EN[ERROR_PREFIX + _key], IT[ERROR_PREFIX + _key] = _english, _italian
