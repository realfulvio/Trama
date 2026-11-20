# Algoritmi K-means

L'opzione **Scala delle colonne** permette di usare i valori originali, sottrarre la media di ogni colonna oppure standardizzare con la deviazione standard campionaria. I centri e le distanze sono espressi nella scala del calcolo. La tabella delle osservazioni scalate è disponibile con centratura e standardizzazione.

In **Raggruppamento k-means** e **Selezione del modello k-means** puoi scegliere **Lloyd**, **Forgy–Lloyd**, **Hartigan–Wong** e **MacQueen**. Lloyd usa più partenze K-means++ e conserva la soluzione con la somma dei quadrati interna più bassa. Per Hartigan–Wong, il limite di iterazioni conta i giri di trasferimenti ottimali e rapidi. Il calcolo con seme usa fino a dieci partenze da osservazioni distinte. Fra le partenze convergenti conserva la soluzione con la somma dei quadrati interna più bassa.

**Forgy–Lloyd** usa una sola partenza K-means++ determinata dal seme. Il limite conta gli aggiornamenti completi dei centroidi. Al limite il risultato riporta l’ultima assegnazione e i centroidi calcolati da quella assegnazione. Per dato, seme e scala identici, i primi k centroidi iniziali coincidono anche se cambia l’intervallo della selezione del modello.

MacQueen parte con K-means++ e visita le osservazioni nell'ordine del foglio. Ogni trasferimento verso un centro strettamente più vicino aggiorna subito i centri dei due gruppi. Un pareggio mantiene l'assegnazione e l'ultimo elemento di un gruppo resta nel gruppo. Il limite conta i giri sul foglio e il calcolo richiede un giro senza trasferimenti per confermare la convergenza.

Nel raggruppamento Forgy–Lloyd, Hartigan–Wong o MacQueen puoi fornire una riga iniziale per gruppo. Scrivi i numeri delle righe del foglio separati da virgole, partendo da 1. Ogni riga deve avere tutti i valori selezionati, e le righe devono individuare centri distinti. Il campo vuoto usa l'inizializzazione con seme. Con la standardizzazione, centri e somma dei quadrati sono riportati sulla scala di calcolo.

Nella selezione del numero di gruppi l'algoritmo e il limite scelti valgono anche per i campioni di riferimento Gap. Il consenso usa i fit calcolati in quella ricerca. Con una ricetta importata compatibile, Trama ripristina il seme, il limite di iterazioni e l'intervallo di k. Le partenze e i campioni Gap vengono generati da Trama. Due programmi possono ricavare partizioni diverse a parità di seme perché la sequenza di inizializzazione può essere diversa. Puoi consultare le viste originali archiviate dove disponibili.

**Geometria del riferimento Gap** definisce la regione da cui si estraggono i campioni uniformi, dopo la scalatura scelta. **Intervalli delle variabili** usa i limiti delle colonne ed è la scelta predefinita per le nuove analisi e i progetti Trama che non specificano una geometria. **Intervalli delle componenti principali** usa i limiti lungo le direzioni principali della nuvola di punti. Le ricette esterne compatibili di selezione K-means adottano questa geometria con 100 simulazioni quando rientrano nel limite di calcolo. Per i progetti più grandi, la ricetta usa il massimo numero consentito, a partire da 20, e lo indica nel risultato. La geometria cambia il riferimento Gap e il suo errore standard. Le osservazioni e i fit dei dati reali restano gli stessi. [Tibshirani, Walther e Hastie](https://doi.org/10.1111/1467-9868.00293).

## Report da un fit o da una ricerca di k

Apri la scheda **Risultati** per scegliere le tabelle aggiuntive. La ricerca di k riusa tutti i fit già calcolati. **Assegnazioni per ogni k** affianca una colonna di gruppo per ogni modello ai dati di origine, con celle vuote per le righe incomplete. **Dettagli dei gruppi** riporta centro, numerosità e somma dei quadrati interna per variabile. **Distanze dal centro assegnato** misura la distanza euclidea sulla scala del fit. La somma dei quadrati di queste distanze coincide con la WSS. La tabella delle osservazioni standardizzate è disponibile con la standardizzazione attiva.

**Centri iniziali** riporta i centri della partenza effettivamente selezionata dal motore per ciascun fit. **Statistiche Gap** aggiunge i log della WSS osservata e di riferimento per i k per cui il calcolo è disponibile.

**ANOVA descrittiva dei gruppi** scompone la variazione per variabile e riporta F e p nominale quando calcolabili. Poiché i gruppi sono ricavati dalle stesse variabili, questi valori descrivono la partizione e richiedono dati indipendenti per un uso confermativo. La tabella **Variazione dei gruppi** riporta le quote interna e spiegata se la variazione totale è positiva.

L'importazione recupera le opzioni dei report dove riconosciute. Trama ricalcola tabelle e misure sulla propria partizione. Per confrontare con una partizione salvata, usa le tabelle archiviate del progetto originale.

Nella scheda **Grafico** della selezione di k puoi affiancare al criterio scelto il gomito della WSS, la silhouette media e la statistica Gap con barre di un errore standard. Le curve usano le stesse partizioni delle tabelle. Attivare il grafico Gap calcola i campioni di riferimento anche con un altro criterio di scelta. Una ricetta importata compatibile recupera le tre opzioni di visualizzazione e le rende in un’unica figura Trama. Le viste importate conservano la presentazione archiviata dove disponibile.

Quando la PCA salvata usa il foglio delle assegnazioni compatibile, Trama la collega a **Assegnazioni per ogni k**. Modifica il foglio di origine per ricalcolare in ordine clustering e PCA. **Analisi sorgente** apre le assegnazioni correnti. Per le viste che non corrispondono al foglio di origine, la PCA compatibile resta disponibile sui dati archiviati.
