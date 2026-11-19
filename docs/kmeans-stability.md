# Stabilità K-means

**Stabilità K-means** (in inglese *K-means stability*) misura quanto si ripetono le partizioni K-means quando si tolgono righe a caso o si cambia il seme. La trovi in **Analizza → Raggruppamento**, dopo la selezione del modello k-means. Per ogni k dell'intervallo scelto puoi vedere i gruppi fragili e le osservazioni che cambiano assegnazione. L'analisi non sceglie il numero di gruppi. Raggruppamento k-means, Selezione del modello k-means e silhouette restano analisi separate e non cambiano.

## Opzioni

| Campo | Predefinito | Valori ammessi |
| --- | --- | --- |
| **Variabili** | colonne scelte | da 1 a 32 colonne numeriche diverse |
| **k minimo** | 2 | intero da 2 a 12 |
| **k massimo** | 4 | intero da k minimo a 12 |
| **Standardizza** | sì | sì o no |
| **Algoritmo k-means** | Lloyd | Lloyd o Hartigan–Wong, come nel raggruppamento k-means |
| **Limite di iterazioni Hartigan–Wong** | 10 | da 1 a 1000; il campo compare solo con Hartigan–Wong |
| **Seme casuale** | 42 | intero da 0 a 4294967295 |
| **Ricampionamenti** | 100 | intero da 5 a 2000 |
| **Frazione campionata (%)** | 80 | numero da 50 a 95; nel dialogo puoi scrivere la virgola decimale |
| **Ripetizioni con altri semi** | 0 | intero da 0 a 100 |
| **k dei report per osservazione** | 2 | intero fra k minimo e k massimo |
| **Mostra la matrice di co-assegnazione** | no | richiede al massimo 200 righe complete |

Il progetto salva le opzioni con i nomi e i valori inglesi, quindi una ricetta si riapre uguale in qualunque lingua. Con Lloyd il limite di iterazioni non viene salvato.

## Come funziona

Per ogni k Trama calcola un **riferimento** su tutte le righe complete con il motore K-means già usato dal raggruppamento. Poi estrae i ricampionamenti senza reinserimento. Ogni campione contiene floor(n × frazione / 100) righe e per un dato seme è lo stesso per ogni k. Su ogni campione il K-means viene ricalcolato, con media e deviazione standard del solo campione se la standardizzazione è attiva. Tutte le righe complete vengono poi assegnate al centro più vicino. Un pareggio esatto va al gruppo con il numero più basso. La partizione ottenuta si confronta con il riferimento:

- l'**ARI** (indice di Rand corretto di Hubert e Arabie) misura l'accordo fra le due partizioni intere, senza dipendere dai nomi dei gruppi;
- l'**OOB ARI** ripete il confronto sulle sole righe rimaste fuori dal campione;
- i gruppi del campione vengono abbinati uno a uno a quelli del riferimento con la massima sovrapposizione totale. Su questo abbinamento si calcolano il **Jaccard** di ogni gruppo e l'**accordo** di ogni riga.

Le **Ripetizioni con altri semi** ricalcolano il K-means su tutte le righe con semi diversi e confrontano ogni soluzione con il riferimento. Misurano la sensibilità all'inizializzazione.

Le righe con un valore mancante o infinito in una variabile scelta vengono escluse e contate nel riepilogo. Le righe escluse dal foglio non entrano nell'analisi. **Worksheet row** è la posizione della riga nel foglio, contando da 1, come la vede l'analisi.

## Risultati

I fogli dei risultati hanno nomi inglesi fissi, come nelle altre analisi:

- **Stability summary**: una riga per k con N, dimensione del campione, ricampionamenti validi, mediana dell'ARI con 10° e 90° percentile, mediana dell'OOB ARI, WSS del riferimento e stato. Con le ripetizioni attive aggiunge il loro numero e la mediana dell'ARI.
- **Resample scores**: l'ARI e l'OOB ARI di ogni ricampionamento, con il motivo quando non è valido. Un campione non è valido se una variabile vi risulta costante, se il fit non riesce o se un gruppo proiettato resta vuoto.
- **Cluster stability**: per ogni gruppo del riferimento, numerosità, mediana del Jaccard con 10° e 90° percentile e ricampionamenti validi.
- **Assignment stability**: per il k scelto in *k dei report per osservazione*, gruppo di riferimento e accordo di ogni riga, cioè la frazione di ricampionamenti validi in cui conserva il gruppo. **Usa il risultato come dati** lo trasforma in una tabella normale.
- **Co-assignment** (facoltativo): la frazione di ricampionamenti validi in cui due righe finiscono nello stesso gruppo, per il k dei report. È simmetrica, con valori fra 0 e 1, e le righe sono nell'ordine del foglio.
- **Reference centers**: i centri del riferimento nelle unità originali e sulla scala di calcolo.
- **Seed sensitivity**: l'ARI di ogni ripetizione con altro seme. Compare solo se le ripetizioni sono attive.
- **Settings**: variabili, opzioni, campionamento, righe usate e incomplete, semi, limiti e una nota di interpretazione.

Se il riferimento di un k non si può calcolare, la sua riga riporta il motivo e le misure restano vuote. Se manca per tutti i k, il calcolo si ferma con l'errore e puoi correggere le opzioni. Quando non ci sono ricampionamenti validi le celle aggregate restano vuote.

## Grafico

Il primo pannello mette k sull'asse X e la mediana dell'ARI sull'asse Y, con la fascia fra 10° e 90° percentile. Con le ripetizioni attive aggiunge la loro mediana. I k senza ricampionamenti validi lasciano una lacuna segnata. Con la matrice attiva, il secondo pannello mostra la co-assegnazione per il k dei report con scala colori da 0 a 1. Il grafico entra nei layout e si esporta in PNG, SVG e PDF dal comando Esporta. Linee e testi restano vettoriali, mentre la mappa di co-assegnazione è un'immagine raster.

## Come leggere i risultati

Le misure descrivono la stabilità rispetto a questa perturbazione, cioè sottocampioni e semi. La fascia 10°–90° è fatta di percentili empirici dei ricampionamenti validi. Non è un intervallo di confidenza per k e un ARI alto non dimostra che i gruppi esistano davvero. Su dati con gruppi sovrapposti, cambiare il seme può spostare le misure. Conviene confrontare più semi prima di trarre conclusioni.

## Limiti e tempi

Il dialogo controlla i limiti quando premi **Esegui analisi**, prima di avviare qualsiasi calcolo:

- al massimo 20.000 righe complete e N × k massimo fino a 2.000.000;
- al massimo 6.000 fit K-means in tutto, cioè (numero di k) × (1 + ricampionamenti + ripetizioni);
- N × variabili × somma dei k × fit per k fino a 600 milioni;
- ogni campione deve avere almeno k massimo + 1 righe, e servono almeno k massimo osservazioni distinte.

Un limite superato evidenzia il campo da correggere: Ricampionamenti, Ripetizioni con altri semi, k massimo o la matrice. Il calcolo gira in background, la barra di stato mostra l'avanzamento e **Annulla** si ferma fra un fit e l'altro. Se annulli, ricetta e risultati precedenti restano come prima. Se annulli una nuova analisi, il progetto non cambia. Con **Calcolo multicore** (Impostazioni) i fit si distribuiscono sui processi scelti e i risultati restano identici. Hartigan–Wong costa molto più di Lloyd. Su 2.000 righe × 6 variabili, k da 2 a 6 e 30 ricampionamenti, nella macchina di prova Lloyd ha impiegato circa 12 s con un processo e 3–4 s con quattro. Hartigan–Wong ha impiegato circa 135 s con un processo e 37 s con quattro.

## Riproducibilità

Con lo stesso seme e gli stessi dati i risultati sono identici. I campioni dipendono solo dal seme e dal numero del ricampionamento, quindi aumentare i ricampionamenti aggiunge repliche in coda e lascia invariate le prime. Cambiare l'intervallo di k non cambia i campioni dei k già presenti. Un altro programma può ottenere partizioni diverse a parità di seme, perché la sequenza di inizializzazione può essere diversa.

## Esempio

`docs/examples/Stabilita-KMeans.alab` contiene 20 righe sintetiche in tre gruppi separati, con due righe incomplete, e la ricetta con k da 2 a 4, 30 ricampionamenti e la matrice di co-assegnazione per k = 3. All'apertura Trama ricalcola i risultati. Con k = 3 l'ARI mediano è 1. Con k = 2 e k = 4 l'accordo cala, perché i campioni spezzano o uniscono i gruppi in modi diversi.

## Riferimenti

- Hubert L, Arabie P. [Comparing partitions](https://doi.org/10.1007/BF01908075). Journal of Classification, 1985.
- Hennig C. [Cluster-wise assessment of cluster stability](https://doi.org/10.1016/j.csda.2006.11.025). Computational Statistics & Data Analysis, 2007. Qui il ricampionamento è senza reinserimento e l'abbinamento è uno a uno.

## Immagini

Schermate e file d'esempio prodotti dallo smoke su dati sintetici sono in `docs/media/kmeans-stability-096/`: dialogo, errori nel dialogo, grafico, foglio Assignment stability, esportazioni PNG e SVG e i CSV.
