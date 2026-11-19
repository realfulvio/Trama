# Unire due fogli per chiave

**Analizza → Elaborazione dati → Unisci fogli per chiave…** (inglese: Analyze → Data Processing → Join worksheets by key) collega le righe di due fogli dati dello stesso progetto che hanno la stessa chiave: per esempio le misure di un campione e la sua anagrafica di visita. Il risultato è un'analisi come le altre: si ricalcola da solo quando cambia uno dei due fogli, si può esportare in CSV, analizzare con **Analizza questo risultato…** o trasformare in un foglio con **Usa risultato come dati**.

La funzione si usa nella finestra standard (Qt). La finestra classica (`--tk`) conserva la ricetta ma non la calcola e non la modifica.

## Esempio

Il progetto `tests/data/worksheet_join/unione-campioni.alab` ha due fogli.

`Misure $` (sinistra):

| Sample | Visit | Signal | Signal [right] |
| --- | --- | --- | --- |
| 1 | A | 10 | L1 |
| 1 | B | 20 | L2 |
| "1" (testo) | A | 30 | L3 |
| (vuoto) | A | 40 | L4 |
| 2 | C | 50 | L5 |

`Anagrafica | visite` (destra):

| ID | Time | Signal | Batch $ |
| --- | --- | --- | --- |
| 1 | A | 100 | A1 |
| 1.0 | A | 101 | A2 |
| "1" (testo) | A | 102 | A3 |
| (vuoto) | A | 200 | A4 |
| 3 | D | 300 | A5 |

1. Apri `Misure $` e scegli **Unisci fogli per chiave…**. Il foglio aperto è quello di sinistra.
2. In **Foglio di destra** scegli `Anagrafica | visite`. Le colonne di destra si aggiornano subito.
3. Nella **Coppia 1** abbina `Sample` a `ID`; con **Aggiungi coppia** abbina `Visit` a `Time` (fino a 4 coppie, una per riga, sinistra e destra affiancate).
4. In **Opzioni** scegli **Tipo di unione: Completa** e **Cardinalità: Uno a molti**, poi **Esegui**.

Il risultato **Joined data** ha 8 righe: la prima riga di sinistra (1, A) trova due righe di destra (1 e 1.0 hanno lo stesso valore), la riga con "1" testuale trova solo il "1" testuale, le righe con chiave incompleta restano senza corrispondenza e le due righe di destra non abbinate compaiono in fondo, con la loro chiave nelle colonne `Sample` e `Visit`. La colonna `Signal` di destra diventa `Signal [right 2]`, perché `Signal [right]` esiste già a sinistra.

Con **Uno a uno** l'unione si ferma: il foglio di destra ripete la chiave (1, A) alle righe 1 e 2. Il dialogo si riapre con il messaggio e il cursore su **Cardinalità**; si corregge lì stesso.

## Chiavi

- Il testo deve coincidere esattamente, maiuscole e spazi compresi (`"A "` non è `"A"`).
- I numeri interi e decimali coincidono se hanno lo stesso valore (1 e 1,0), senza perdere precisione sugli interi grandi. Un numero non coincide mai con il testo che gli somiglia (`1` e `"1"`).
- Vero/falso coincide solo con vero/falso, non con 1 o 0.
- Una chiave con una cella vuota, esclusa o non finita non coincide con niente: la riga resta "non abbinata". Le celle escluse arrivano vuote anche nelle colonne dei dati.
- Le formule si calcolano prima dell'unione: si può usare come chiave una colonna calcolata.
- Una cella di un altro tipo (per esempio una data importata) ferma l'unione con un errore sulla coppia, che indica colonna e riga.

Attenzione: in una colonna mista (numeri e testo), quello che si scrive nella griglia può diventare testo. Se `2` scritto a mano non trova il `2` numerico dell'altro foglio, controlla il tipo della cella.

## Tipo di unione e cardinalità

| Tipo | Righe nel risultato |
| --- | --- |
| Interna | solo le coppie abbinate |
| Da sinistra (predefinita) | tutte le righe di sinistra, abbinate o no |
| Completa | come Da sinistra, più le righe di destra senza corrispondenza, in fondo e nel loro ordine |

La **cardinalità** dice quali chiavi devono essere uniche: il primo termine è la sinistra. *Uno a molti* vuole chiavi uniche a sinistra, *Molti a uno* a destra, *Uno a uno* (predefinita) su entrambi i lati, *Molti a molti* nessun vincolo. Il controllo vale per tutte le chiavi complete, anche per quelle che non trovano corrispondenza.

Il risultato può avere al massimo 100.000 righe e 2.000.000 di celle. Il numero di righe si conta prima di costruire il risultato: con troppe chiavi ripetute l'errore arriva subito su **Tipo di unione**, con la stima e il limite.

## Risultati

- **Joined data**: tutte le colonne di sinistra nell'ordine, poi le colonne di destra che non sono chiavi. Un nome già usato diventa `Nome [right]`, `Nome [right 2]`… senza toccare i nomi di destra che non sono in conflitto. Le righe seguono l'ordine di sinistra, l'ordine di destra dentro una corrispondenza multipla e infine le righe solo di destra.
- **Join provenance**: per ogni riga del risultato il numero di riga (da 1) nel foglio di sinistra e in quello di destra e lo stato `Matched`, `Left only` o `Right only`.
- **Join diagnostics**: righe in ingresso, righe con chiave incompleta, coppie abbinate e righe non abbinate dei due lati (contate anche quando il tipo di unione non le mostra), righe in uscita.

I nomi dei fogli di risultato, delle colonne e degli stati restano in inglese in tutte le lingue, come nelle altre analisi e nei CSV.

## Ricalcolo, salvataggio e copie

- Modificare, escludere o annullare una cella in uno dei due fogli ricalcola l'unione e le analisi collegate al suo risultato. Se non cambia niente, aprire il risultato non ricalcola niente.
- Il foglio di destra è ricordato con il suo titolo esatto nel file `.alab`. Se non c'è più (per esempio in un progetto copiato a mano) il risultato mostra un errore che lo nomina; **Cambia parametri** mostra il titolo come "(mancante)" e chiede di sceglierne un altro. Trama non sceglie mai da solo un foglio sostitutivo.
- **Duplica famiglia** dal foglio di sinistra crea una copia che continua a leggere lo stesso foglio di destra del progetto. Se la copia comprende anche il foglio di destra, l'unione copiata legge la copia.
- **Salva famiglia come…** porta con sé anche il foglio di destra, così l'unione si apre e si calcola nel nuovo progetto.
- Ogni scheda di progetto ha i suoi fogli: due progetti aperti con titoli uguali non si mescolano.
- Per ora Trama Qt non rinomina né elimina i fogli dati, quindi un riferimento non può cambiare sotto un'unione esistente.
