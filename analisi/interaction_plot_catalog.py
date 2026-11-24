"""Two-factor interaction plot: Italian captions and engine messages.

``analisi.interface_catalog`` merges these two tables at the end of its own. Recipes keep the
canonical English keys and values; sheet titles, column titles and worksheet text stay literal.
"""

CAPTIONS = {
    "Interaction plot": "Grafico d'interazione",
    "X factor": "Fattore X",
    "Series factor": "Fattore delle serie",
    "Error bars": "Barre d'errore",
    "Confidence level": "Livello di confidenza",
}

CHOICE_KEYS = {
    "None": "interaction.choice.none",
    "SD": "interaction.choice.sd",
    "SEM": "interaction.choice.sem",
    "Confidence interval": "interaction.choice.ci",
}

_E = "interaction.error."
MESSAGES = {
    "interaction.choice.none": ("None", "Nessuna"),
    "interaction.choice.sd": ("SD", "DS"),
    "interaction.choice.sem": ("SEM", "SEM"),
    "interaction.choice.ci": ("Confidence interval", "IC della media"),
    "interaction.help.caption": ("Note", "Nota"),
    "interaction.help.text": (
        "Shows observed cell means. Error bars belong to each individual cell "
        "(independent observations, no multiplicity correction).",
        "Mostra le medie osservate per cella. Le barre d'errore appartengono alla singola cella "
        "(osservazioni indipendenti, senza correzione di molteplicità).",
    ),
    _E + "unique": (
        "Worksheet column names must be unique.",
        "I nomi delle colonne del foglio devono essere univoci.",
    ),
    _E + "choose": (
        "Choose a column for {field}.",
        "Scegli una colonna per {field}.",
    ),
    _E + "existing": (
        "Choose an existing column for {field}.",
        "Scegli una colonna esistente per {field}.",
    ),
    _E + "diff_x": (
        "Choose an X factor column different from Response.",
        "Scegli una colonna Fattore X diversa da Risposta.",
    ),
    _E + "diff_series": (
        "Choose a Series factor column different from Response and X factor.",
        "Scegli una colonna Fattore delle serie diversa da Risposta e Fattore X.",
    ),
    _E + "mode": (
        "Choose a valid Error bars mode.",
        "Scegli una modalità valida per Barre d'errore.",
    ),
    _E + "confidence": (
        "Confidence level must be greater than 0 and less than 100.",
        "Livello di confidenza deve essere maggiore di 0 e minore di 100.",
    ),
    _E + "no_valid": (
        "No row has a finite numeric Response with both factors present.",
        "Nessuna riga contiene una Risposta numerica finita con entrambi i fattori presenti.",
    ),
    _E + "x_levels": (
        "X factor requires at least two levels.",
        "Fattore X richiede almeno due livelli.",
    ),
    _E + "series_levels": (
        "Series factor requires at least two levels.",
        "Fattore delle serie richiede almeno due livelli.",
    ),
    _E + "range": (
        "Response values exceed the supported numeric range.",
        "I valori di Risposta superano l’intervallo numerico supportato.",
    ),
}
