# Test t non appaiato da riepiloghi

In **Confronto tra gruppi → Test t non appaiato da riepiloghi**, confronta due
gruppi indipendenti quando disponi di media aritmetica, dispersione e numerosità,
senza dover ricostruire osservazioni individuali.

Puoi usare una riga per gruppo oppure sottocolonne denominate `A [Mean]`,
`A [SD]`, `A [N]` e così via. Sono accettati SD, SEM o CV (%); scegli il tipo
effettivamente presente. Con SEM la conversione è SD = SEM × √N; con CV (%) è
SD = |media| × CV/100. Una media zero non consente di convertire CV in SD.

Servono esattamente due gruppi completi, con N intero ≥ 2 e almeno una SD
positiva. Le righe incomplete o con una cella necessaria esclusa non sono usate;
il foglio **Omitted groups** le identifica con la riga sorgente, numerata da 1.
Il totale N non può superare 2^53. N non determina l'allocazione di osservazioni
artificiali: anche numerosità grandi occupano solo due righe di riepilogo.

**Welch**, predefinito, usa varianze separate e gradi di libertà di
Welch–Satterthwaite. **Student** usa la varianza aggregata e N₁ + N₂ − 2 gradi di
libertà. Il test è bilaterale. La differenza è sempre **prima media meno seconda
media**, nell'ordine dei gruppi completi del foglio o delle sottocolonne
selezionate. Le due etichette e righe sorgente sono riportate nel risultato.

**Differenza ipotizzata**, inizialmente zero, imposta l'ipotesi nulla. Il grafico
e l'intervallo di confidenza stimano la differenza delle medie nella sua scala
originale; non sono intervalli di predizione. Il livello di confidenza cambia
l'intervallo e la soglia di significatività, senza cambiare il valore p.

Per evitare overflow intermedi, il calcolo centra le medie e scala differenze
e SD prima di calcolare SE, t e gradi di libertà. Se un valore finale non è
rappresentabile nelle unità originali resta vuoto con una nota; l'inferenza
scalata resta disponibile. Un SE o una statistica non rappresentabile produce
un errore esplicito, non un valore p sostitutivo.

Salvataggio `.alab`, ricalcolo dopo modifica, uso dei risultati come dati e
export CSV/PNG/SVG/PDF seguono il normale ciclo del progetto. Se un'esclusione
lascia un solo gruppo, il risultato diventa non disponibile; Annulla ripristina
i dati e il calcolo. Non viene presentato un risultato vecchio come attuale.
Il dialogo è in italiano e inglese; ricette, tabelle e figura usano le chiavi e
i testi canonici inglesi.

Questa analisi non copre test appaiati, test unilaterali, test non parametrici,
medie geometriche o inferenza ricostruita da errori senza N. I riepiloghi non
consentono di valutare normalità, dipendenza tra osservazioni o valori anomali.
La scelta del disegno resta una decisione sperimentale.

Le verifiche numeriche confrontano Student e Welch con i test sulle osservazioni
originali e con gli intervalli di SciPy; per Student controllano inoltre
l'identità t² = F dell'ANOVA a due gruppi. Il riferimento pubblico alle formule
e ai parametri è [SciPy: ttest_ind_from_stats](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind_from_stats.html).

