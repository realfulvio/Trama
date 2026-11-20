# Rimodellare un foglio da lungo a largo e viceversa

**Analizza → Elaborazione dati → Rimodella lungo e largo** (inglese: Analyze → Data Processing → Reshape long and wide) porta un foglio dalla struttura *lunga* (una riga per misura) a quella *larga* (una riga per soggetto, una colonna per livello) e ritorno. Serve per preparare misure ripetute, dati multivariabili e grafici partendo da dati acquisiti nell'altra forma. Il risultato è un'analisi come le altre: si ricalcola quando cambia il foglio, si esporta in CSV, si analizza con **Analizza questo risultato…** (collegamento vivo) o si trasforma in un foglio con **Usa risultato come dati**. Il foglio di partenza non viene mai modificato.

Le altre due funzioni vicine restano come prima: **Riorganizza repliche** impila le repliche di più colonne, **Estrai e riorganizza** costruisce fogli XY, Column, Grouped o Contingency.

Si usa nella finestra standard (Qt). La finestra classica calcola una ricetta salvata ma non ha l'editor: per cambiarla si usa la finestra standard.

## Da lungo a largo

| Campo | Contenuto |
| --- | --- |
| Direzione | `Long to wide` |
| Colonne ID | una o più colonne chiave, in ordine (si spuntano e si ordinano con le frecce) |
| Colonna dei nomi | la colonna con il livello di ogni misura (per esempio la visita) |
| Colonna dei valori | la colonna con le misure |

Esempio (`tests/data/reshape_long_wide/long.csv`):

| Sample $ | Rep | Visit | Measure |
| --- | --- | --- | --- |
| 001 | 1 | A \| Start | 5 |
| 001 | 1 | Fine à | 6 |
| 001 | 2 | A \| Start | 0 |
| 001 | 2 | Fine à | *(vuoto)* |
| 002 | 1 | A \| Start | 8 |
| … | | | |

diventa

| Sample $ | Rep | A \| Start | Fine à |
| --- | --- | --- | --- |
| 001 | 1 | 5 | 6 |
| 001 | 2 | 0 | *(vuoto)* |
| 002 | 1 | 8 | 7 |
| 002 | 2 | 9 | 11 |

Regole:

* Una riga per ogni combinazione delle colonne ID, nell'ordine in cui compare la prima volta; prima le colonne ID, poi una colonna per livello, nell'ordine di prima comparsa.
* Il livello è l'etichetta letterale: niente cambi di maiuscole, accenti o segni, e nessun separatore viene interpretato (`A | Start` e `$` restano tali). Un numero diventa il nome nella forma più corta: 1,0 dà `1`, 2,5 dà `2.5`.
* Testo e numeri restano distinti: se il testo `"1"` e il numero 1 darebbero la stessa colonna `1`, Trama si ferma con un errore su **Colonna dei nomi** che mostra le due righe e i due valori. Lo stesso se un livello ha il nome di una colonna ID.
* Due righe con lo stesso ID e lo stesso livello sono un errore che mostra entrambe le righe, anche se una delle due misure è vuota. Trama non fa medie né somme: si aggiunge una colonna ID che le distingua (per esempio la replica) oppure si toglie una riga.
* Una misura vuota con chiave e livello validi resta una cella vuota *mappata*. Una combinazione mai osservata resta vuota e non ha riga nella mappa.
* Le chiavi mantengono il loro tipo: `001` resta testo, gli interi grandi restano esatti. Se una colonna di interi deve ospitare celle vuote diventa decimale solo quando i valori ci stanno esattamente, altrimenti resta intera con celle vuote.

## Da largo a lungo

| Campo | Contenuto | Predefinito |
| --- | --- | --- |
| Direzione | `Wide to long` | |
| Colonne ID | una o più colonne, in ordine | |
| Colonne delle misure | le colonne da impilare, in ordine | |
| Intestazione dei nomi | il titolo della nuova colonna con il nome della misura | `Variable` |
| Intestazione dei valori | il titolo della nuova colonna con il valore | `Value` |
| Escludi i valori mancanti | toglie le misure vuote | no |

* Ogni riga di origine dà una riga per misura: prima l'ordine delle righe, poi l'ordine delle colonne delle misure scelto nella lista.
* Le colonne ID devono identificare ogni riga: con due righe uguali Trama mostra le loro posizioni sul campo **Colonne ID**; basta spuntare un'altra colonna ID e rieseguire.
* Le due intestazioni nuove non possono coincidere tra loro né con una colonna ID (anche se scritte a mano).
* **Escludi i valori mancanti** toglie solo le celle vuote: zeri, valori falsi e testi (anche uno spazio) restano.
* I valori mantengono il tipo: i numeri restano numeri e i testi restano testi, compresi `001` e `"5"`. Una stringa che sembra un numero non diventa una misura. In **Settings** c'è il tipo di ogni colonna delle misure (`Numeric`, `Text`, `Mixed`) e quello della colonna dei valori.

### Colonne miste, CSV e progetto

Se le colonne delle misure hanno tipi diversi (numeri in una, testi nell'altra) la colonna dei valori è *mista*: contiene il numero 5 e il testo `"5"` come valori distinti.

* Nel progetto `.alab` (con **Usa risultato come dati**) la colonna viene salvata come mista e torna identica alla riapertura: 5 resta numero, `"5"` resta testo, `001` resta testo.
* Il CSV non ha tipi: il numero 5 e il testo `"5"` diventano entrambi `5`. Alla reimportazione la colonna è testo (perché contiene anche testo). Le chiavi come `001` tornano testo perché iniziano con zero. Per conservare i tipi si usa il progetto `.alab`.
* L'esportazione di una tabella dei risultati, come per tutte le analisi, scrive anche la colonna dell'indice (0, 1, 2…).

## Reversibilità

* Largo → lungo → largo ricostruisce la tabella di partenza con gli stessi tipi.
* Lungo → largo → lungo ricostruisce la tabella di partenza se tutte le combinazioni erano presenti. Una combinazione mai osservata, dopo il passaggio al largo, è una cella vuota come una misura vuota: tornando al lungo diventa una riga con valore vuoto. Con **Escludi i valori mancanti** quelle righe spariscono, ma spariscono anche le misure vuote originali: la distinzione tra "assente" e "presente ma vuota" non si può ricostruire dalla tabella larga. La **Source map** del primo passaggio la conserva.

## Righe vuote, esclusioni e chiavi incomplete

* Trama legge il foglio mascherato: una cella esclusa arriva vuota e resta vuota (non si recupera il dato originale, non si mette zero, non si copia il valore vicino).
* Una riga vuota in tutte le colonne scelte viene saltata (sono le righe in fondo al foglio) ed è contata in **Settings**.
* Una riga con dati ma con la chiave vuota è un errore che indica la riga: si corregge la cella o si esclude la riga e si riesegue; la ricetta resta com'era.

## Anteprima e limiti

La pagina **Anteprima** del dialogo mostra il numero di righe e di colonne del risultato, le celle mappate e quelle vuote, e le prime 25 righe e 12 colonne (con quante ne restano fuori). Usa gli stessi controlli del calcolo e conta chiavi e livelli senza costruire la matrice, quindi gli errori si vedono prima di **Esegui**. Il calcolo vero gira sul thread di lavoro della finestra e si annulla con il pulsante Annulla della barra di stato.

Ogni tabella del risultato deve stare nei limiti dei fogli di Trama: al massimo 512 colonne e 2.000.000 di celle. Si controllano prima di allocare: la tabella rimodellata (righe × colonne) e la **Source map** (4 celle per misura, quindi al massimo 500.000 misure). Oltre il limite il messaggio dice quante righe, colonne o celle servirebbero.

## Tabelle del risultato

* **Reshaped data**: il foglio rimodellato.
* **Source map**: una riga per ogni misura presente nel risultato, comprese quelle vuote mantenute: `Source row` e `Source column` (riga del foglio, contata da 1, e nome della colonna di origine: la colonna dei valori nel passaggio al largo, la colonna della misura nel passaggio al lungo), `Result row` e `Result column` (riga contata da 1 e nome della colonna nel risultato). La vista delle tabelle dei risultati numera le righe da 0: `Result row` 1 è la riga 0 della vista.
* **Settings**: direzione, colonne scelte, tipi, righe usate e saltate, dimensioni, celle mappate, vuote e combinazioni mai osservate.

## Ricetta

La ricetta salva solo i campi della direzione scelta, con i nomi e i valori canonici in inglese (`Direction`, `ID columns`, `Name column`, `Value column`, `Measure columns`, `Output names`, `Output values`, `Drop missing values`). Nel dialogo, passando da una direzione all'altra, le scelte dell'altra direzione restano e si ritrovano tornando indietro, ma non finiscono nel progetto.

Il [progetto di esempio](examples/rimodella-visite.alab) contiene un foglio con una cella esclusa, un rimodellamento e un grafico Column collegato al risultato.

Riferimento: H. Wickham, *Tidy Data*, Journal of Statistical Software 59(10), 2014, [doi:10.18637/jss.v059.i10](https://doi.org/10.18637/jss.v059.i10).
