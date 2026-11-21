"""English and Italian text of the Cluster silhouette dialog.

Merged into the interface catalog by ``interface_catalog``. Only application-owned text lives here: the method name,
the fixed distance choices, the note of the Options tab and the field and budget errors of the engine. Column names,
cluster labels and observation labels are never translated.
"""

# English caption -> Italian caption. Captions that already exist elsewhere in the catalog (Variables, Distance,
# Standardize, Graph, Observation labels) are not repeated. Every field and fixed choice needs an entry, even when the
# Italian text is the English one.
CAPTIONS = {
    "Cluster silhouette": "Silhouette dei cluster",
    "Cluster": "Cluster",
    "Euclidean": "Euclidea",
    "Manhattan": "Manhattan",
}

# key -> (English, Italian). The keys under ``silhouette.error.`` are matched against the English messages the engine
# raises; each ``{name}`` copies the value of the message literally.
MESSAGES = {
    "silhouette.note": (
        "The distance and the scale are set here. They do not depend on the analysis that made the partition.",
        "La distanza e la scala si scelgono qui. Non dipendono dall’analisi che ha prodotto la partizione."),
    "silhouette.error.variables_count": (
        "Select between 1 and {count} numeric columns for Variables.",
        "Seleziona da 1 a {count} colonne numeriche per Variabili."),
    "silhouette.error.variables_distinct": (
        "Choose distinct existing columns for Variables.",
        "Scegli colonne esistenti e distinte per Variabili."),
    "silhouette.error.variables_most": (
        "Select at most {count} columns for Variables.",
        "Seleziona al massimo {count} colonne per Variabili."),
    "silhouette.error.unique": (
        "Worksheet column names must be unique.",
        "I nomi delle colonne del foglio devono essere univoci."),
    "silhouette.error.choose": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    "silhouette.error.select": ("Select at least one column for {field}.",
                                "Seleziona almeno una colonna per {field}."),
    "silhouette.error.cluster_variable": (
        'Column "{column}" is already a variable. Choose a different Cluster column.',
        'La colonna "{column}" è già una variabile. Scegli un’altra colonna per Cluster.'),
    "silhouette.error.labels_missing": (
        "Choose an existing column for Observation labels, or none.",
        "Scegli una colonna esistente per le etichette delle osservazioni, oppure nessuna."),
    "silhouette.error.labels_used": (
        'Column "{column}" is already used. Choose a different column for Observation labels.',
        'La colonna "{column}" è già usata. Scegli un’altra colonna per le etichette delle osservazioni.'),
    "silhouette.error.cluster_values": (
        'Column "{column}" must hold cluster labels as text or finite numbers.',
        'La colonna "{column}" deve contenere etichette di cluster come testo o numeri finiti.'),
    "silhouette.error.flag": ("{field} must be on or off.", "{field}: scegli sì o no."),
    "silhouette.error.distance": ("Choose Euclidean or Manhattan.", "Scegli Euclidea o Manhattan."),
    "silhouette.error.rows": (
        "Silhouettes use at most {limit} complete rows; this input has {rows}.",
        "Le silhouette usano al massimo {limit} righe complete; questo ingresso ne ha {rows}."),
    "silhouette.error.scalars": (
        "Rows² × variables is {scalars}, above the limit of {limit}. Select fewer variables or use fewer rows.",
        "Righe² × variabili vale {scalars}, oltre il limite di {limit}. Seleziona meno variabili o usa meno righe."),
    "silhouette.error.few_rows": (
        "Silhouettes need at least 3 complete rows; this input has {rows}.",
        "Le silhouette richiedono almeno 3 righe complete; questo ingresso ne ha {rows}."),
    "silhouette.error.clusters": (
        "Clusters in the partition: {count}. "
        "Silhouettes need between 2 and {last} clusters among {rows} complete rows.",
        "Cluster nella partizione: {count}. "
        "Le silhouette richiedono tra 2 e {last} cluster su {rows} righe complete."),
    "silhouette.error.graph": (
        "The graph shows at most {limit} observations; this input has {rows}. Turn Graph off to keep the tables.",
        "Il grafico mostra al massimo {limit} osservazioni; questo ingresso ne ha {rows}. "
        "Disattiva il grafico per ottenere solo le tabelle."),
    "silhouette.error.unrepresentable": (
        "The distances cannot be represented with these variables.",
        "Con queste variabili le distanze non sono rappresentabili."),
    "silhouette.error.complex": ('Column "{column}" contains complex data.',
                                 'La colonna "{column}" contiene dati complessi.'),
    "silhouette.error.text": ('Column "{column}" contains text or infinite values.',
                              'La colonna "{column}" contiene testo o valori infiniti.'),
    "silhouette.error.precision": (
        'Column "{column}" contains integers outside the supported precision.',
        'La colonna "{column}" contiene interi oltre la precisione supportata.'),
}
