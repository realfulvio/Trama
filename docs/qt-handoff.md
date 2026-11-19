# Consegna Qt per Codex

Questo file è il canale fisso tra Claude e Codex per la migrazione a Qt (PR #56, ramo `claude/project-thread-4unaln`).
Claude lo aggiorna a ogni commit; la voce più recente sta in cima. Il piano complessivo è in `docs/qt-migration.md`.

## Procedura per Codex, a ogni avanzamento

1. `git fetch origin claude/project-thread-4unaln && git checkout claude/project-thread-4unaln && git pull --ff-only`
2. Leggi la voce più recente qui sotto (e quelle che non hai ancora visto, confrontando il commit).
3. Test: `python -m unittest tests.test_qt_shell` (offscreen; su Windows imposta `QT_QPA_PLATFORM=offscreen` solo per i test) più la tua suite completa.
4. Prova a mano su Windows quello che la voce indica in "Da provare su Windows", a 100% e 150% di scala, e lancia `python -m trama_qt --smoke CARTELLA` alle due scale.
5. Rispondi con un commento sulla PR #56 (o scrivilo a Luca): commit provato, esito dei test, problemi con passi per riprodurli.

Regole fisse: niente merge e niente cambio di versione da parte di Claude; la grafica nuova si fa solo su Qt (il Vetro su Tk è fermo); `trama_qt` non deve importare `tkinter`; Windows resta NON PROVATO finché Codex non lo conferma.

## Avanzamenti

### 9c10a2f · Formule, cella con Invio e testo SVG: consegna finale per la 0.95 (2026-11-19)

**Consegna finale per la 0.95: il commit `9c10a2f`.** Il commit dopo aggiunge solo questa nota. Integra quella revisione.

- Colonne calcolate su Qt. Home → Formula… aggiunge una colonna calcolata o ne cambia una. Il doppio clic sull'intestazione di una colonna calcolata apre la sua formula, al posto del messaggio che rimandava a Tk. L'espressione viene verificata sulla tabella prima di tenerla e si può annullare. Codice in `trama_qt/formula.py` e `Project.set_formula`. Con questo la parità con la finestra classica è completa. La riproduzione di Codex (doppio clic sulla colonna calcolata) ora apre la formula.
- La cella si chiude con Invio: `closeEditor` usa `QAbstractItemDelegate.EndEditHint`, come nel candidato di Codex. Il test con F2, valore e Invio controlla che il valore sia scritto e che la selezione scenda di una riga.
- Esporta con opzioni ricorda anche Testo SVG (Tracciati) per la sessione.
- OK e Annulla tradotti in Esporta con opzioni, Formula e Proprietà del foglio Info. I testi di Qt (pulsanti dei messaggi, dialoghi file) usano `qtbase_it.qm` di PySide6 se presente (`theme.install_qt_translations`). Per il portabile serve che PyInstaller includa `PySide6/Qt/translations/qtbase_it.qm`.
- Nota per l'integrazione: la barra comandi troppo larga è corretta qui con lo scorrimento laterale di ogni scheda (b78e602). Il tuo candidato usa l'overflow delle azioni. Tieni la soluzione che preferisci: lo smoke Qt controlla solo che la finestra entri nello schermo.
- Da provare su Windows:
  - Formula… con nome "Double" e `=Control *` dà l'errore nel dialogo; con `=Control * 2` la colonna compare. Il doppio clic sulla sua intestazione riapre la formula; cambiarla in `* 3` e poi Annulla.
  - Esportare in SVG con Tracciati, poi riaprire il dialogo: Testo SVG resta su Tracciati.
  - In italiano, i pulsanti Salva/Non salvare/Annulla del messaggio di chiusura con modifiche.
  - `python -m trama_qt --smoke` a 100% e 150%.
- Test attesi: `tests.test_qt_shell` 20/20 OK. Nel container la suite completa dà 63 errori, tutti `No module named 'tkinter'` (il container non ha Tk); nessun altro errore.

### b78e602 · Smoke Qt e schermi piccoli al 150% (2026-11-19)

- Nuovo: `python -m trama_qt --smoke CARTELLA` (`trama_qt/smoke.py`), il collaudo da desktop per Qt descritto in `docs/qt-migration.md`. Gira in inglese e in italiano. Salva gli screenshot della finestra su ogni foglio e di ogni dialogo, poi scrive `report.txt` e `status.txt` (PASS o FAIL). Fallisce se un dialogo non entra nello schermo o se un testo è tagliato.
- Corretto quello che lo smoke ha trovato emulando schermi al 150%:
  - La barra dei comandi a schede imponeva alla finestra una larghezza minima di 2025 px (2231 in italiano). Ora ogni scheda scorre di lato.
  - I pulsanti delle pagine andavano a capo male e venivano tagliati. Ora stanno in un layout che va a capo (`trama_qt/flow.py`).
  - Ogni dialogo, quando si apre, viene ridotto e spostato dentro lo schermo (`theme.keep_on_screen`).
  - Importazione testo, Confronti a coppie e Forme scorrono in verticale sugli schermi bassi; i pulsanti restano sempre visibili.
- Esito nel container (offscreen con schermi emulati): PASS a 1920×1080 al 100%, 1920×1080 al 150% (1280×720 logici) e 1366×768 al 150% (911×512 logici).
- Da provare su Windows: lanciare `python -m trama_qt --smoke C:\temp\qt-smoke-100` a 100% e `...-150` a 150%. Allegare `report.txt`, guardare gli screenshot e segnalare i testi tagliati o i dialoghi fuori schermo che il controllo non vede.
- Test attesi: `tests.test_qt_shell` 19/19 OK (incluso lo smoke in inglese).

### a751bcd · Importazione guidata di file di testo su Qt (2026-11-19)

- Nuovo: File → Importa nel progetto… su un file .csv, .tsv o .txt apre l'importazione guidata. Codice in `trama_qt/text_import.py` e in `open_path` di `trama_qt/window.py`, stesso motore della versione Tk (`analisi.text_import`). Si sceglie separatore, decimali, intestazione, prima e ultima riga e colonna con salto, codice dei mancanti e `*` finale che esclude il valore. L'anteprima filtrata si aggiorna dal vivo e gli errori compaiono nel dialogo. I testi sono in italiano anche dove il dialogo Tk restava in inglese. Aprire un file di testo con Apri resta diretto.
- Con questo commit tutte le funzioni della finestra classica sono anche su Qt. Restano il porting dello smoke test e il collaudo DPI su Windows.
- Da provare su Windows:
  - File .txt con `;` e virgola decimale (ID;Dose;Risposta;Note), colonne 2–3, ultima riga 4, codice mancante -99, `*` finale attivo: in anteprima compaiono Dose e Risposta, il valore con `*` è segnato e dopo l'importazione è escluso.
  - Prima colonna "x" deve dare l'errore nel dialogo senza chiuderlo.
  - Un file non UTF-8 deve dare il messaggio di errore e non aprire il dialogo.
- Test attesi: `tests.test_qt_shell` 18/18 OK.

### ad09d92 · Catene di analisi su Qt (2026-11-19)

- Nuovo: Analizza questo risultato…, Analisi sorgente e Cambia risultato di ingresso… nella pagina dei risultati e dei grafici collegati, nella scheda Analizza e nel menu del tasto destro. Codice in `trama_qt/analysis_source.py` (scelta di sorgente e tabella, stesso comportamento del dialogo Tk) e `trama_qt/window.py` (`analyze_result_table`, `source_analysis`, `change_input_result`; `_ask` accetta la sorgente). Nel navigatore i risultati collegati compaiono sotto la loro sorgente. Il ricalcolo a catena c'era già.
- Da provare su Windows:
  - Tabella X 0..3, Y 1,3,5,7. Transform (valore assoluto), poi Analizza questo risultato → Normalize (sottrai il primo valore), poi Analizza questo risultato → Regressione lineare X/Y: pendenza 2.
  - Analisi sorgente dalla regressione: si apre Normalize sulla scheda "Normalized".
  - Cambia risultato di ingresso del Transform verso la regressione deve dare l'errore di ciclo nel dialogo.
  - Cambiare l'ingresso della regressione verso Transform/"Transformed", salvare e riaprire in Qt e in Tk: i collegamenti restano. Modificare una cella: si ricalcola tutta la catena.
- Test attesi: `tests.test_qt_shell` 17/17 OK.

### 1ab2343 · Esporta con opzioni su Qt (2026-11-19)

- Nuovo: File → Esporta con opzioni… (anche nella scheda Grafico) per grafici, layout e layout salvati. Codice in `trama_qt/export_options.py`; `export_graph` e `Project.export_layout` accettano le impostazioni. Stesse scelte del dialogo Tk: preset Schermo/Stampa/Vettoriale/Personalizzato, formato PNG/TIFF/SVG/PDF, larghezza in mm (vuota = dimensione attuale o pagina del layout), DPI per PNG e TIFF, sfondo trasparente, testo SVG come testo o tracciati, riga con dimensione finale in mm e pixel. Le scelte restano per la sessione. La destinazione passa da `check_destination`.
- Da provare su Windows:
  - Grafico a colonne, PNG a 85 mm e 200 DPI: il file deve essere largo 669 px.
  - Lo stesso in SVG con testo come tracciati: il file non deve contenere `<text>`.
  - Layout di due grafici in PDF a 180 mm: pagina larga 180 mm. In PNG deve comparire la nota sul raster.
  - Larghezza "abc" deve dare l'errore nel dialogo senza chiuderlo. Controllare i testi in italiano a 150%.
- Test attesi: `tests.test_qt_shell` 16/16 OK.

### fc63fa9 · Modifica dei fogli Info su Qt (2026-11-19)

- Nuovo: Home → Nuovo foglio Info…; nella pagina del foglio Proprietà… (nome e ambito), Sposta su/giù, Elimina foglio Info…, costanti modificabili (aggiungi, elimina, ↑↓), note con grassetto, corsivo e sottolineato (pulsanti o Ctrl+B/I/U) e Importa note… Codice in `trama_qt/info_editor.py`, `Project.change_info`/`move_info`/`update_info_sheets`. Le note si salvano dopo una pausa, uscendo dal foglio e prima di salvare. Gli stili sono contati in caratteri Python, quindi le emoji non spostano la formattazione.
- Da provare su Windows:
  - Nuovo foglio Info legato a una tabella, costante "Dose" = 10 e una formula della tabella che la usa: cambiando il valore la tabella si ricalcola.
  - Note con una parte in grassetto e un'emoji prima, salvare e riaprire in Qt e in Tk: formattazione nello stesso punto.
  - Eliminare il foglio.
- Test attesi: `tests.test_qt_shell` 15/15 OK.

### a22d53b · Famiglie di esperimenti su Qt (2026-11-19)

- Nuovo: Home → Duplica famiglia… e Salva famiglia come… (anche col tasto destro nel navigatore). Codice in `trama_qt/family.py` e `trama_qt/window.py`, più `Project.apply_family` e `Project.update_info_sheets`. Stesso motore della versione Tk (`analisi.family_workflow`): anteprima di tabelle, analisi, layout e fogli info; nome della nuova tabella o prefisso per gli altri fogli; layout inclusi. Copia e salvataggio girano in background e si possono annullare: annullando la copia non viene aggiunto niente. I risultati copiati si calcolano quando apri il foglio.
- Da provare su Windows:
  - Duplicare una tabella con grafico e layout: il nome già usato deve dare l'errore nel dialogo; con "Repeat" compaiono la tabella, il grafico e il layout copiati.
  - Salva famiglia come su un file nuovo, poi riaprirlo in Qt e in Tk.
  - Scegliere il file del progetto corrente deve dare l'errore.
- Test attesi: `tests.test_qt_shell` 14/14 OK.

### 597075b · Confronti a coppie e lettere compatte su Qt (2026-11-19)

- Nuovo: scheda Grafico, Confronti a coppie… e Lettere compatte… (`trama_qt/pairwise.py`, comando in `trama_qt/window.py`). Stessa sezione della ricetta della versione Tk: sorgente (ANOVA a una via con post-hoc, Kruskal–Wallis con Dunn, t-test appaiato fra due colonne del grafico), tutte o solo le coppie spuntate, asterischi o valore P, soglia, colore; in modalità lettere alfa, identificatori, posizione, dimensione e anteprima. Applica ricalcola il grafico; Rimuovi toglie i confronti.
- Da provare su Windows: tabella con due colonne, t-test appaiato Control/Treated, grafico a colonne delle due colonne, Confronti a coppie con valore P, Applica: compare la parentesi; poi Lettere compatte: compaiono le lettere e il foglio "Comparison letters". Salvare e riaprire in Qt e in Tk. Una soglia 2 deve dare errore. Controllare anche i testi in italiano.
- Test attesi: `tests.test_qt_shell` 13/13 OK.

### 714713a · Forme del grafico su Qt (2026-11-19)

- Nuovo: Grafico → Forme del grafico… (`trama_qt/shapes.py`): elenco con aggiungi, modifica, duplica, elimina, su/giù, elimina tutto; editor di linea (frecce: estremi, stile, dimensione), rettangolo ed ellisse (riempimento, motivo e suo colore), tratto, spessore, stile linea, opacità, livello sopra/sotto i dati, coordinate in frazioni del grafico o in unità dei dati. Stessi record e validazione di `analisi.graph_shapes`. Il disegno col mouse sul grafico resta in Tk.
- Da provare su Windows: grafico a colonne, rettangolo da (0,2; 0,3) a (0,6; 0,8) giallo con motivo diagonale + una freccia, Applica, salvare, riaprire in Qt e in Tk: forme identiche. Linea di lunghezza zero deve dare errore nel dialogo.
- Test attesi: `tests.test_qt_shell` 12/12 OK.

### 9dae6d2 · Formato della legenda su Qt (2026-11-19)

- Nuovo: in Format Graph, scheda Aspetto, il pulsante Formato legenda… (`trama_qt/legend.py`): titolo, colonne, ordine inverso, cornice (predefinita/visibile/nascosta), colori di sfondo e bordo, spessore, opacità, etichette delle singole voci, ripristino. Con questo Format Graph su Qt copre tutto quello che fa la versione Tk tranne le forme disegnate.
- Da provare su Windows: grafico XY, legenda con titolo "Gruppi", 1 colonna, cornice nascosta, etichetta di una voce cambiata, Applica, salvare, riaprire in Qt e in Tk: legenda identica. Colonne "abc" deve dare errore nel dialogo.
- Test attesi: `tests.test_qt_shell` 11/11 OK.

### 5e14f9d · Interruzioni degli assi su Qt (2026-11-19)

- Nuovo: in Format Graph, scheda Assi, sui grafici XY nativi c'è il riquadro Interruzioni asse (`trama_qt/axis_breaks.py`): asse, 2 o 3 segmenti, spazio, da/a/quota/intervallo per segmento, "Suggerisci dai dati", totale delle quote. Con un asse interrotto scala, minimo, massimo, passo e inizio di quell'asse restano disattivati. Interruzioni nuove che il grafico non può mostrare danno errore nel dialogo; quelle già salvate restano con la nota del motivo.
- Da provare su Windows: grafico XY, asse Y, 2 segmenti (5,5–6 al 50%, 6,2–6,8 al 50%), Applica, salvare, riaprire in Qt e in Tk: interruzione identica. Con quote che non fanno 100 deve comparire l'errore.
- Test attesi: `tests.test_qt_shell` 10/10 OK.

### a869f3b · Guide e bande degli assi su Qt (2026-11-19)

- Nuovo: in Format Graph, scheda Riferimenti, i pulsanti per tacche e griglie aggiuntive (guide) e per gli intervalli ombreggiati (bande) aprono i rispettivi elenchi (`trama_qt/axis_guides.py`): aggiungi, modifica, duplica, rimuovi; stessi record e stessa validazione del motore (`analisi.axis_guides`), limiti 60 guide e 12 bande. Prima restavano invariati e si modificavano solo in Tk.
- Da provare su Windows: su un grafico a colonne aggiungere una guida Y a 2,5 con etichetta e una banda Y da 4 a 6 con tratteggio, Applica, salvare, riaprire in Qt e in Tk (`--tk`): guide e bande identiche. Su un asse logaritmico un valore 0 deve dare l'errore nel dialogo, non un crash.
- Test attesi: `tests.test_qt_shell` 9/9 OK.

### d9cf4f1 · Annotazioni del grafico su Qt (2026-11-19)

- Nuovo: Grafico → Annotazioni grafico… (`trama_qt/annotations.py`): elenco, aggiungi, modifica, rimuovi; testo, unità (assi o dati), allineamento, posizione, freccia con destinazione, dimensione, colore. Validazione del motore (`analisi.graph_annotations`).
- Da provare su Windows: aggiungere un'annotazione con freccia, applicare, salvare, riaprire il `.alab` in Qt e in Tk (`--tk`): l'annotazione deve essere identica. Numeri con la virgola decimale.
- Test attesi: `tests.test_qt_shell` 8/8 OK.

### 56978a5 · Inspector dei grafici su Qt

- Nuovo: pannello laterale (Ctrl+Maiusc+I) con anteprima dal vivo, Applica/Annulla, clic sul grafico per scegliere il gruppo; prima di salvare, esportare o ricalcolare chiede cosa fare della bozza.
- Da provare su Windows: aprire l'Inspector su un box plot, cambiare colore e assi, salvare con la bozza aperta (deve comparire la domanda Applica/Scarta/Annulla).

### c0d3bd5, 05621e8, 6ee67d1 · Esportazioni, layout, Format Graph

- Esportazione grafici PNG/SVG/PDF/TIFF a 300 dpi verificata; layout PDF e SVG vettoriali; File → Esporta più fogli in PDF.
- Layout (Ctrl+L) nuovo e modifica; Format Graph (Ctrl+Maiusc+F).
- Da provare su Windows: esportare un layout in PDF e SVG e aprirli; esportare 3 fogli in un PDF e controllare l'ordine delle pagine.
