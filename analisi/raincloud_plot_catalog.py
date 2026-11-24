"""Raincloud plot: Italian captions and engine messages.

``analisi.interface_catalog`` merges these tables at the end of its own. Recipes keep canonical
English keys and values; sheet names, column headings and worksheet labels stay literal.
"""

CAPTIONS = {
    "Raincloud plot": "Grafico raincloud",
    "Show density": "Mostra densità",
    "Show box": "Mostra box",
    "Show points": "Mostra osservazioni",
}

CHOICE_KEYS = {
    "Vertical": "raincloud.choice.vertical",
    "Horizontal": "raincloud.choice.horizontal",
}

_E = "raincloud.error."
MESSAGES = {
    "raincloud.choice.vertical": ("Vertical", "Verticale"),
    "raincloud.choice.horizontal": ("Horizontal", "Orizzontale"),
    "graph.inspector.show_kind.raincloud": ("Show raincloud", "Mostra raincloud"),
    "raincloud.help.caption": ("Note", "Nota"),
    "raincloud.help.text": (
        "Combines half-violin density, compact Tukey box summary (median and range when N < 4) "
        "and individual observations. Non-numeric, non-finite or missing-group rows are discarded.",
        "Combina mezza densità a violino, riepilogo compatto di Tukey (mediana e intervallo se N < 4) "
        "e singole osservazioni. Le righe non numeriche, non finite o con gruppo mancante vengono scartate.",
    ),
    _E + "unique_columns": (
        "Worksheet column names must be unique.",
        "I nomi delle colonne del foglio devono essere univoci.",
    ),
    _E + "choose_response": (
        "Choose an existing column for Response.",
        "Scegli una colonna esistente per Risposta.",
    ),
    _E + "choose_group": (
        "Choose an existing column for Group.",
        "Scegli una colonna esistente per Gruppo.",
    ),
    _E + "distinct_group": (
        "Choose a Group column different from Response.",
        "Scegli una colonna Gruppo diversa da Risposta.",
    ),
    _E + "orientation": (
        "Choose a valid Orientation (Vertical or Horizontal).",
        "Scegli un orientamento valido (Verticale o Orizzontale).",
    ),
    _E + "flag": (
        "{field}: choose on or off.",
        "{field}: scegli attivo o disattivo.",
    ),
    _E + "components": (
        "Enable at least one component (density, box or points).",
        "Attiva almeno un componente (densità, box o osservazioni).",
    ),
    _E + "bandwidth_number": (
        "The bandwidth multiplier must be a number.",
        "Il moltiplicatore della larghezza di banda deve essere un numero.",
    ),
    _E + "bandwidth_positive": (
        "The bandwidth multiplier must be finite and greater than zero.",
        "Il moltiplicatore della larghezza di banda deve essere finito e maggiore di zero.",
    ),
    _E + "bandwidth_range": (
        "The bandwidth or density is outside the supported numeric range.",
        "La larghezza di banda o la densità supera l’intervallo numerico supportato.",
    ),
    _E + "kde_budget": (
        "Too many observations for the density estimate. Turn off Show density or select fewer rows.",
        "Troppe osservazioni per la stima della densità. Disattiva Mostra densità o riduci le righe.",
    ),
    _E + "no_data": (
        "No row has a finite numeric Response (with a present Group, when selected).",
        "Nessuna riga contiene una Risposta numerica finita (con Gruppo presente, se selezionato).",
    ),
    _E + "too_many_groups": (
        "Plot up to {limit} groups at once.",
        "È possibile disegnare al massimo {limit} gruppi alla volta.",
    ),
    _E + "too_many_points": (
        "Select fewer observations (up to {limit}) to draw this graph.",
        "Seleziona meno osservazioni (massimo {limit}) per disegnare questo grafico.",
    ),
    _E + "numeric_range": (
        "The selected Response values exceed the supported numeric range.",
        "I valori selezionati in Risposta superano l’intervallo numerico supportato.",
    ),
}
