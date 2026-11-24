# Grafico di Pareto (`Pareto plot`)

Il metodo canonico `Pareto plot` (famiglia **Graphing** e **Nuovo grafico**) ordina le categorie per frequenza o somma dei pesi decrescente e sovrappone la curva della percentuale cumulata su un asse Y secondario indipendente da 0% a 100%.

## Opzioni

- **Category** *(obbligatoria)*: colonna categoriale. Etichette letterali (`parse_math=False`) con identità tipizzate stabili (`int`, `float`, `str`, `bool` restano distinti). Categorie mancanti o vuote vengono ignorate e contate.
- **Weight** *(facoltativa)*: se omessa o vuota conta le occorrenze; se selezionata (distinta da `Category`) somma i pesi per categoria. Pesi mancanti vengono scartati e conteggiati; valori presenti negativi, booleani, non numerici o non finiti generano errore su `Weight`. Lo zero è ammesso purché ci sia almeno una categoria e totale positivo e finito.
- **Threshold** *(facoltativa, default `80`)*: percentuale strettamente compresa tra 0 e 100. Vuota disattiva la linea di riferimento. Quando attiva, evidenzia la prima categoria che raggiunge o supera la soglia e la riporta nel foglio `Settings`.

## Risultati e stile

- **`Pareto categories`**: colonne `Category`, `Amount`, `Percent`, `Cumulative percent` (valore finale esatto `100`). A pari valore viene conservato l’ordine di prima occorrenza senza modificare il foglio dati.
- **`Settings`**: modalità, colonne, numero di categorie, totale, soglia, categoria di soglia e conteggio delle righe usate e scartate. Per pesi di scala estrema, l’asse sinistro indica il fattore in potenza di dieci. La tabella conserva i pesi originali.
- **Stile e Ispettore**: ogni categoria è identificata da `pareto:cat:<token>` (più `pareto:line:cumulative` e `pareto:line:threshold`), così colori e visibilità seguono la categoria dopo ricalcolo e riapertura `.alab`. La sincronizzazione lineare degli assi secondari (`linked_axes`) non è attivata.

## Collaudo

- Unit e regressione: `python -m unittest tests.test_pareto_plot tests.test_qt_pareto_plot tests.test_catalog`
- Smoke Classica Qt: `python -m trama_qt --smoke <cartella> --only qt-pareto-plot`
