"""Italian captions and engine messages for two-way ANOVA from cell summaries.

Recipes keep the English keys. Result-sheet headings stay English, as in the other analyses.
"""

CAPTIONS = {
    "Two-way ANOVA from summaries": "ANOVA a due fattori da riepiloghi",
}

_E = "summary.twoway.error."
MESSAGES = {
    _E + "input": (
        "Choose summary subcolumns or groups in rows.",
        "Scegli sottocolonne di riepilogo o gruppi nelle righe.",
    ),
    _E + "dispersion": (
        "Choose SD or SEM.",
        "Scegli SD o SEM.",
    ),
    _E + "infer": (
        "Choose SD or SEM. The selected summaries do not show one dispersion.",
        "Scegli SD o SEM. I riepiloghi selezionati non indicano una sola dispersione.",
    ),
    _E + "unique": (
        "Worksheet column names must be unique.",
        "I nomi delle colonne del foglio devono essere univoci.",
    ),
    _E + "row": (
        "Choose the column with the row factor levels.",
        "Scegli la colonna con i livelli del fattore di riga.",
    ),
    _E + "variables": (
        "Select the Mean, SD or SEM, and N subcolumns for each column group.",
        "Seleziona le sottocolonne Mean, SD o SEM, e N di ogni gruppo di colonna.",
    ),
    _E + "subcolumn": (
        "Select only named Mean, SD, SEM or N subcolumns.",
        "Seleziona solo sottocolonne Mean, SD, SEM o N.",
    ),
    _E + "role": (
        "Each column group must have unique summary roles.",
        "Ogni gruppo di colonna deve avere ruoli di riepilogo univoci.",
    ),
    _E + "triple": (
        "Each column group needs Mean, the chosen dispersion and N.",
        "Ogni gruppo di colonna richiede Mean, la dispersione scelta e N.",
    ),
    _E + "column": (
        "Choose an existing column for {field}.",
        "Scegli una colonna esistente per {field}.",
    ),
    _E + "distinct": (
        "The two factors and the summary columns must be distinct.",
        "I due fattori e le colonne di riepilogo devono essere distinti.",
    ),
    _E + "name": (
        "Enter a factor name of up to 160 characters.",
        "Inserisci un nome di fattore di al massimo 160 caratteri.",
    ),
    _E + "reserved": (
        'Choose a factor name other than "{name}".',
        'Scegli un nome di fattore diverso da "{name}".',
    ),
    _E + "colon": (
        "A factor name cannot contain a colon.",
        "Un nome di fattore non può contenere i due punti.",
    ),
    _E + "same": (
        "Choose different names for the two factors.",
        "Scegli nomi diversi per i due fattori.",
    ),
    _E + "finite": (
        "Summary values must be finite numbers.",
        "I valori di riepilogo devono essere numeri finiti.",
    ),
    _E + "nonnegative": (
        "Dispersion must be nonnegative.",
        "La dispersione non può essere negativa.",
    ),
    _E + "conversion": (
        "The SD conversion is outside the supported numeric range.",
        "La conversione in SD è fuori dall’intervallo numerico supportato.",
    ),
    _E + "size": (
        "Each sample size must be an integer from 2 to 2^53.",
        "Ogni numerosità deve essere un intero da 2 a 2^53.",
    ),
    _E + "partial": (
        "Cell {row_level} × {column_level} is incomplete or excluded ({role}).",
        "La cella {row_level} × {column_level} è incompleta o esclusa ({role}).",
    ),
    _E + "partial_row": (
        "Row {source_row} is incomplete or excluded ({role}).",
        "La riga {source_row} è incompleta o esclusa ({role}).",
    ),
    _E + "blank": (
        "Each included row needs a nonempty level name.",
        "Ogni riga inclusa richiede un nome di livello non vuoto.",
    ),
    _E + "duplicate": (
        "The combination {row_level} × {column_level} appears more than once.",
        "La combinazione {row_level} × {column_level} compare più di una volta.",
    ),
    _E + "missing": (
        "The combination {row_level} × {column_level} is missing.",
        "Manca la combinazione {row_level} × {column_level}.",
    ),
    _E + "levels": (
        "{factor} needs at least two levels.",
        "{factor} richiede almeno due livelli.",
    ),
    _E + "variance": (
        "The pooled residual variance is zero.",
        "La varianza residua aggregata è zero.",
    ),
    _E + "repeated": (
        "Repeated measures cannot be estimated from cell summaries.",
        "Le misure ripetute non si possono stimare da riepiloghi di cella.",
    ),
    _E + "diagnostics": (
        "Residual diagnostics need the observations. Cell summaries do not keep them.",
        "Le diagnostiche sui residui richiedono le osservazioni. I riepiloghi di cella non le conservano.",
    ),
    _E + "type3": (
        "This analysis reports Type III sums of squares only.",
        "Questa analisi riporta solo le somme dei quadrati di tipo III.",
    ),
    _E + "interaction": (
        "The model is the full crossing with interaction.",
        "Il modello è l’incrocio completo con interazione.",
    ),
    _E + "comparisons": (
        "Comparisons that need the observations are not available from cell summaries.",
        "I confronti che richiedono le osservazioni non sono disponibili dai riepiloghi di cella.",
    ),
    _E + "numeric": (
        "The sums of squares could not be computed reliably for this grid.",
        "Le somme dei quadrati non si possono calcolare in modo affidabile per questa griglia.",
    ),
    _E + "total": (
        "The total sample size must not exceed 2^53.",
        "La numerosità totale non deve superare 2^53.",
    ),
    _E + "grid": (
        "Provide a complete grid with at least two levels of each factor.",
        "Fornisci una griglia completa con almeno due livelli per ciascun fattore.",
    ),
    _E + "large": (
        "This grid has too many cells for the summary ANOVA.",
        "Questa griglia ha troppe celle per l’ANOVA da riepiloghi.",
    ),
}
