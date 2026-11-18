# Grafici e report della PCA

Nella scheda **Grafico**, scegli **Colora gruppi per** per distinguere le categorie nei grafici dei punteggi e nel biplot. La legenda usa il nome della colonna. Una categoria assente ha il proprio gruppo. Il grafico accetta fino a 40 gruppi. Il colore segue le osservazioni che entrano nella PCA e le coordinate della PCA restano identiche. La colonna **Color group** compare nel foglio delle coordinate quando attivi l’opzione.

Nella scheda **Risultati**, seleziona i fogli da aggiungere.

| Foglio | Contenuto |
| --- | --- |
| Transformed data | Righe complete centrate, oppure centrate e divise per la deviazione standard campionaria se è attiva la standardizzazione. |
| Variable contributions | Quadrato della coordinata di ogni variabile nell’autovettore. Per una componente di rango positivo, le quote sommano a 1. |
| Variable–component correlations | Correlazione di Pearson di ciascuna variabile con il punteggio della componente. |
| Observation contributions | Quota di ogni osservazione sulla somma dei quadrati dei punteggi della componente. Le quote sommano a 1 per ogni componente di rango positivo. |
| Variable matrix | Correlazioni tra variabili con standardizzazione attiva, covarianze campionarie altrimenti. |

Se selezioni un criterio per trattenere le componenti, i fogli dei contributi e delle correlazioni mostrano le componenti trattenute. Le celle relative a componenti numericamente nulle sono vuote. Ogni riga di un foglio per osservazione riporta l’indice della riga sorgente. I report utilizzano la PCA già calcolata e le opzioni si salvano nel progetto.

## Contorni per punteggi e biplot

In **Contorni**, scegli il tipo di area da tracciare. Puoi usare tutti i punti del grafico oppure una regione per ciascun gruppo della colonna scelta in **Colora gruppi per**.

- **Regione di confidenza della media** usa la covarianza campionaria e il quantile F di Hotelling per la media bivariata.
- **Ellisse dei dati** usa la covarianza campionaria e un quantile chi quadrato a due gradi di libertà per la copertura sotto un modello normale bivariato.
- **Inviluppo convesso** unisce le osservazioni esterne del gruppo.

I contorni usano le coordinate delle osservazioni effettivamente disegnate, con la scala del biplot quando lo scegli. Il foglio **Confidence overlays** riporta numerosità, centro e stato per gruppo. Gruppi troppo piccoli o collineari conservano i loro punti e una riga con il motivo. Il livello e il raggruppamento restano salvati quando passi a un’altra vista della PCA. I report selezionati rimangono disponibili anche in Scree e Proporzione di varianza.
