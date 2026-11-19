# Galleria Qt di grafici e layout

## Funzione da consegnare

Aggiungere una galleria navigabile al workbench Qt. Oggi il navigatore elenca i fogli e apre le singole pagine, mentre la vista a galleria esiste nell'interfaccia classica. Un progetto con decine di grafici deve permettere di cercarli visivamente, distinguere grafici e layout e passare al foglio reale.

Usare `Project`, i riferimenti dei fogli di `trama_qt/window.py` e le figure confermate del motore. Il riferimento funzionale classico è in `analisi/gallery.py` e nelle funzioni `open_gallery` e `gallery_thumbnail`. Progettare un modulo Qt separato, usando model/view e delegati Qt per le card.

## Contratto funzionale

1. Azione Galleria nella scheda Visualizza. Vista Tutti/Grafici/Layout, con nomi, tipo e anteprima quando disponibile. La ricerca filtra senza modificare i dati e gestisce accenti, spazi, nomi duplicati e caratteri come il dollaro. Il titolo resta letterale. I layout importati a cui Qt ha accesso possono aprirsi come tali.
2. Le card devono distinguere fogli pronti, non calcolati e risultati divenuti obsoleti. La galleria mostra un segnaposto esplicito quando il risultato manca. Aprire una voce usa la navigazione standard e il ricalcolo ordinario della pagina, mantenendo gestione errori e annullamento. La scansione della galleria non lancia calcoli che l'utente non ha chiesto.
3. Generare anteprime delle sole card visibili attraverso una piccola coda, con cache limitata e invalidazione su stile, dati e ricalcolo. Un disegno di anteprima non prende possesso del canvas di una figura confermata. Le miniature di vecchi progetti devono sparire al cambio di progetto. Il disegno Matplotlib e l'accesso ai widget restano sicuri rispetto al thread GUI.
4. Selezione e apertura con frecce, Invio e doppio clic. Esc o Indietro torna al foglio di partenza, con focus coerente. Modifiche al foglio, chiusura, salvataggio e bozze dell'Ispettore continuano a seguire i percorsi esistenti. Filtri e apertura galleria sono stato di visualizzazione. Su errore o mancanza di grafici ci sono istruzioni brevi utilizzabili anche da tastiera.
5. EN/IT, chiaro e scuro, finestre piccole. Titoli e stato non dipendono soltanto dal colore. Thumbnail di pagina autosimile senza stiramenti. La galleria non cambia l'export dei grafici o layout, né il loro formato salvato.

Per il verificatore esterno usare `window.actions["gallery"]`. Dare alla lista il nome `sheetGallery` e alla ricerca `gallerySearch`. Esporre nel ruolo Qt UserRole il riferimento di navigazione già usato dal workbench, per esempio ("graph", 0). Il filtro iniziale mostra grafici e layout. Il layout della vista e le etichette restano a scelta del progettista.

## Fixture e prove

- `fixtures/galleria.alab` contiene tre grafici e due layout. All'apertura i risultati possono essere pendenti. La ricerca `Calibrazione $` trova un solo grafico e Invio apre il grafico corrispondente da posizione 0.
- Verificare conteggio, filtro, apertura di layout, ritorno alla vista precedente, invalidazione su un dato cambiato e dopo Format Graph, un errore di calcolo e una nuova apertura di un altro progetto. Misurare un caso 120 schede e registrare tempi, numero di miniature e picco memoria. Controllare che scorrere produca le sole miniature necessarie e che i click restino reattivi. Conservare un confronto a parità di dati.
- Smoke Qt a 1024×768 e 1600×1000, EN/IT, chiaro/scuro se disponibile. Coprire layout numerato, ricerca `$`, grafico senza risultato, cambio foglio con Invio, ricalcolo, anteprima aggiornata e export della figura dalla sua pagina. Aggiungere un caso di errore e almeno un controllo sulla pulizia della cache.
- Mantenere compatibile l'uso di `MainWindow.project` e della navigazione già presente quando arriveranno le schede multiple. Questo pacchetto si sviluppa e si prova da solo.

## Ordine di lavoro

- Catalogo, filtro, stato e cache delle miniature con test.
- Vista a galleria Qt e apertura reale dei fogli.
- Prestazioni, smoke e guida. Gli agganci a `window.py` devono stare nell'area visualizzazione e navigatore.
