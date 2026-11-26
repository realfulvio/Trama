# Weighted log-rank tests · Log-rank pesato

English first, then Italian (*[vai alla versione italiana](#italiano)*).

## English

In **Survival Analysis → Kaplan–Meier survival**, the **Pairwise tests** page has one selector, **Curve comparison**. It adds Tarone–Ware and Fleming–Harrington tests to the Kaplan–Meier analysis that is already there. The Kaplan–Meier curves and the numbers at risk are calculated exactly as before: the weight changes which deaths the test emphasizes, not the estimated survival.

### What the weight means

- **Log-rank** gives every event time the same weight. It is the Fleming–Harrington test with rho = 0 and gamma = 0.
- **Tarone–Ware** weights each time by the square root of the number of subjects still at risk, in the comparison being calculated.
- **Gehan–Breslow–Wilcoxon** weights each time by that number at risk, so early deaths count more. The checkbox of the same name on the Options page is the original sheet and is left as it was.
- **Fleming–Harrington early (1, 0)** multiplies by the pooled survival just before the event, so early deaths count more.
- **Fleming–Harrington late (0, 1)** multiplies by one minus that survival, so later deaths count more. At the first event the survival is still 1, and the weight is 0.
- **Fleming–Harrington intermediate (1, 1)** gives more weight to the middle of follow-up.
- **Fleming–Harrington (custom)** asks for rho and gamma. Both must be finite and at least zero. A factor raised to zero is 1, including when the base is 0 or 1.

The pooled survival used as the weight is the Kaplan–Meier value **immediately before** the event, on the subjects in that comparison. Subjects censored at the same time as a death are still in the risk set. Each pair is calculated again on its own rows, so its risk sets and its weights are not copied from the global test.

### Pairs and the weight detail

**Pairwise scope** chooses all pairs, a control, or a list of pairs. **Pairwise correction** is applied to that one family, separately for each response. The sheet *Weighted log-rank* reports the method, rho and gamma when the weight uses them, chi-square, degrees of freedom and p. *Weighted pairwise* adds the adjusted p when the correction has one. If a group is empty, there are no events, or the covariance does not have enough rank, the sheet says so and does not invent a p value.

**Weight detail** adds a sheet with, at each event time, the events, the subjects at risk, the previous survival, the weight, and the observed and expected counts of every group. The figure gains a step curve of that weight. Its vertical axis and its legend name the method. With more than one response, every sheet and every weight curve names the response.

Recipes saved before this choice keep their previous sheets. The selector is stored only when it is not *None*, and rho and gamma are stored only for the custom weight.

## Italiano

In **Analisi di sopravvivenza → Sopravvivenza di Kaplan–Meier**, la pagina **Confronti a coppie** ha un solo selettore, **Confronto fra curve**. Aggiunge i test di Tarone–Ware e di Fleming–Harrington all’analisi di Kaplan–Meier che c’è già. Le curve di Kaplan–Meier e i numeri a rischio si calcolano come prima: il peso cambia quali decessi il test mette in risalto, non la sopravvivenza stimata.

### Che cosa significa il peso

- **Log-rank** dà lo stesso peso a ogni tempo con eventi. È il test di Fleming–Harrington con rho = 0 e gamma = 0.
- **Tarone–Ware** pesa ogni tempo con la radice quadrata dei soggetti ancora a rischio, nel confronto che si sta calcolando.
- **Gehan–Breslow–Wilcoxon** pesa ogni tempo con quel numero a rischio, quindi i decessi precoci contano di più. La casella con lo stesso nome nella pagina Opzioni è il foglio originale e resta com’era.
- **Fleming–Harrington precoce (1, 0)** moltiplica per la sopravvivenza cumulata subito prima dell’evento, quindi i decessi precoci contano di più.
- **Fleming–Harrington tardivo (0, 1)** moltiplica per uno meno quella sopravvivenza, quindi i decessi tardivi contano di più. Al primo evento la sopravvivenza è ancora 1 e il peso è 0.
- **Fleming–Harrington intermedio (1, 1)** dà più peso alla parte centrale del follow-up.
- **Fleming–Harrington personalizzato** chiede rho e gamma. Entrambi devono essere finiti e almeno zero. Un fattore elevato a zero vale 1, anche quando la base è 0 o 1.

La sopravvivenza usata come peso è il valore di Kaplan–Meier **immediatamente prima** dell’evento, sui soggetti di quel confronto. I soggetti censurati nello stesso tempo di un decesso restano nel gruppo a rischio. Ogni coppia è ricalcolata sulle proprie righe, quindi i suoi gruppi a rischio e i suoi pesi non sono copiati dal test globale.

### Coppie e dettaglio dei pesi

**Coppie da confrontare** sceglie tutte le coppie, un controllo o un elenco. **Correzione per confronti multipli** si applica a quell’unica famiglia, separatamente per ogni risposta. Il foglio *Log-rank pesato* riporta il metodo, rho e gamma quando il peso li usa, il chi-quadro, i gradi di libertà e il p. *Confronti a coppie pesati* aggiunge il p corretto quando la correzione lo prevede. Se un gruppo è vuoto, non ci sono eventi o la covarianza non ha rango sufficiente, il foglio lo dice e non inventa un p.

**Dettaglio dei pesi** aggiunge un foglio con, a ogni tempo con eventi, gli eventi, i soggetti a rischio, la sopravvivenza precedente, il peso e i conteggi osservati e attesi di ogni gruppo. La figura guadagna una curva a gradini di quel peso. L’asse verticale e la legenda nominano il metodo. Con più di una risposta, ogni foglio e ogni curva dei pesi nominano la risposta.

Le ricette salvate prima di questa scelta mantengono i fogli precedenti. Il selettore è memorizzato solo quando non è *Nessuno*, e rho e gamma solo per il peso personalizzato.
