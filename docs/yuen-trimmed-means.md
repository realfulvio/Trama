# Test di Yuen per medie troncate

Scegli **Confronto tra gruppi → Test di Yuen per medie troncate** (in inglese: *Group Comparison → Yuen's test for trimmed means*). Il test confronta le medie troncate di due campioni indipendenti e riporta la differenza, l’errore standard, i gradi di libertà, la statistica t, il p bilaterale e l’intervallo di confidenza simmetrico.

La differenza è sempre **prima media troncata − seconda media troncata**. Il verso resta quello scelto nel dialogo: due colonne, l’ordine dei due gruppi, oppure la casella che inverte i campioni.

## Dati

| Campo | Predefinito | Significato |
|---|---|---|
| Formato dei campioni | Due colonne di misura | Anche **Una misura e una colonna di gruppo**, se il foglio ha esattamente due etichette non vuote. |
| Prima misura / Seconda misura | | Colonne numeriche. I mancanti si scartano dentro ciascuna colonna. |
| Risposta / Gruppo | | Nel formato raggruppato. L’ordine di comparsa dei gruppi è A poi B e viene conservato nel progetto. |
| Troncamento per coda (%) | 20 | Da 0 incluso a 50 escluso. |
| Livello di confidenza (%) | 95 | Strettamente tra 0 e 100. |
| Inverti primo e secondo campione | Spento | Scambia A e B senza cambiare le colonne. |

Nel dialogo italiano si può scrivere `20,5`. Nella ricetta il numero resta `20.5`.

Un testo, un infinito o un intero oltre ±9.007.199.254.740.992 ferma l’analisi sulla colonna e sulla riga di origine. Con meno di 2 osservazioni finite il campo da correggere è il campione. Se il troncamento ne lascia meno di 2, il campo da correggere è il troncamento: il controllo non divide per zero. Le scelte già fatte restano nel dialogo.

`tests/data/yuen/columns.csv` è la coppia con un valore estremo: Controllo `1, 2, 3, 4, 100` e Trattato `2, 4, 5, 6, 8, 201`. Al 20% si toglie un’osservazione per coda e la differenza delle medie centrali è −2,75.

## Calcolo

In un campione di n osservazioni finite si toglie da ogni coda

`g = floor(n × percentuale / 100)`

con il pavimento calcolato sulla percentuale dichiarata, non sul prodotto binario `n × frazione`. Con n = 100 e 29% il prodotto binario vale circa 28,999999999999996 e `floor` darebbe 28; il test toglie 29. La dimensione effettiva è `h = n − 2g`. Il foglio riporta N prima del filtro, N dopo il filtro, g e h.

La media usa gli h valori centrali. Per la varianza, le due code della serie ordinata sono sostituite dagli estremi conservati (winsor). Se `sW²` è la varianza winsorizzata con divisore `h − 1`, la componente della media è

`d = (n − 1) sW² / (h (h − 1))`

cioè la somma dei quadrati winsorizzati divisa per `h (h − 1)`. Quando i valori sono enormi rispetto alla loro dispersione, gli scarti sono calcolati dopo una traslazione e un riscalamento, così la somma dei quadrati non si cancella. Se il risultato non è finito, l’errore nomina il campione.

`SE = √(dA + dB)`, `t = (mediaA − mediaB) / SE` e i gradi di libertà sono quelli di Welch–Satterthwaite sulle due componenti. Il p e l’intervallo usano la t di Student con quei gradi di libertà, sempre bilaterale. A troncamento 0 il risultato coincide con il t di Welch nello stesso verso.

Un solo campione costante è ammesso: l’altro tiene l’errore standard positivo. Se entrambe le componenti sono zero, i fogli tengono le medie e la differenza, l’errore standard è 0 e inferenza, t, gradi di libertà, p e limiti restano vuoti. Il motivo è: *Inference is not available because the standard error is zero.*

## Fogli

I nomi restano in inglese, come le altre ricette.

* **Yuen groups**: gruppo, ruolo (First / Second), N prima e dopo il filtro, osservazioni tolte per coda, N effettivo, media troncata, componente di varianza.
* **Yuen effect**: differenza, SE, df, t, p, limiti, livello di confidenza e se l’inferenza è disponibile.

Non c’è un grafico.

## Limiti

* Solo due campioni indipendenti e solo il test bilaterale.
* SciPy `ttest_ind(..., trim=)` usa `int(n × trim)`. Sui quattro casi di controllo i due concordano. Sulle percentuali il cui prodotto cade su un intero, per esempio 29% di 100, SciPy toglie un’osservazione in meno: il risultato di Trama segue la percentuale digitata.
* Il confronto con 50.000 osservazioni per gruppo, troncamento 20%, usa 30.000 osservazioni effettive per campione. Sul notebook di collaudo il solo calcolo è durato circa 0,10 s (`tests.test_yuen`, N effettivo 30.000+30.000). Non vale il tetto di 50.000 valori complessivi del test di permutazione.
* Scala di sistema 150% su Windows: NON PROVATO. Il mini PC che ospita la VM non rispondeva sulla porta 22 durante il collaudo, quindi DPI, renderer e interazione a 150% non sono stati misurati.

Riferimenti: Yuen, *The two-sample trimmed t for unequal population variances*, Biometrika 61 (1974); `scipy.stats.ttest_ind`.
