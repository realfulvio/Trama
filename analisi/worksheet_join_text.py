"""Join worksheets by key: interface text (English and Italian).

The "join.error." entries are the exact English messages raised by ``worksheet_join`` and by the application
when it resolves the right worksheet; ``i18n.translate_message`` matches them and copies sheet titles, column
names and numbers literally. Recipes, result sheets and columns stay English.
"""

EN = {
    "join.method": "Join worksheets by key",
    "join.field.sheet": "Join right sheet", "join.field.left_keys": "Join left keys",
    "join.field.right_keys": "Join right keys", "join.field.type": "Join type",
    "join.field.cardinality": "Join cardinality",
    "join.choice.inner": "Inner", "join.choice.left": "Left", "join.choice.full": "Full",
    "join.choice.one_one": "One-to-one", "join.choice.one_many": "One-to-many",
    "join.choice.many_one": "Many-to-one", "join.choice.many_many": "Many-to-many",
    "join.caption.left": "Left worksheet", "join.caption.right": "Right worksheet",
    "join.caption.keys": "Key columns", "join.caption.pair": "Pair {number}",
    "join.caption.left_column": "Left column", "join.caption.right_column": "Right column",
    "join.caption.add": "Add key pair", "join.caption.remove": "Remove pair {number}",
    "join.caption.missing_sheet": "{sheet} (missing)", "join.caption.no_sheet": "No other data sheet",
    "join.caption.missing_column": "{column} (missing)",
    "join.note.left": "The data sheet of this analysis: {sheet}.",
    "join.note.keys": ("Each row pairs a left column with a right column. Text must match exactly, spaces "
                       "included; 1 and 1.0 match, \"1\" and 1 do not, true/false only match true/false. A row "
                       "whose key has an empty, excluded or non-finite cell matches nothing: Left and Full keep "
                       "it as unmatched."),
    "join.note.cardinality": ("One-to-many: each left key appears once, a right key may repeat. Many-to-one is the "
                              "opposite, One-to-one needs unique keys on both sides, Many-to-many allows repeats "
                              "everywhere. A repeated key that the choice does not allow is an error, also when it "
                              "has no match."),
    "join.note.type": ("Inner keeps matched rows only. Left keeps every left row. Full also adds the right rows "
                       "without a match, with their key in the left key columns. At most 100,000 rows."),
    "join.note.results": ("Results: Joined data, Join provenance (worksheet rows and state of every output row) "
                          "and Join diagnostics. Editing either worksheet recalculates the join."),
    "join.note.no_sheet": "Add a second data sheet to the project to join it with this one.",
    "join.error.sheet_none": "Choose the right worksheet in Join right sheet.",
    "join.error.sheet_missing": ('The worksheet "{sheet}" is not in this project. Choose a data sheet in Join right '
                                 "sheet to link it again."),
    "join.error.sheet_view": ('The worksheet "{sheet}" is a recovered result view, not a data sheet. Choose a data '
                              "sheet in Join right sheet."),
    "join.error.sheet_same": ('The worksheet "{sheet}" is already on the left. Choose another data sheet in Join '
                              "right sheet."),
    "join.error.pairs": "Choose from 1 to 4 pairs of key columns.",
    "join.error.pair_incomplete": "Each key pair needs a left column and a right column.",
    "join.error.repeated_left": 'Pair {pair}: "{column}" is already a left key.',
    "join.error.repeated_right": 'Pair {pair}: "{column}" is already a right key.',
    "join.error.type": "Join type: choose Inner, Left or Full.",
    "join.error.cardinality": "Join cardinality: choose one of the listed options.",
    "join.error.column_left": 'Pair {pair}: the left worksheet has no column "{column}".',
    "join.error.column_right": 'Pair {pair}: the right worksheet has no column "{column}".',
    "join.error.columns": "The joined sheet would have {count} columns; a sheet holds at most {limit}.",
    "join.error.value_left": ('Pair {pair}: column "{column}" of the left worksheet holds an unsupported value in '
                              "row {row}. Keys accept text, numbers and true/false values."),
    "join.error.value_right": ('Pair {pair}: column "{column}" of the right worksheet holds an unsupported value in '
                               "row {row}. Keys accept text, numbers and true/false values."),
    "join.error.repeat_left": ("The left worksheet repeats a key in rows {first} and {second}. {rule} needs unique "
                               "keys on the left: choose another cardinality or correct the data."),
    "join.error.repeat_right": ("The right worksheet repeats a key in rows {first} and {second}. {rule} needs unique "
                                "keys on the right: choose another cardinality or correct the data."),
    "join.error.budget": ("The join would create {rows} rows ({cells} cells); the limit is {max_rows} rows and "
                          "{max_cells} cells. Choose Inner, add key columns or reduce the repeated keys."),
}

IT = {
    "join.method": "Unisci fogli per chiave",
    "join.field.sheet": "Foglio di destra", "join.field.left_keys": "Chiavi di sinistra",
    "join.field.right_keys": "Chiavi di destra", "join.field.type": "Tipo di unione",
    "join.field.cardinality": "Cardinalità",
    "join.choice.inner": "Interna", "join.choice.left": "Da sinistra", "join.choice.full": "Completa",
    "join.choice.one_one": "Uno a uno", "join.choice.one_many": "Uno a molti",
    "join.choice.many_one": "Molti a uno", "join.choice.many_many": "Molti a molti",
    "join.caption.left": "Foglio di sinistra", "join.caption.right": "Foglio di destra",
    "join.caption.keys": "Colonne chiave", "join.caption.pair": "Coppia {number}",
    "join.caption.left_column": "Colonna di sinistra", "join.caption.right_column": "Colonna di destra",
    "join.caption.add": "Aggiungi coppia", "join.caption.remove": "Rimuovi la coppia {number}",
    "join.caption.missing_sheet": "{sheet} (mancante)", "join.caption.no_sheet": "Nessun altro foglio dati",
    "join.caption.missing_column": "{column} (mancante)",
    "join.note.left": "Il foglio dati di questa analisi: {sheet}.",
    "join.note.keys": ("Ogni riga abbina una colonna di sinistra a una di destra. Il testo deve coincidere "
                       "esattamente, spazi compresi; 1 e 1,0 coincidono, \"1\" e 1 no, vero/falso coincide solo con "
                       "vero/falso. Una riga con una cella della chiave vuota, esclusa o non finita non trova "
                       "corrispondenze: Da sinistra e Completa la tengono come non abbinata."),
    "join.note.cardinality": ("Uno a molti: ogni chiave di sinistra compare una volta sola, a destra può ripetersi. "
                              "Molti a uno è l’opposto, Uno a uno vuole chiavi uniche sui due lati, Molti a molti "
                              "ammette ripetizioni ovunque. Una chiave ripetuta che la scelta non ammette è un "
                              "errore, anche se non trova corrispondenze."),
    "join.note.type": ("Interna tiene solo le righe abbinate. Da sinistra tiene tutte le righe di sinistra. Completa "
                       "aggiunge anche le righe di destra senza corrispondenza, con la loro chiave nelle colonne "
                       "chiave di sinistra. Al massimo 100.000 righe."),
    "join.note.results": ("Risultati: Joined data, Join provenance (righe dei fogli e stato di ogni riga) e Join "
                          "diagnostics. Modificare uno dei due fogli ricalcola l’unione."),
    "join.note.no_sheet": "Aggiungi un secondo foglio dati al progetto per unirlo a questo.",
    "join.error.sheet_none": "Scegli il foglio di destra in Foglio di destra.",
    "join.error.sheet_missing": ('Il foglio "{sheet}" non è in questo progetto. Scegli un foglio dati in Foglio di '
                                 "destra per ricollegarlo."),
    "join.error.sheet_view": ('Il foglio "{sheet}" è una vista di risultati recuperata, non un foglio dati. Scegli '
                              "un foglio dati in Foglio di destra."),
    "join.error.sheet_same": ('Il foglio "{sheet}" è già a sinistra. Scegli un altro foglio dati in Foglio di '
                              "destra."),
    "join.error.pairs": "Scegli da 1 a 4 coppie di colonne chiave.",
    "join.error.pair_incomplete": "Ogni coppia di chiavi vuole una colonna di sinistra e una di destra.",
    "join.error.repeated_left": 'Coppia {pair}: "{column}" è già una chiave di sinistra.',
    "join.error.repeated_right": 'Coppia {pair}: "{column}" è già una chiave di destra.',
    "join.error.type": "Tipo di unione: scegli Interna, Da sinistra o Completa.",
    "join.error.cardinality": "Cardinalità: scegli una delle opzioni elencate.",
    "join.error.column_left": 'Coppia {pair}: il foglio di sinistra non ha la colonna "{column}".',
    "join.error.column_right": 'Coppia {pair}: il foglio di destra non ha la colonna "{column}".',
    "join.error.columns": "Il foglio unito avrebbe {count} colonne; un foglio ne contiene al massimo {limit}.",
    "join.error.value_left": ('Coppia {pair}: la colonna "{column}" del foglio di sinistra contiene un valore non '
                              "supportato alla riga {row}. Le chiavi accettano testo, numeri e valori vero/falso."),
    "join.error.value_right": ('Coppia {pair}: la colonna "{column}" del foglio di destra contiene un valore non '
                               "supportato alla riga {row}. Le chiavi accettano testo, numeri e valori vero/falso."),
    "join.error.repeat_left": ("Il foglio di sinistra ripete una chiave alle righe {first} e {second}. {rule} vuole "
                               "chiavi uniche a sinistra: scegli un’altra cardinalità o correggi i dati."),
    "join.error.repeat_right": ("Il foglio di destra ripete una chiave alle righe {first} e {second}. {rule} vuole "
                                "chiavi uniche a destra: scegli un’altra cardinalità o correggi i dati."),
    "join.error.budget": ("L’unione creerebbe {rows} righe ({cells} celle); il limite è {max_rows} righe e "
                          "{max_cells} celle. Scegli Interna, aggiungi colonne chiave o riduci le chiavi ripetute."),
}
