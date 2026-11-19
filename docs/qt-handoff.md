# Consegna Qt per Codex

Questo file è il canale fisso tra Claude e Codex per la migrazione a Qt (PR #56, ramo `claude/project-thread-4unaln`).
Claude lo aggiorna a ogni commit; la voce più recente sta in cima. Il piano complessivo è in `docs/qt-migration.md`.

## Procedura per Codex, a ogni avanzamento

1. `git fetch origin claude/project-thread-4unaln && git checkout claude/project-thread-4unaln && git pull --ff-only`
2. Leggi la voce più recente qui sotto (e quelle che non hai ancora visto, confrontando il commit).
3. Test: `python -m unittest tests.test_qt_shell` (offscreen; su Windows imposta `QT_QPA_PLATFORM=offscreen` solo per i test) più la tua suite completa.
4. Prova a mano su Windows quello che la voce indica in "Da provare su Windows", a 100% e 150% di scala.
5. Rispondi con un commento sulla PR #56 (o scrivilo a Luca): commit provato, esito dei test, problemi con passi per riprodurli.

Regole fisse: niente merge e niente cambio di versione da parte di Claude; la grafica nuova si fa solo su Qt (il Vetro su Tk è fermo); `trama_qt` non deve importare `tkinter`; Windows resta NON PROVATO finché Codex non lo conferma.

## Avanzamenti

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
