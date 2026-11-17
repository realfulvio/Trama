# Analisi collegate

Un risultato può diventare l’ingresso di un’altra analisi senza creare una copia dei dati. Per esempio: dati sperimentali → trasformazione → normalizzazione → regressione. Le modifiche ai dati sorgente, alle esclusioni, alle formule e ai parametri si propagano alle analisi dipendenti e ai loro grafici.

## Creare un collegamento

1. Apri un’analisi calcolata e seleziona la scheda dei risultati da utilizzare.
2. Premi **Analizza questo risultato…** e scegli il metodo e le colonne nel dialogo di analisi.
3. Dopo il calcolo, la nuova analisi appare sotto la sorgente nella famiglia. La barra **Ingresso** identifica l’analisi e la tabella utilizzate.

**Analisi sorgente** torna alla scheda di ingresso. **Cambia risultato di ingresso…** consente di scegliere un’altra analisi e una sua tabella, oppure i dati originali. Il passaggio successivo fa rivedere i parametri; Annulla mantiene la ricetta confermata. Un ciclo viene rifiutato nel dialogo.

Il comando ordinario **Analizza dati…**, quando si guarda un’analisi collegata, usa lo stesso ingresso di quell’analisi. Il comando esplicito **Analizza questo risultato…** usa invece la scheda di uscita selezionata.

## Collegamento o copia

**Usa risultato come dati** conserva il comportamento precedente: crea una tabella modificabile e indipendente. Le successive modifiche alla sorgente non aggiornano quella copia. I risultati collegati restano in sola lettura: si modificano i dati o i parametri da cui derivano.

Le colonne delle repliche e le etichette di riga restano disponibili per l’analisi successiva. I nomi delle tabelle e delle colonne sono letterali, anche quando l’interfaccia cambia lingua.

## Aggiornamento e problemi

Il ricalcolo avviene sul worker, nell’ordine delle dipendenze. Ogni nodo interessato viene calcolato una volta per revisione. Aprire per primo un grafico finale o un layout collegato riaperto ricostruisce anche le analisi sorgente non ancora calcolate.

Se una sorgente fallisce, i risultati precedenti restano consultabili con un avviso che li distingue dai risultati attuali. Esportazione e riutilizzo sono bloccati finché il problema non viene corretto e il ricalcolo riesce. Lo stesso vale per i layout che contengono un pannello non aggiornato.

Se un cambio di metodo elimina una tabella usata a valle, **Cambia risultato di ingresso…** permette di riparare il collegamento. Non viene scelta automaticamente un’altra tabella. Annullare un ricalcolo dopo una modifica ai dati conserva i risultati precedenti come non aggiornati; annullare un ricalcolo manuale di risultati già correnti li conserva validi.

Le annotazioni dei confronti statistici richiedono un’analisi che usi lo stesso ingresso del grafico. Avere colonne con nomi uguali non basta.

## Salvataggio e compatibilità

I progetti con collegamenti usano il formato `.alab` versione 3. Le versioni precedenti del programma li rifiutano: non aprirli con una vecchia build. I progetti senza collegamenti e con al massimo 256 analisi per tabella continuano a usare il formato 2.

Il budget complessivo è di 65.536 analisi per progetto, senza un limite di profondità separato. Ogni tabella dei risultati usata come ingresso deve essere non vuota, avere nomi di colonna non ambigui e rispettare il limite di due milioni di celle. Questo budget è un limite di validazione del formato, non una promessa di prestazioni per progetti di tale dimensione.

L’interfaccia dei nuovi comandi è disponibile in inglese e italiano; nomi canonici delle analisi e dei risultati restano nel progetto. Questa funzione non elimina i limiti dei singoli metodi statistici.
