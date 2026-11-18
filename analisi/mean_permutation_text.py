"""English and Italian text of the Permutation test for mean difference (captions, choices, notes, messages).

The "perm.error." entries are the exact English messages raised by ``mean_permutation`` and by the dialog's number
parsing; ``i18n.translate_message`` matches them and copies the placeholder values literally. Recipes, sheets and
columns stay English.
"""

EN = {
    "perm.tab.data": "Data", "perm.tab.test": "Test",
    "perm.field.first": "First", "perm.field.second": "Second", "perm.field.design": "Design",
    "perm.field.alternative": "Alternative", "perm.field.method": "Method", "perm.field.resamples": "Resamples",
    "perm.field.seed": "Seed", "perm.field.keep": "Keep draws", "perm.field.graph": "Show graph",
    "perm.choice.independent": "Independent", "perm.choice.paired": "Paired",
    "perm.choice.two_sided": "Two-sided", "perm.choice.greater": "Greater (First > Second)",
    "perm.choice.less": "Less (First < Second)", "perm.choice.auto": "Auto", "perm.choice.exact": "Exact",
    "perm.choice.monte_carlo": "Monte Carlo",
    "perm.note.independent": "Independent samples: the estimate is mean(First) − mean(Second). Under the null "
                             "hypothesis the values are exchangeable between the two samples (the same "
                             "distribution, not only the same mean), so every split of the pooled values into "
                             "groups of the observed sizes is equally likely. Blank or excluded cells are dropped "
                             "column by column and counted.",
    "perm.note.paired": "Paired samples: only rows with both values are used. Under the null hypothesis the two "
                        "labels are exchangeable within each pair, so every difference First − Second is equally "
                        "likely to be positive or negative (a zero difference counts in both configurations). "
                        "Incomplete or excluded rows are omitted and counted.",
    "perm.note.tails": "Greater counts statistics ≥ the observed one, Less ≤, Two-sided |statistic| ≥ |observed|; "
                       "ties are included. Exact: p = tail count / assignments, the observed one included. Monte "
                       "Carlo: p = (tail count + 1) / (resamples + 1). The test gives no confidence interval.",
    "perm.preview.auto_exact": "With these columns Auto enumerates all {count} assignments exactly: Resamples and "
                               "Seed are not used.",
    "perm.preview.auto_simulate": "With these columns Auto exceeds the exact limits (200,000 assignments, 10 million "
                                  "operations) and simulates: Resamples and Seed are used.",
    "perm.preview.auto": "Auto enumerates exactly up to 200,000 assignments and 10 million operations, and beyond "
                         "that simulates with Resamples and Seed.",
    "perm.preview.exact_count": "Exact enumerates all {count} assignments; Resamples and Seed are ignored.",
    "perm.preview.exact": "Exact enumerates every assignment (up to 200,000); Resamples and Seed are ignored.",
    "perm.preview.monte_carlo": "Monte Carlo draws Resamples assignments with Generator(PCG64(Seed)); the same seed "
                                "with more resamples keeps the earlier draws.",
    "perm.error.choice": "{field}: choose one of the listed options.",
    "perm.error.flag": "{field}: choose on or off.",
    "perm.error.resamples": "Resamples must be a whole number from 199 to 100,000.",
    "perm.error.seed": "Seed must be a whole number from 0 to 18446744073709551615.",
    "perm.error.whole": "{field} must be a whole number.",
    "perm.error.integer_range": "{field} exceeds the supported integer range.",
    "perm.error.choose": "Choose a column for {field}.",
    "perm.error.exists": 'Choose an existing column for {field}: "{name}" is not in the worksheet.',
    "perm.error.unique": 'Worksheet column names must be unique: "{name}" appears more than once.',
    "perm.error.same": "Second: choose a column different from First.",
    "perm.error.number": "{field}: source row {row} is not a number ({value}).",
    "perm.error.finite": "{field}: source row {row} must be a finite number.",
    "perm.error.exact_value": "{field}: source row {row} ({value}) cannot be represented exactly; use values within "
                              "±9007199254740992.",
    "perm.error.pairs_few": "Paired design needs at least 2 complete pairs; {count} found.",
    "perm.error.pairs_many": "Paired design accepts up to 25,000 complete pairs; {count} found.",
    "perm.error.values_few": "{field}: at least 2 values are needed; {count} found.",
    "perm.error.values_many": "Independent design accepts up to 50,000 values in total; {count} found.",
    "perm.error.exact_count": "Method: exact enumeration allows at most 200,000 assignments and these data have "
                              "more. Choose Auto or Monte Carlo.",
    "perm.error.exact_work": "Method: exact enumeration allows at most 10,000,000 operations (assignments × values) "
                             "and these data need {work}. Choose Auto or Monte Carlo.",
    "perm.error.simulation_work": "Resamples: Monte Carlo allows at most 50,000,000 operations (resamples × values) "
                                  "and {resamples} × {units} = {work}. Use {limit} resamples or fewer.",
    "perm.error.magnitude": "{field}: the values are too large in magnitude to be compared reliably.",
}

IT = {
    "perm.tab.data": "Dati", "perm.tab.test": "Test",
    "perm.field.first": "Primo campione", "perm.field.second": "Secondo campione", "perm.field.design": "Disegno",
    "perm.field.alternative": "Alternativa", "perm.field.method": "Metodo", "perm.field.resamples": "Repliche",
    "perm.field.seed": "Seme", "perm.field.keep": "Salva distribuzione nulla", "perm.field.graph": "Mostra grafico",
    "perm.choice.independent": "Indipendenti", "perm.choice.paired": "Appaiati",
    "perm.choice.two_sided": "Bilaterale", "perm.choice.greater": "Maggiore (Primo > Secondo)",
    "perm.choice.less": "Minore (Primo < Secondo)", "perm.choice.auto": "Automatico", "perm.choice.exact": "Esatto",
    "perm.choice.monte_carlo": "Monte Carlo",
    "perm.note.independent": "Campioni indipendenti: la stima è media(Primo) − media(Secondo). Sotto l’ipotesi "
                             "nulla i valori sono scambiabili tra i due campioni (stessa distribuzione, non solo "
                             "stessa media), quindi ogni suddivisione dei valori riuniti in gruppi delle dimensioni "
                             "osservate è ugualmente probabile. Le celle vuote o escluse sono scartate colonna per "
                             "colonna e contate.",
    "perm.note.paired": "Campioni appaiati: si usano solo le righe con entrambi i valori. Sotto l’ipotesi nulla le "
                        "due etichette sono scambiabili all’interno di ogni coppia, quindi ogni differenza Primo − "
                        "Secondo ha la stessa probabilità di essere positiva o negativa (una differenza zero conta "
                        "in entrambe le configurazioni). Le righe incomplete o escluse sono omesse e contate.",
    "perm.note.tails": "Maggiore conta le statistiche ≥ di quella osservata, Minore ≤, Bilaterale |statistica| ≥ "
                       "|osservata|; le parità sono incluse. Esatto: p = conteggio in coda / assegnazioni, inclusa "
                       "quella osservata. Monte Carlo: p = (conteggio in coda + 1) / (repliche + 1). Il test non "
                       "produce un intervallo di confidenza.",
    "perm.preview.auto_exact": "Con queste colonne Automatico enumera esattamente tutte le {count} assegnazioni: "
                               "Repliche e Seme non sono usati.",
    "perm.preview.auto_simulate": "Con queste colonne Automatico supera i limiti dell’esatto (200.000 assegnazioni, "
                                  "10 milioni di operazioni) e simula: Repliche e Seme sono usati.",
    "perm.preview.auto": "Automatico enumera esattamente fino a 200.000 assegnazioni e 10 milioni di operazioni; "
                         "oltre simula con Repliche e Seme.",
    "perm.preview.exact_count": "Esatto enumera tutte le {count} assegnazioni; Repliche e Seme sono ignorati.",
    "perm.preview.exact": "Esatto enumera ogni assegnazione (fino a 200.000); Repliche e Seme sono ignorati.",
    "perm.preview.monte_carlo": "Monte Carlo estrae Repliche assegnazioni con Generator(PCG64(Seme)); lo stesso seme "
                                "con più repliche conserva le estrazioni precedenti.",
    "perm.error.choice": "{field}: scegli una delle opzioni elencate.",
    "perm.error.flag": "{field}: scegli attivo o disattivo.",
    "perm.error.resamples": "Repliche deve essere un numero intero da 199 a 100.000.",
    "perm.error.seed": "Seme deve essere un numero intero da 0 a 18446744073709551615.",
    "perm.error.whole": "{field}: inserisci un numero intero.",
    "perm.error.integer_range": "{field}: il numero supera l’intervallo di interi ammesso.",
    "perm.error.choose": "Scegli una colonna per {field}.",
    "perm.error.exists": 'Scegli una colonna esistente per {field}: "{name}" non è nel foglio.',
    "perm.error.unique": 'I nomi delle colonne del foglio devono essere unici: "{name}" compare più di una volta.',
    "perm.error.same": "Secondo campione: scegli una colonna diversa dal primo campione.",
    "perm.error.number": "{field}: la riga {row} non è un numero ({value}).",
    "perm.error.finite": "{field}: la riga {row} deve contenere un numero finito.",
    "perm.error.exact_value": "{field}: la riga {row} ({value}) non è rappresentabile in modo esatto; usa valori "
                              "entro ±9007199254740992.",
    "perm.error.pairs_few": "Il disegno appaiato richiede almeno 2 coppie complete; trovate {count}.",
    "perm.error.pairs_many": "Il disegno appaiato accetta fino a 25.000 coppie complete; trovate {count}.",
    "perm.error.values_few": "{field}: servono almeno 2 valori; trovati {count}.",
    "perm.error.values_many": "Il disegno indipendente accetta fino a 50.000 valori in totale; trovati {count}.",
    "perm.error.exact_count": "Metodo: l’enumerazione esatta ammette al massimo 200.000 assegnazioni e questi dati "
                              "ne hanno di più. Scegli Automatico o Monte Carlo.",
    "perm.error.exact_work": "Metodo: l’enumerazione esatta ammette al massimo 10.000.000 di operazioni "
                             "(assegnazioni × valori) e questi dati ne richiedono {work}. Scegli Automatico o Monte "
                             "Carlo.",
    "perm.error.simulation_work": "Repliche: Monte Carlo ammette al massimo 50.000.000 di operazioni (repliche × "
                                  "valori) e {resamples} × {units} = {work}. Usa al massimo {limit} repliche.",
    "perm.error.magnitude": "{field}: i valori sono troppo grandi in modulo per essere confrontati in modo "
                            "affidabile.",
}
