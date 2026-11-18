# Test binomiale esatto a due categorie

`Compare observed distribution with expected` (Data Exploration and Summary) ha ora l'opzione `Test method`, nella pagina Options:

- `Pearson chi-square` è il valore predefinito e il metodo di sempre: le tabelle `Test` e `Categories`, i residui, i contributi, i nomi e le opzioni non cambiano. Una ricetta salvata prima della 0.93 non ha la chiave e si apre come Pearson.
- `Exact binomial` confronta la prima riga osservata, il successo, con la proporzione attesa della prima riga. Produce solo tabelle, nessun grafico.

## Dati

Il test esatto vuole esattamente due righe osservate. Le righe con conto vuoto si saltano, come nel metodo di Pearson, quindi due righe riempite con una vuota in mezzo vanno bene. I conti sono interi da 0 in su, anche quando tutto sta in una sola categoria. Il totale va da 1 a 10.000.000. Le etichette sono quelle del foglio, nello stesso ordine, e non vengono interpretate.

`Expected distribution` ha i tre modi già noti:

- `Equal proportions`: `p0 = 1/2`.
- `Weights in a column`: un peso positivo per riga, `p0 = peso della prima riga / somma dei pesi`.
- `Expected counts in a column`: come i pesi, con la somma dei conti attesi uguale al totale osservato.

`p0` deve poter stare strettamente fra 0 e 1. Con pesi come `1e-300` e `1e300` il campo `Expected values` segnala l'errore. Il caso 2/8 con conti attesi 20/80 e `n = 100` dà lo stesso `p0 = 0,2`.

## Cosa riporta

Se `X ~ Bin(n, p0)` e `k` è il conto della prima riga:

- `p lower` è `P(X ≤ k)` e `p upper` è `P(X ≥ k)`, entrambi inclusivi. La coda superiore viene dalla funzione di sopravvivenza di SciPy, non da `1 - cdf`, quindi resta precisa anche quando vale 1e-60.
- `p` è il valore bilaterale ordinato per massa: somma `P(X = j)` su tutti gli interi `j` con `P(X = j) ≤ P(X = k)`. Le parità numeriche contano come parità, con una tolleranza relativa di 1e-7 sulla massa di `k`, la stessa di `scipy.stats.binomtest`. Non è il doppio della coda più piccola.
- `CI lower` e `CI upper` sono l'intervallo esatto di Clopper–Pearson a code uguali per `k/n`, al livello `Confidence level (%)` (95 se non cambiato). Agli estremi i limiti sono esattamente 0 e 1.

Il test bilaterale ordinato per massa e l'intervallo a code uguali non sono la stessa costruzione e possono portare a decisioni diverse sullo stesso `p0`. Cambiare il livello cambia solo l'intervallo: i `p` restano identici. Non ci sono correzione di continuità, stima di `p0` né variante mid-p.

Il calcolo non alloca array proporzionali al totale. Il confine delle due code si cerca per bisezione attorno alla moda, poi si sommano `cdf` e `sf`. Con 10 milioni di osservazioni serve qualche millisecondo.

`Test` è una tabella con indice e colonna `Value`, con le righe `Total count`, `Null proportion`, `Observed proportion`, `p lower`, `p upper`, `p`, `CI lower`, `CI upper`, `Confidence level (%)` e `Method` (`Exact binomial`). `Categories` ha `Category`, `Observed` e `Expected`. Gli export (CSV, `.alab`) usano i numeri grezzi, senza arrotondare; la griglia ne mostra dieci cifre.

## Il dialogo

Con `Exact binomial` il campo `Estimated parameters` si nasconde e compare `Confidence level (%)`. Il test esatto non stima parametri, quindi se si passa a `Exact binomial` con un numero di parametri stimati diverso da 0, il numero torna a 0 e una nota sotto i campi lo dice. La ricetta del test esatto non contiene `Estimated parameters`; una ricetta scritta a mano con un valore diverso da 0 viene rifiutata con un errore su quel campo. Con tre o più righe riempite l'errore è su `Observed counts` e il dialogo resta aperto, come per il livello fuori da 0–100.

Caption, scelte, note ed errori del dialogo sono in italiano e in inglese. Nella ricetta restano i valori canonici inglesi (`Test method`: `Exact binomial`).

## Esempio sintetico

7 successi su 100 con `p0 = 0,2` (pesi 2 e 8): `p lower` = 0,000276987, `p upper` = 0,999922, `p` = 0,000613074 e intervallo al 95% [0,0286053; 0,138920]. La seconda coda del bilaterale parte da 35: `P(X ≤ 7) + P(X ≥ 35) = 0,000276987 + 0,000336087`. I valori congelati sono in `tests/data/exact_binomial/expected.json`, sommati a parte con masse razionali; i dati sono sintetici.

## Verifiche

```sh
python tests/verify.py --repo <checkout>        # verificatore del pacchetto, fuori dal repository
python -m unittest tests.test_exact_binomial     # oracolo con Fraction, validazioni, 10 milioni di osservazioni
TRAMASTAT_SMOKE_ONLY=binomial-goodness python tramastat.py --smoke <cartella>
```

Lo smoke `binomial-goodness` usa la finestra vera: Analyze, un Pearson salvato che resta identico, tre righe che tengono aperto il dialogo, il reset dei parametri stimati, CSV con numeri grezzi, `Use Result as Data` sulla tabella `Categories`, salvataggio e riapertura, modifica ed esclusione di una cella con ricalcolo, cambio di livello, nelle due lingue. Fa parte anche dello smoke completo.
