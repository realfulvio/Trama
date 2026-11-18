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
