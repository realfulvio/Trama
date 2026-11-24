# Test delle mediane di Mood

Scegli **Confronto tra gruppi → Test delle mediane di Mood** (in inglese: *Group Comparison → Mood median test*). Il metodo confronta la mediana di due o più campioni indipendenti in colonne distinte (`Variables`), costruisce una tabella 2×k rispetto alla mediana complessiva e valuta un χ² di Pearson.

## Dati

| Campo | Predefinito | Significato |
|---|---|---|
| Variabili | | Due o più colonne numeriche distinte. Mancanti ed esclusioni si scartano **dentro** ciascuna colonna. |
| Pareggi | Sotto | Colloca i valori uguali alla mediana complessiva **Sotto**, **Sopra** oppure **Ignora**. |
| Correzione di Yates | disattiva | Attiva e valida **solo** con esattamente due campioni. |

Servono almeno **2** osservazioni finite per campione **prima** del trattamento dei pareggi. Una booleana ferma l’analisi. Stringhe numeriche locali (virgola decimale) sono accettate. Nomi di colonna duplicati e selezioni incomplete restano segnalati sul campo Variabili.

`tests/data/mood_median/mood.csv` è il fixture dell’oracolo: A `1,2,3,3,4`, B `2,3,5,6`, C `3,4,5,7`. Mediana complessiva `3`; conteggi stretti Above/Below/Tied = `[1,2,3]` / `[2,1,0]` / `[2,1,1]`.

## Calcolo

1. Mediana complessiva sul pool di osservazioni valide (non si ricalcola quando cambia la regola dei pareggi).
2. Per ogni campione: conteggi strettamente sopra, strettamente sotto e pari alla mediana.
3. Regola Pareggi: i pari vanno nella riga scelta, oppure sono esclusi dalla tabella del test (`Ignora`). La colonna **Tied** nel foglio Mood counts resta il conteggio osservato **prima** della regola; **Above** e **Below** sono i conteggi finali.
4. χ² di Pearson sulla tabella 2×k, gradi di libertà `k−1`, p-value dalla coda superiore. Con due campioni si può applicare Yates.

Con un margine nullo o un campione svuotato da Ignora si conservano mediana e conteggi; Chi-square, df e P restano vuoti e Settings spiega il motivo. Se una frequenza attesa è inferiore a 5 compare una nota di cautela. Nessun test esatto o post-hoc implicito.

Riferimento: `scipy.stats.median_test`.

## Fogli

I nomi restano in inglese, come le altre ricette.

* **Mood median**: una riga con `Pooled median`, `Chi-square`, `df`, `P`.
* **Mood counts**: una riga per campione, nell’ordine della selezione, con `Sample`, `Above`, `Below`, `Tied`.
* **Settings**: opzioni, scarti per colonna, frequenza attesa minima, note di validità e motivo dell’inferenza assente.

Non c’è un grafico.

## Limiti

* Campioni indipendenti in colonne distinte (non un fattore Gruppo).
* La correzione di Yates con più di due campioni è ignorata.
* Scala di sistema 150% su Windows: **NON PROVATO** se assente dal collaudo della macchina.

Il motore vive in `analisi/mood_median.py` e non modifica i test per ranghi esistenti.
