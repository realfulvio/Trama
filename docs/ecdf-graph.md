# Distribuzione cumulativa empirica (ECDF)

Il comando **Distribuzione cumulativa empirica** (`Empirical cumulative distribution`), disponibile nella categoria **Grafici** (`Graphing`), consente di calcolare, confrontare e salvare funzioni di distribuzione cumulativa empirica (ECDF) a gradini per da 1 a 12 serie.

## Definizione statistica

Per un campione non vuoto di $N$ osservazioni finite $x_1, \dots, x_N$, la funzione di distribuzione cumulativa empirica in un punto $x \in \mathbb{R}$ è:

$$\hat{F}(x) = \frac{1}{N} \sum_{i=1}^{N} \mathbf{1}(x_i \le x)$$

- **Ordinamento e pareggi**: i valori distinti di $X$ vengono ordinati in senso strettamente crescente; eventuali osservazioni uguali (inclusi `0.0` e `-0.0`) vengono aggregate in un unico salto di ampiezza $\text{Count} / N$.
- **Continuità a destra**: ciascun tratto orizzontale si estende a destra del relativo salto (`steps-post`), con pendenza nulla tra salti consecutivi.
- **Livelli ai bordi visibili**: il grafico mostra il livello iniziale $0$ a sinistra del minimo osservato e il livello finale $1$ (o $100\%$) a destra del massimo osservato, senza introdurre righe fittizie nella tabella `ECDF points`.
- **Serie costante**: una serie con un unico valore distinto $c$ viene rappresentata da un solo salto da $0$ a $1$ in $x = c$ (con una sola riga in `ECDF points`).

## Modalità di ingresso e gestione dei dati

Il metodo riusa la selezione dei grafici di distribuzione e mantiene nel progetto `.alab` le chiavi canoniche in inglese:

1. **Risposta singola** (`Single response`):
   - **Risposta** (`Response`): colonna numerica di $X$.
   - **Gruppo** (`Group`, opzionale): colonna di raggruppamento. Se lasciata vuota viene tracciata una sola curva (`All`).
   - Vengono normalizzate insieme solo la colonna $X$ e la colonna di gruppo della stessa riga; le altre colonne del foglio non vengono considerate.
   - Le etichette di gruppo mantengono identità tipizzata (es. l'intero `1` e il testo `"1"` restano distinti) e rispettano l'eventuale ordine categorie del foglio, altrimenti l'ordine di prima apparizione.
2. **Colonne separate** (`Separate columns`):
   - **Variabili** (`Variables`): da 1 a 12 colonne numeriche distinte.
   - L'ordine di selezione spuntato dall'utente viene preservato sia nel calcolo sia alla riapertura della ricetta.
   - Ogni colonna gestisce in modo indipendente celle mancanti ed esclusioni del foglio.

### Dati mancanti, esclusioni ed errori

- Le celle mancanti (`NaN`/vuote) e le celle escluse dal foglio sono escluse dal calcolo e conteggiate per ciascuna serie nella colonna `Excluded` di `ECDF summary`.
- Valori testuali, complessi o non finiti (`±inf`) in una colonna selezionata producono un errore esplicito sul campo interessato, coerentemente con i grafici adiacenti.
- Una colonna selezionata o un gruppo presente senza alcuna osservazione numerica valida produce un errore esplicito sul campo (`Variables`, `Group` o `Response`).
- Il limite massimo è di **12 curve** contemporanee.

## Risultati ed esportazioni

Il metodo genera tre fogli di risultato e una figura nativa:

- **`ECDF points`**: tabella lunga con colonne `Group`, `X`, `Count`, `Cumulative count`, `Probability`. La colonna `Probability` resta sempre nell'intervallo $[0, 1]$ anche quando il grafico è visualizzato in percentuale, così i CSV esportati risultano identici nelle due modalità.
- **`ECDF summary`**: riepilogo per serie con `Group`, `N` (valido), `Excluded` (righe escluse), `Distinct values`, `Minimum`, `Maximum` e `Note`.
- **`Settings`**: parametri della ricetta, numero di curve, conteggio complessivo di osservazioni valide ed escluse (e righe omesse per gruppo mancante, se presenti) e convenzione a gradini.

## Grafico, unità dell'asse Y e personalizzazione

- **Asse Y** (`Y axis`): scelta tra **Proporzione** (`Proportion`, scala $0\text{–}1$) e **Percentuale** (`Percent`, scala $0\%\text{–}100\%$). Il cambio di unità aggiorna la sola presentazione del grafico senza modificare i valori numerici esportati in `ECDF points`.
- **Strumenti grafici**: la figura supporta tema chiaro e scuro dell'interfaccia Qt, legenda con chiavi stabili, **Formato grafico**, **Ispettore grafico**, stili predefiniti, annotazioni, forme, assi secondari collegati ed esportazione in **PNG**, **SVG** e **PDF** vettoriali.
- **Ricalcolo e persistenza**: il progetto `.alab` salva la ricetta canonica e lo stile del grafico; modificando una cella del foglio e ricalcolando, punti, riepilogo e figura si aggiornano coerentemente.

## Contratto programmatico

In `analisi/ecdf_graph.py` la funzione pubblica `ecdf_points(values)` accetta un vettore 1D non vuoto di numeri finiti e restituisce un `pandas.DataFrame` con le quattro colonne canoniche `["X", "Count", "Cumulative count", "Probability"]`.
