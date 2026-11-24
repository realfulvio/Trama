"""Pareto plot: Italian captions and engine messages.

``analisi.interface_catalog`` merges these tables at the end of its own. Recipes keep canonical
English keys and values; sheet names, column headings and worksheet labels stay literal.
"""

CAPTIONS = {
    "Pareto plot": "Grafico di Pareto",
}

_E = "pareto.error."
MESSAGES = {
    "graph.inspector.show_kind.pareto": ("Show bar", "Mostra barra"),
    "graph.inspector.show_kind.pareto-line": ("Show cumulative line", "Mostra linea cumulata"),
    "graph.inspector.show_kind.pareto-threshold": ("Show threshold line", "Mostra linea di soglia"),
    "pareto.help.caption": ("Note", "Nota"),
    "pareto.help.text": (
        "Sorts categories by descending count or weight sum (ties keep first occurrence) and draws "
        "a cumulative percentage curve on the right axis (0–100%). Leave Weight empty to count rows, "
        "and leave Threshold empty to hide the reference line.",
        "Ordina le categorie per frequenza o somma dei pesi decrescente (a pari valore mantiene la "
        "prima occorrenza) e traccia la percentuale cumulata sull’asse destro (0–100%). Lascia Peso "
        "vuoto per contare le occorrenze e Soglia vuota per nascondere la linea di riferimento.",
    ),
    _E + "unique_columns": (
        "Worksheet column names must be unique.",
        "I nomi delle colonne del foglio devono essere univoci.",
    ),
    _E + "choose_category": (
        "Choose an existing column for Category.",
        "Scegli una colonna esistente per Categoria.",
    ),
    _E + "choose_weight": (
        "Choose an existing column for Weight.",
        "Scegli una colonna esistente per Peso.",
    ),
    _E + "distinct_weight": (
        "Choose a Weight column different from Category.",
        "Scegli una colonna Peso diversa da Categoria.",
    ),
    _E + "threshold_number": (
        "Threshold must be a number between 0 and 100, or left blank.",
        "La soglia deve essere un numero compreso tra 0 e 100, oppure lasciata vuota.",
    ),
    _E + "threshold_range": (
        "Threshold must be strictly greater than 0 and less than 100.",
        "La soglia deve essere strettamente maggiore di 0 e minore di 100.",
    ),
    _E + "weight_boolean": (
        "Weight cannot contain boolean values.",
        "La colonna Peso non può contenere valori booleani.",
    ),
    _E + "weight_non_numeric": (
        "Weight must contain numeric values only (missing cells are discarded).",
        "La colonna Peso deve contenere solo valori numerici (le celle mancanti vengono scartate).",
    ),
    _E + "weight_non_finite": (
        "Weight values must be finite numbers.",
        "I valori nella colonna Peso devono essere numeri finiti.",
    ),
    _E + "weight_negative": (
        "Weight values cannot be negative.",
        "I valori nella colonna Peso non possono essere negativi.",
    ),
    _E + "no_categories": (
        "No valid categories were found after ignoring missing or empty entries.",
        "Nessuna categoria valida trovata dopo aver ignorato i valori mancanti o vuoti.",
    ),
    _E + "no_usable_weights": (
        "No row with a valid Category has a present Weight.",
        "Nessuna riga con Categoria valida ha un Peso presente.",
    ),
    _E + "total_positive": (
        "The total across categories must be finite and strictly greater than zero.",
        "Il totale tra le categorie deve essere finito e strettamente maggiore di zero.",
    ),
    _E + "too_many_categories": (
        "Plot up to {limit} distinct categories at once.",
        "È possibile disegnare al massimo {limit} categorie distinte alla volta.",
    ),
}
