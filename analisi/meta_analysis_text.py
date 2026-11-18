"""English and Italian text of Meta-analysis of effect estimates (captions, choices, notes, messages).

The "meta.error." entries are the exact English messages raised by ``meta_analysis``; ``i18n.translate_message``
matches them and copies the placeholder values literally. Recipes, sheets and columns stay English.
"""

EN = {
    "meta.tab.studies": "Studies", "meta.tab.model": "Model and output",
    "meta.field.study": "Study", "meta.field.estimate": "Estimate", "meta.field.se": "Standard error",
    "meta.field.se_ratio": "SE of ln(ratio)", "meta.field.measure": "Measure", "meta.field.model": "Pooling model",
    "meta.field.interval": "Random interval", "meta.field.level": "Confidence level (%)",
    "meta.field.prediction": "Prediction interval", "meta.field.loo": "Leave one out",
    "meta.field.graph": "Show graph",
    "meta.choice.difference": "Difference", "meta.choice.ratio": "Ratio", "meta.choice.common": "Common effect",
    "meta.choice.random": "Random effects (Paule–Mandel)", "meta.choice.mkh": "Modified Knapp–Hartung",
    "meta.choice.normal": "Normal",
    "meta.note.difference": "One row per independent study. Enter each estimate and its standard error on the same "
                            "scale; the pooled SE is on that scale too. A blank or excluded estimate or SE omits the "
                            "row, and the omitted rows are counted.",
    "meta.note.ratio": "Ratio: enter the ratios themselves (for example 1.25) and, as SE, the standard error of the "
                       "NATURAL LOGARITHM of each ratio, SE of ln(ratio). Pooling, Tau² and the pooled SE are on the "
                       "ln scale; estimates and limits are shown as ratios.",
    "meta.note.model": "Random effects estimate Tau² with Paule–Mandel. Modified Knapp–Hartung multiplies the "
                       "variance by q⋆ = Q(τ²)/(k − 1) only when q⋆ > 1 and uses t with k − 1 df. The prediction "
                       "interval is approximate and needs at least 3 studies. Q p is the p value of Cochran's Q. "
                       "Leave one out repeats the chosen model omitting one study at a time.",
    "meta.error.choice": "{field}: choose one of the listed options.",
    "meta.error.flag": "{field}: choose on or off.",
    "meta.error.level": "Confidence level (%) must be a finite number strictly between 0 and 100.",
    "meta.error.choose": "Choose a column for {field}.",
    "meta.error.exists": 'Choose an existing column for {field}: "{name}" is not in the worksheet.',
    "meta.error.unique": 'Worksheet column names must be unique: "{name}" appears more than once.',
    "meta.error.same": "{field}: choose a column different from {other}.",
    "meta.error.number": "{field}: source row {row} is not a number ({value}).",
    "meta.error.finite": "{field}: source row {row} must be a finite number.",
    "meta.error.ratio": "Estimate: source row {row} must be greater than zero for a ratio ({value}).",
    "meta.error.se": "Standard error: source row {row} must be greater than zero ({value}).",
    "meta.error.few": "Meta-analysis needs at least 2 studies with an estimate and a standard error; {count} found.",
    "meta.error.many": "Meta-analysis combines up to 200 studies; {count} found.",
    "meta.error.se_span": "Standard error: the standard errors span too many orders of magnitude to be combined.",
    "meta.error.spread": "Estimate: the estimates are too far apart relative to their standard errors to be "
                         "combined.",
    "meta.error.bracket": "Pooling model: the Paule–Mandel estimate of tau² could not be bracketed.",
    "meta.error.converge": "Pooling model: the Paule–Mandel estimate of tau² did not converge.",
    "meta.error.tau_small": "Standard error: the values are too small to represent tau² on the analysis scale.",
    "meta.error.tau_large": "Standard error: the values are too large to represent tau² on the analysis scale.",
    "meta.error.range": "Estimate: the pooled result is outside the representable range.",
    "meta.error.study_range": "Standard error: source row {row} gives an interval outside the representable range.",
}

IT = {
    "meta.tab.studies": "Studi", "meta.tab.model": "Modello e risultati",
    "meta.field.study": "Studio", "meta.field.estimate": "Stima", "meta.field.se": "Errore standard",
    "meta.field.se_ratio": "ES di ln(rapporto)", "meta.field.measure": "Misura",
    "meta.field.model": "Modello di sintesi", "meta.field.interval": "Intervallo (effetti casuali)",
    "meta.field.level": "Livello di confidenza (%)", "meta.field.prediction": "Intervallo di predizione",
    "meta.field.loo": "Omissione di uno studio alla volta", "meta.field.graph": "Mostra il grafico",
    "meta.choice.difference": "Differenza", "meta.choice.ratio": "Rapporto", "meta.choice.common": "Effetto comune",
    "meta.choice.random": "Effetti casuali (Paule–Mandel)", "meta.choice.mkh": "Knapp–Hartung modificato",
    "meta.choice.normal": "Normale",
    "meta.note.difference": "Una riga per studio indipendente. Inserisci ogni stima e il suo errore standard sulla "
                            "stessa scala; anche l’ES combinato è su quella scala. Una stima o un ES vuoti o esclusi "
                            "omettono la riga, e le righe omesse vengono contate.",
    "meta.note.ratio": "Rapporto: inserisci i rapporti così come sono (per esempio 1,25) e, come ES, l’errore "
                       "standard del LOGARITMO NATURALE di ciascun rapporto, ES di ln(rapporto). La sintesi, Tau² e "
                       "l’ES combinato sono sulla scala ln; stime e limiti sono mostrati come rapporti.",
    "meta.note.model": "Gli effetti casuali stimano Tau² con Paule–Mandel. Knapp–Hartung modificato moltiplica la "
                       "varianza per q⋆ = Q(τ²)/(k − 1) solo quando q⋆ > 1 e usa t con k − 1 gradi di libertà. "
                       "L’intervallo di predizione è approssimato e richiede almeno 3 studi. Q p è il valore p della "
                       "Q di Cochran. L’omissione ripete il modello scelto togliendo uno studio alla volta.",
    "meta.error.choice": "{field}: scegli una delle opzioni elencate.",
    "meta.error.flag": "{field}: scegli attivo o disattivo.",
    "meta.error.level": "Il livello di confidenza (%) deve essere un numero finito strettamente compreso tra 0 e 100.",
    "meta.error.choose": "Scegli una colonna per {field}.",
    "meta.error.exists": "Scegli una colonna esistente per {field}: «{name}» non è nel foglio dati.",
    "meta.error.unique": "I nomi delle colonne del foglio dati devono essere unici: «{name}» compare più volte.",
    "meta.error.same": "{field}: scegli una colonna diversa da {other}.",
    "meta.error.number": "{field}: la riga di origine {row} non è un numero ({value}).",
    "meta.error.finite": "{field}: la riga di origine {row} deve essere un numero finito.",
    "meta.error.ratio": "Stima: la riga di origine {row} deve essere maggiore di zero per un rapporto ({value}).",
    "meta.error.se": "Errore standard: la riga di origine {row} deve essere maggiore di zero ({value}).",
    "meta.error.few": "La meta-analisi richiede almeno 2 studi con stima ed errore standard; trovati {count}.",
    "meta.error.many": "La meta-analisi combina fino a 200 studi; trovati {count}.",
    "meta.error.se_span": "Errore standard: gli errori standard coprono troppi ordini di grandezza per essere "
                          "combinati.",
    "meta.error.spread": "Stima: le stime sono troppo distanti rispetto ai loro errori standard per essere combinate.",
    "meta.error.bracket": "Modello di sintesi: non è stato possibile delimitare la stima Paule–Mandel di tau².",
    "meta.error.converge": "Modello di sintesi: la stima Paule–Mandel di tau² non è arrivata a convergenza.",
    "meta.error.tau_small": "Errore standard: i valori sono troppo piccoli per rappresentare tau² sulla scala di "
                            "analisi.",
    "meta.error.tau_large": "Errore standard: i valori sono troppo grandi per rappresentare tau² sulla scala di "
                            "analisi.",
    "meta.error.range": "Stima: il risultato combinato è fuori dall’intervallo rappresentabile.",
    "meta.error.study_range": "Errore standard: la riga di origine {row} dà un intervallo fuori dall’intervallo "
                              "rappresentabile.",
}
