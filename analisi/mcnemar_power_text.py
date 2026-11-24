"""English and Italian text for the paired-proportion power plan.

The engine raises English messages. ``translate_message`` matches them against ``mcnemar.power.error.``.
Recipes keep the English field names and the English goal. ``i18n`` registers ``CAPTIONS``, ``EN`` and ``IT``.
"""

CAPTIONS = {
    "Power for paired proportions": "Potenza per proporzioni appaiate",
    "Alpha (%)": "Alfa (%)",
    "Number of pairs": "Numero di coppie",
    "Negative to positive (%)": "Da negativo a positivo (%)",
    "Positive to negative (%)": "Da positivo a negativo (%)",
}

EN = {
    "command.paired_power": "Paired proportions power…",
    "mcnemar.power.sheet": "Paired proportions power",
    "mcnemar.power.error.percent": "{field} must be a percentage from 0 to 100, including 0 and 100.",
    "mcnemar.power.error.alpha": "{field} must be a percentage strictly between 0 and 100.",
    "mcnemar.power.error.alpha_small": "{field} is too small to represent.",
    "mcnemar.power.error.whole": "{field} must be a whole number from 1 to 5,000.",
    "mcnemar.power.error.target": "{field} must be strictly between 0 and 1.",
    "mcnemar.power.error.finite": "{field} must be finite.",
    "mcnemar.power.error.number": "{field} must be a number.",
    "mcnemar.power.error.graph": "{field} must be on or off.",
    "mcnemar.power.error.sum": "Negative to positive (%) and Positive to negative (%) add up to more than 100.",
    "mcnemar.power.error.goal": "Choose Sample size or Power for Goal.",
    "mcnemar.power.note.design": "The calculation uses the exact two-sided McNemar test, conditional on the "
                                 "discordant pairs. Sample size visits every integer number of pairs, in order, "
                                 "up to 5,000.",
    "mcnemar.power.note.effect": "Expected difference {difference} percentage points. Discordant pairs "
                                 "{discordance}% of the pairs.",
    "mcnemar.power.note.effect_empty": "Enter both transition probabilities as percentages of the pairs.",
    "mcnemar.power.note.curve": "The graph draws every integer N that was calculated and connects those values. "
                                "It does not skip ahead. The target line is drawn only for the sample-size goal.",
}

IT = {
    "command.paired_power": "Potenza per proporzioni appaiate…",
    "mcnemar.power.sheet": "Potenza per proporzioni appaiate",
    "mcnemar.power.error.percent": "{field} deve essere una percentuale da 0 a 100, estremi compresi.",
    "mcnemar.power.error.alpha": "{field} deve essere una percentuale strettamente compresa tra 0 e 100.",
    "mcnemar.power.error.alpha_small": "{field} è troppo piccolo per essere rappresentato.",
    "mcnemar.power.error.whole": "{field} deve essere un numero intero da 1 a 5.000.",
    "mcnemar.power.error.target": "{field} deve essere strettamente compreso tra 0 e 1.",
    "mcnemar.power.error.finite": "{field} deve essere un numero finito.",
    "mcnemar.power.error.number": "{field} deve essere un numero.",
    "mcnemar.power.error.graph": "{field} deve essere attivo oppure disattivo.",
    "mcnemar.power.error.sum": "Da negativo a positivo (%) e Da positivo a negativo (%) sommati superano 100.",
    "mcnemar.power.error.goal": "Per Obiettivo scegli Dimensione del campione oppure Potenza.",
    "mcnemar.power.note.design": "Il calcolo usa il test di McNemar esatto bilaterale, condizionato alle coppie "
                                 "discordanti. La numerosità visita ogni numero intero di coppie, in ordine, "
                                 "fino a 5.000.",
    "mcnemar.power.note.effect": "Differenza attesa {difference} punti percentuali. Coppie discordanti "
                                 "{discordance}% delle coppie.",
    "mcnemar.power.note.effect_empty": "Inserisci entrambe le probabilità di transizione come percentuali delle coppie.",
    "mcnemar.power.note.curve": "Il grafico disegna ogni N intero effettivamente calcolato e congiunge quei valori. "
                                "Non salta in avanti. La linea dell’obiettivo compare solo per la numerosità.",
}
