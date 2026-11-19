# Algoritmi K-means

In **Raggruppamento k-means** e **Selezione del modello k-means** puoi scegliere **Lloyd** con inizializzazione K-means++, **Hartigan–Wong** e **MacQueen**. Per Hartigan–Wong, il limite di iterazioni conta i giri di trasferimenti ottimali e rapidi. Il calcolo con seme usa fino a dieci partenze da osservazioni distinte. Fra le partenze convergenti conserva la soluzione con la somma dei quadrati interna più bassa.

MacQueen parte con K-means++ e visita le osservazioni nell'ordine del foglio. Ogni trasferimento verso un centro strettamente più vicino aggiorna subito i centri dei due gruppi. Un pareggio mantiene l'assegnazione e l'ultimo elemento di un gruppo resta nel gruppo. Il limite conta i giri sul foglio e il calcolo richiede un giro senza trasferimenti per confermare la convergenza.

Nel raggruppamento Hartigan–Wong o MacQueen puoi fornire una riga iniziale per gruppo. Scrivi i numeri delle righe del foglio separati da virgole, partendo da 1. Ogni riga deve avere tutti i valori selezionati, e le righe devono individuare centri distinti. Il campo vuoto usa l'inizializzazione con seme. Con la standardizzazione, centri e somma dei quadrati sono riportati sulla scala di calcolo.

Nella selezione del numero di gruppi l'algoritmo e il limite scelti valgono anche per i campioni di riferimento Gap. Il consenso usa i fit calcolati in quella ricerca. Con una ricetta importata compatibile, Trama ripristina il seme, il limite di iterazioni e l'intervallo di k. Le partenze e i campioni Gap vengono generati da Trama. Due programmi possono ricavare partizioni diverse a parità di seme perché la sequenza di inizializzazione può essere diversa. Puoi consultare le viste originali archiviate dove disponibili.

## Report da un fit o da una ricerca di k

Apri la scheda **Risultati** per scegliere le tabelle aggiuntive. La ricerca di k riusa tutti i fit già calcolati. **Assegnazioni per ogni k** affianca una colonna di gruppo per ogni modello ai dati di origine, con celle vuote per le righe incomplete. **Dettagli dei gruppi** riporta centro, numerosità e somma dei quadrati interna per variabile. **Distanze dal centro assegnato** misura la distanza euclidea sulla scala del fit. La somma dei quadrati di queste distanze coincide con la WSS. La tabella delle osservazioni standardizzate è disponibile con la standardizzazione attiva.

**Centri iniziali** riporta i centri della partenza effettivamente selezionata dal motore per ciascun fit. **Statistiche Gap** aggiunge i log della WSS osservata e di riferimento per i k per cui il calcolo è disponibile.

**ANOVA descrittiva dei gruppi** scompone la variazione per variabile e riporta F e p nominale quando calcolabili. Poiché i gruppi sono ricavati dalle stesse variabili, questi valori descrivono la partizione e richiedono dati indipendenti per un uso confermativo. La tabella **Variazione dei gruppi** riporta le quote interna e spiegata se la variazione totale è positiva.

L'importazione recupera le opzioni dei report dove riconosciute. Trama ricalcola tabelle e misure sulla propria partizione. Per confrontare con una partizione salvata, usa le tabelle archiviate del progetto originale.

Nella scheda **Grafico** della selezione di k puoi affiancare al criterio scelto il gomito della WSS, la silhouette media e la statistica Gap con barre di un errore standard. Le curve usano le stesse partizioni delle tabelle. Attivare il grafico Gap calcola i campioni di riferimento anche con un altro criterio di scelta. Una ricetta importata compatibile recupera le tre opzioni di visualizzazione e le rende in un’unica figura Trama. Le viste importate conservano la presentazione archiviata dove disponibile.

Quando la PCA salvata usa il foglio delle assegnazioni compatibile, Trama la collega a **Assegnazioni per ogni k**. Modifica il foglio di origine per ricalcolare in ordine clustering e PCA. **Analisi sorgente** apre le assegnazioni correnti. Per le viste che non corrispondono al foglio di origine, la PCA compatibile resta disponibile sui dati archiviati.
