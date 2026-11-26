"""Weighted log-rank comparisons: Italian captions and messages.

Recipes keep the English keys. ``analisi.interface_catalog`` merges these tables.
"""

CAPTIONS = {
    "Curve comparison": "Confronto fra curve",
    "Weight detail": "Dettaglio dei pesi",
    "Fleming–Harrington rho": "rho di Fleming–Harrington",
    "Fleming–Harrington gamma": "gamma di Fleming–Harrington",
    "Log-rank": "Log-rank",
    "Tarone–Ware": "Tarone–Ware",
    "Fleming–Harrington early (1, 0)": "Fleming–Harrington precoce (1, 0)",
    "Fleming–Harrington late (0, 1)": "Fleming–Harrington tardivo (0, 1)",
    "Fleming–Harrington intermediate (1, 1)": "Fleming–Harrington intermedio (1, 1)",
    "Fleming–Harrington (custom)": "Fleming–Harrington personalizzato",
    "Weighted log-rank": "Log-rank pesato",
    "Weighted pairwise": "Confronti a coppie pesati",
    "Weighted pairwise FDR": "FDR dei confronti pesati",
    "All groups": "Tutti i gruppi",
    "Survival before": "Sopravvivenza precedente",
    "Group at risk": "A rischio nel gruppo",
    "Observed": "Osservati",
    "Expected": "Attesi",
    "Not available": "Non disponibile",
    "Estimated": "Stimato",
    "At risk": "A rischio",
    "Events": "Eventi",
    "Weight": "Peso",
    "Comparison": "Confronto",
    "First group": "Primo gruppo",
    "Second group": "Secondo gruppo",
    "Status": "Stato",
    "Reason": "Motivo",
    "Method": "Metodo",
    "Metric": "Metrica",
    "Value": "Valore",
    "Adjusted p": "p corretto",
    "Significant": "Significativo",
    "Response variable": "Variabile di risposta",
}

MESSAGES = {
    "weight.help": (
        "The weight changes which deaths the test emphasizes. An early weight, more sensitive to events soon "
        "after the start, and a late weight, more sensitive to later events, answer different questions. "
        "The Kaplan–Meier curves and the numbers at risk do not change. Rho and gamma, when you set them, "
        "must be finite and at least zero: a factor raised to zero is 1, including when the base is 0 or 1, "
        "so (0, 0) is the log-rank test.",
        "Il peso cambia quali decessi il test mette in risalto. Un peso precoce, più sensibile agli eventi "
        "vicini all’inizio, e un peso tardivo, più sensibile agli eventi successivi, rispondono a domande "
        "diverse. Le curve di Kaplan–Meier e i numeri a rischio non cambiano. Rho e gamma, quando li imposti, "
        "devono essere finiti e almeno zero: un fattore elevato a zero vale 1, anche quando la base è 0 o 1, "
        "quindi (0, 0) è il log-rank.",
    ),
    "weight.axis": ("Weight", "Peso"),
    "weight.sheet.global": ("Weighted log-rank", "Log-rank pesato"),
    "weight.sheet.pairs": ("Weighted pairwise", "Confronti a coppie pesati"),
    "weight.sheet.detail": ("Weight detail", "Dettaglio dei pesi"),
    "weight.sheet.fdr": ("Weighted pairwise FDR", "FDR dei confronti pesati"),
    "weight.error.method": ("Choose a curve comparison.", "Scegli un confronto fra curve."),
    "weight.error.exponent": (
        "{field} must be a finite number greater than or equal to zero.",
        "{field} deve essere un numero finito maggiore o uguale a zero.",
    ),
    "weight.error.groups": (
        "A comparison needs at least two groups.",
        "Un confronto richiede almeno due gruppi.",
    ),
    "weight.error.events": (
        "There are no events to compare.",
        "Non ci sono eventi da confrontare.",
    ),
    "weight.error.empty": (
        "A group has no observations for this comparison.",
        "Un gruppo non ha osservazioni per questo confronto.",
    ),
    "weight.error.rank": (
        "The covariance does not have enough rank for this comparison.",
        "La covarianza non ha rango sufficiente per questo confronto.",
    ),
    "weight.error.limit": (
        "Pairwise survival tests support up to twelve groups.",
        "Puoi confrontare fino a dodici gruppi.",
    ),
    "weight.error.cancelled": (
        "The weighted comparison was cancelled.",
        "Il confronto pesato è stato annullato.",
    ),
    "weight.phrase.groups": (
        "A comparison needs at least two groups.",
        "Un confronto richiede almeno due gruppi.",
    ),
    "weight.phrase.events": (
        "There are no events to compare.",
        "Non ci sono eventi da confrontare.",
    ),
    "weight.phrase.empty": (
        "A group has no observations for this comparison.",
        "Un gruppo non ha osservazioni per questo confronto.",
    ),
    "weight.phrase.rank": (
        "The covariance does not have enough rank for this comparison.",
        "La covarianza non ha rango sufficiente per questo confronto.",
    ),
    "weight.phrase.unavailable": ("Not available", "Non disponibile"),
    "weight.phrase.estimated": ("Estimated", "Stimato"),
    "weight.phrase.all": ("All groups", "Tutti i gruppi"),
    "weight.phrase.logrank": ("Log-rank", "Log-rank"),
    "weight.phrase.tarone": ("Tarone–Ware", "Tarone–Ware"),
    "weight.phrase.gehan": ("Gehan–Breslow–Wilcoxon", "Gehan–Breslow–Wilcoxon"),
    "weight.phrase.early": ("Fleming–Harrington early (1, 0)", "Fleming–Harrington precoce (1, 0)"),
    "weight.phrase.late": ("Fleming–Harrington late (0, 1)", "Fleming–Harrington tardivo (0, 1)"),
    "weight.phrase.intermediate": (
        "Fleming–Harrington intermediate (1, 1)",
        "Fleming–Harrington intermedio (1, 1)",
    ),
    "weight.phrase.custom": ("Fleming–Harrington (custom)", "Fleming–Harrington personalizzato"),
    "weight.column.metric": ("Metric", "Metrica"),
    "weight.column.value": ("Value", "Valore"),
    "weight.column.method": ("Method", "Metodo"),
    "weight.column.comparison": ("Comparison", "Confronto"),
    "weight.column.first": ("First group", "Primo gruppo"),
    "weight.column.second": ("Second group", "Secondo gruppo"),
    "weight.column.time": ("Time", "Tempo"),
    "weight.column.risk": ("At risk", "A rischio"),
    "weight.column.events": ("Events", "Eventi"),
    "weight.column.survival": ("Survival before", "Sopravvivenza precedente"),
    "weight.column.weight": ("Weight", "Peso"),
    "weight.column.group": ("Group", "Gruppo"),
    "weight.column.group_risk": ("Group at risk", "A rischio nel gruppo"),
    "weight.column.observed": ("Observed", "Osservati"),
    "weight.column.expected": ("Expected", "Attesi"),
    "weight.column.status": ("Status", "Stato"),
    "weight.column.reason": ("Reason", "Motivo"),
    "weight.column.adjusted": ("Adjusted p", "p corretto"),
    "weight.column.significant": ("Significant", "Significativo"),
    "weight.column.response": ("Response variable", "Variabile di risposta"),
    "weight.column.rho": ("Rho", "rho"),
    "weight.column.gamma": ("Gamma", "gamma"),
}
